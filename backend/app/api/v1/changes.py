import logging
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import Response

from app.api.deps import CurrentUser, DbSession, record_audit
from app.models import ChangeRequest, Connection, InventoryItem, Job
from app.schemas import (
    ChangeRequestOut,
    ChangeRequestSummary,
    DeployRequest,
    DeployTargetOut,
    JobOut,
)
from app.services import changes as change_service
from app.services.storage import safe_filename, uploads_dir
from app.services.templates import build_findings_workbook
from app.workers.tasks import deploy_task, rollback_task

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/changes", tags=["changes"])

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
ALLOWED_SUFFIXES = (".xlsx", ".xlsm")


def _get_or_404(db: DbSession, change_id: str) -> ChangeRequest:
    change = db.get(ChangeRequest, change_id)
    if change is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Change request not found")
    return change


@router.post("", response_model=ChangeRequestOut, status_code=status.HTTP_201_CREATED)
async def upload_change(
    request: Request,
    user: CurrentUser,
    db: DbSession,
    connection_id: str = Form(...),
    file: UploadFile = File(...),
) -> ChangeRequest:
    """Upload a completed workbook; it is parsed and validated immediately."""
    connection = db.get(Connection, connection_id)
    if connection is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Connection not found")

    original = safe_filename(file.filename or "changes.xlsx", "changes.xlsx")
    if not original.lower().endswith(ALLOWED_SUFFIXES):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only .xlsx or .xlsm workbooks are accepted")

    snapshot = change_service.latest_snapshot(db, connection_id)
    if snapshot is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Run a discovery for this system first; validation needs a snapshot to compare against",
        )

    change = ChangeRequest(
        connection_id=connection_id,
        snapshot_id=snapshot.id,
        filename=original,
        stored_path="",
        created_by=user.id,
    )
    db.add(change)
    db.flush()

    target = uploads_dir() / f"{change.id}.xlsx"
    written = 0
    try:
        with target.open("wb") as sink:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Workbook exceeds the 25 MB limit"
                    )
                sink.write(chunk)
    except HTTPException:
        target.unlink(missing_ok=True)
        db.rollback()
        raise

    change.stored_path = str(target)
    db.commit()

    try:
        change_service.validate_change(db, change, actor=user.email)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None

    record_audit(
        db,
        request,
        "change.upload",
        actor=user.email,
        target_type="change",
        target_id=change.id,
        detail={"filename": original, "errors": change.error_count},
    )
    return change


@router.get("", response_model=list[ChangeRequestSummary])
def list_changes(
    _user: CurrentUser, db: DbSession, connection_id: str | None = None, limit: int = 50
) -> list[ChangeRequest]:
    query = db.query(ChangeRequest)
    if connection_id:
        query = query.filter(ChangeRequest.connection_id == connection_id)
    return query.order_by(ChangeRequest.created_at.desc()).limit(min(limit, 200)).all()


@router.get("/{change_id}", response_model=ChangeRequestOut)
def get_change(change_id: str, _user: CurrentUser, db: DbSession) -> ChangeRequest:
    return _get_or_404(db, change_id)


@router.get("/{change_id}/findings")
def download_findings(change_id: str, _user: CurrentUser, db: DbSession) -> Response:
    """Every finding as a spreadsheet, including what to do about each one."""
    change = _get_or_404(db, change_id)
    connection = db.get(Connection, change.connection_id)

    content = build_findings_workbook(
        (change.validation or {}).get("issues", []),
        change.filename,
        connection.name if connection else "unknown system",
        {
            "errors": change.error_count,
            "warnings": change.warning_count,
            "changes": change.change_count,
        },
    )
    stem = safe_filename(change.filename.rsplit(".", 1)[0], "changes")
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{stem}_findings.xlsx"'},
    )


@router.post("/{change_id}/revalidate", response_model=ChangeRequestOut)
def revalidate(change_id: str, request: Request, user: CurrentUser, db: DbSession) -> ChangeRequest:
    """Re-run validation, e.g. after a fresh discovery changed the baseline."""
    change = _get_or_404(db, change_id)
    snapshot = change_service.latest_snapshot(db, change.connection_id)
    if snapshot is not None:
        change.snapshot_id = snapshot.id
        db.commit()
    try:
        change_service.validate_change(db, change, actor=user.email)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None

    record_audit(
        db, request, "change.revalidate", actor=user.email, target_type="change", target_id=change.id
    )
    return change


@router.get("/{change_id}/targets", response_model=list[DeployTargetOut])
def list_targets(change_id: str, _user: CurrentUser, db: DbSession) -> list[DeployTargetOut]:
    """Managed devices found during discovery, for choosing what to deploy to."""
    change = _get_or_404(db, change_id)
    items = (
        db.query(InventoryItem)
        .filter(InventoryItem.snapshot_id == change.snapshot_id, InventoryItem.item_type == "device")
        .order_by(InventoryItem.name)
        .all()
    )
    return [
        DeployTargetOut(
            id=item.external_id or "",
            name=item.name or "unnamed",
            model=(item.payload or {}).get("model"),
            health=(item.payload or {}).get("healthStatus"),
        )
        for item in items
        if item.external_id
    ]


@router.post("/{change_id}/deploy", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
def deploy(
    change_id: str, payload: DeployRequest, request: Request, user: CurrentUser, db: DbSession
) -> Job:
    change = _get_or_404(db, change_id)

    if not change.plan:
        raise HTTPException(status.HTTP_409_CONFLICT, "This change has no plan; fix validation errors first")
    if change.error_count:
        raise HTTPException(status.HTTP_409_CONFLICT, "This change still has validation errors")
    if not payload.dry_run and change.warning_count and not payload.acknowledge_warnings:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"This change has {change.warning_count} unresolved warning(s). Fix them, or confirm "
            "you have reviewed each one before applying.",
        )
    if not payload.dry_run and not payload.confirm:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Set confirm=true to apply changes to the live device"
        )
    if change.status == "deploying":
        raise HTTPException(status.HTTP_409_CONFLICT, "A deployment is already running for this change")

    job = Job(
        connection_id=change.connection_id,
        job_type="dry_run" if payload.dry_run else "deploy",
        created_by=user.id,
        result={
            "change_id": change.id,
            "dry_run": payload.dry_run,
            "engine": payload.engine,
            "deploy_to_devices": [] if payload.dry_run else payload.deploy_to_devices,
        },
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    change.job_id = job.id
    db.commit()

    deploy_task.delay(job.id)
    record_audit(
        db,
        request,
        "change.deploy" if not payload.dry_run else "change.dry_run",
        actor=user.email,
        target_type="change",
        target_id=change.id,
        detail={
            "engine": payload.engine,
            "operations": change.change_count,
            "devices": payload.deploy_to_devices,
        },
    )
    return job


@router.post("/{change_id}/rollback", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
def rollback(change_id: str, request: Request, user: CurrentUser, db: DbSession) -> Job:
    change = _get_or_404(db, change_id)
    if not change.deployment or change.deployment.get("dry_run"):
        raise HTTPException(status.HTTP_409_CONFLICT, "There is no applied deployment to roll back")

    job = Job(
        connection_id=change.connection_id,
        job_type="rollback",
        created_by=user.id,
        result={"change_id": change.id},
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    rollback_task.delay(job.id)
    record_audit(db, request, "change.rollback", actor=user.email, target_type="change", target_id=change.id)
    return job


@router.delete("/{change_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_change(change_id: str, request: Request, user: CurrentUser, db: DbSession) -> None:
    change = _get_or_404(db, change_id)
    Path(change.stored_path).unlink(missing_ok=True)
    db.delete(change)
    db.commit()
    record_audit(db, request, "change.delete", actor=user.email, target_type="change", target_id=change_id)
