from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import func

from app.api.deps import CurrentUser, DbSession
from app.models import Connection, InventoryItem, Report, Snapshot
from app.plugins import registry
from app.schemas import InventoryItemOut, InventoryPage, PageMeta, ReportOut, SnapshotOut
from app.services import reports
from app.services.changes import discovery_from_snapshot
from app.services.templates import build_workbook

router = APIRouter(tags=["inventory"])


@router.get("/snapshots", response_model=list[SnapshotOut])
def list_snapshots(
    _user: CurrentUser, db: DbSession, connection_id: str | None = None, limit: int = 50
) -> list[Snapshot]:
    query = db.query(Snapshot)
    if connection_id:
        query = query.filter(Snapshot.connection_id == connection_id)
    return query.order_by(Snapshot.created_at.desc()).limit(min(limit, 200)).all()


@router.get("/snapshots/{snapshot_id}/inventory", response_model=InventoryPage)
def get_inventory(
    snapshot_id: str,
    _user: CurrentUser,
    db: DbSession,
    item_type: str | None = None,
    search: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> InventoryPage:
    if db.get(Snapshot, snapshot_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Snapshot not found")

    query = db.query(InventoryItem).filter(InventoryItem.snapshot_id == snapshot_id)
    if item_type:
        query = query.filter(InventoryItem.item_type == item_type)
    if search:
        query = query.filter(InventoryItem.name.ilike(f"%{search}%"))

    total = query.with_entities(func.count(InventoryItem.id)).scalar() or 0
    items = query.order_by(InventoryItem.item_type, InventoryItem.name).offset(offset).limit(limit).all()

    return InventoryPage(
        meta=PageMeta(total=total, limit=limit, offset=offset),
        items=[InventoryItemOut.model_validate(i) for i in items],
    )


def _workbook_response(
    db: DbSession, snapshot_id: str, *, populated: bool
) -> Response:
    snapshot = db.get(Snapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Snapshot not found")

    plugin = registry.get(snapshot.product)
    discovery = discovery_from_snapshot(db, snapshot)
    content = build_workbook(
        plugin.template_spec(discovery),
        snapshot.product,
        snapshot.product_version,
        existing=plugin.existing_rows(discovery) if populated else None,
        reference_sheets=set(plugin.reference_sheets),
        snapshot_id=snapshot.id,
        snapshot_label=snapshot.label,
        guide=plugin.field_guide(),
    )

    connection = db.get(Connection, snapshot.connection_id)
    stem = (connection.name if connection else snapshot.product).replace(" ", "_")
    suffix = "current_config" if populated else "blank_template"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{stem}_{suffix}.xlsx"'},
    )


@router.get("/snapshots/{snapshot_id}/template")
def download_template(snapshot_id: str, _user: CurrentUser, db: DbSession) -> Response:
    """Empty workbook: correct sheets and headers, no rows. For bulk additions."""
    return _workbook_response(db, snapshot_id, populated=False)


@router.get("/snapshots/{snapshot_id}/export")
def export_configuration(snapshot_id: str, _user: CurrentUser, db: DbSession) -> Response:
    """Workbook pre-filled with everything in the snapshot, ready to edit in place."""
    return _workbook_response(db, snapshot_id, populated=True)


@router.post("/snapshots/{snapshot_id}/report", response_model=ReportOut, status_code=status.HTTP_201_CREATED)
def generate_inventory_report(snapshot_id: str, user: CurrentUser, db: DbSession) -> Report:
    """Render a shareable HTML inventory report for a snapshot."""
    snapshot = db.get(Snapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Snapshot not found")

    connection = db.get(Connection, snapshot.connection_id)
    items = (
        db.query(InventoryItem)
        .filter(InventoryItem.snapshot_id == snapshot_id)
        .order_by(InventoryItem.item_type, InventoryItem.name)
        .limit(5000)
        .all()
    )

    html = reports.render(
        "inventory.html",
        title="Inventory report",
        connection=connection,
        snapshot=snapshot,
        items=items,
    )
    return reports.save_report(
        db,
        kind="inventory",
        title=f"Inventory: {snapshot.label}",
        html=html,
        connection_id=snapshot.connection_id,
        subject_id=snapshot_id,
        summary=snapshot.summary,
        created_by=user.email,
    )


@router.delete("/snapshots/{snapshot_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_snapshot(snapshot_id: str, _user: CurrentUser, db: DbSession) -> None:
    snapshot = db.get(Snapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Snapshot not found")
    db.delete(snapshot)
    db.commit()
