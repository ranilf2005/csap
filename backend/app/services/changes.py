"""Orchestrates the change lifecycle: upload -> validate -> plan -> deploy -> report."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import ChangeRequest, Connection, InventoryItem, Job, Snapshot
from app.plugins import registry
from app.plugins.base import ChangePlan, DeploymentResult, DiscoveryResult, SecurityPlugin
from app.services import reports
from app.services.connections import to_context
from app.services.workbook import WorkbookError, parse_workbook, read_provenance

logger = logging.getLogger(__name__)


def latest_snapshot(db: Session, connection_id: str) -> Snapshot | None:
    return (
        db.query(Snapshot)
        .filter(Snapshot.connection_id == connection_id)
        .order_by(Snapshot.created_at.desc())
        .first()
    )


def discovery_from_snapshot(db: Session, snapshot: Snapshot) -> DiscoveryResult:
    """Rebuild a DiscoveryResult from stored inventory so validation needs no FMC call."""
    items = db.query(InventoryItem).filter(InventoryItem.snapshot_id == snapshot.id).all()
    return DiscoveryResult(
        product_version=snapshot.product_version,
        items=[
            {
                "item_type": item.item_type,
                "external_id": item.external_id,
                "name": item.name,
                "payload": item.payload,
            }
            for item in items
        ],
        summary=snapshot.summary or {},
    )


def _plugin_for(db: Session, change: ChangeRequest) -> tuple[SecurityPlugin, Connection]:
    connection = db.get(Connection, change.connection_id)
    if connection is None:
        raise ValueError("the managed system for this change was removed")
    return registry.get(connection.product), connection


def _provenance_issues(change: ChangeRequest, snapshot: Snapshot) -> list[dict]:
    """Block a workbook exported from an older snapshot than the one we are validating against.

    Without this, a second administrator can overwrite changes they never saw.
    """
    marks = read_provenance(Path(change.stored_path))
    source = marks.get("snapshot", "")

    if not source:
        return [
            {
                "severity": "warning", "sheet": "-", "row": None, "field": None,
                "message": "This workbook was not exported by CSAP, so it cannot be checked "
                           "against the configuration you started from.",
                "remediation": "Download 'Current config' from the latest discovery and copy "
                               "your changes into it, so CSAP can confirm nothing moved "
                               "underneath you.",
            }
        ]

    if source == snapshot.id:
        return []

    return [
        {
            "severity": "error", "sheet": "-", "row": None, "field": None,
            "message": f"The device configuration changed after this workbook was exported "
                       f"(exported {marks.get('exported', 'earlier')}). Someone else may have "
                       f"made changes you cannot see.",
            "remediation": "Download 'Current config' again from the latest discovery, re-apply "
                           "your edits to that file and upload it. This prevents overwriting "
                           "another administrator's work.",
        }
    ]


def validate_change(db: Session, change: ChangeRequest, actor: str | None = None) -> ChangeRequest:
    """Parse the workbook, validate it against the snapshot, and store a validation report."""
    plugin, connection = _plugin_for(db, change)
    snapshot = db.get(Snapshot, change.snapshot_id) if change.snapshot_id else None
    if snapshot is None:
        raise ValueError("run a discovery first: validation compares the workbook against a snapshot")

    discovery = discovery_from_snapshot(db, snapshot)

    try:
        rows = parse_workbook(Path(change.stored_path), plugin.template_spec(discovery))
    except WorkbookError as exc:
        change.status = "invalid"
        change.error_count = 1
        change.validation = {
            "issues": [
                {
                    "severity": "error", "sheet": "-", "row": None, "field": None,
                    "message": str(exc),
                    "remediation": "Re-download the template, copy your rows into it and upload again.",
                }
            ]
        }
        db.commit()
        return change

    result = plugin.validate(rows, discovery)
    issues = [
        {
            "severity": issue.severity,
            "sheet": issue.sheet,
            "row": issue.row,
            "field": issue.field,
            "message": issue.message,
            "remediation": issue.remediation,
        }
        for issue in result.issues
    ]
    issues = _provenance_issues(change, snapshot) + issues
    blocking = any(i["severity"] == "error" for i in issues)

    change.rows = rows
    change.validation = {"issues": issues}
    change.error_count = sum(1 for i in issues if i["severity"] == "error")
    change.warning_count = sum(1 for i in issues if i["severity"] == "warning")
    change.status = "validated" if not blocking else "invalid"

    if not blocking:
        plan = plugin.plan(rows, discovery)
        change.plan = _plan_to_dict(plan)
        change.plan["preview"] = plugin.preview(plan, host=connection.host)
        change.change_count = plan.total
        change.status = "planned"

    db.commit()

    html = reports.render(
        "validation.html",
        title="Change validation report",
        connection=connection,
        change=change,
        snapshot=snapshot,
        issues=issues,
        rows=rows,
    )
    reports.save_report(
        db,
        kind="validation",
        title=f"Validation: {change.filename}",
        html=html,
        connection_id=connection.id,
        subject_id=change.id,
        summary={
            "errors": change.error_count,
            "warnings": change.warning_count,
            "changes": change.change_count,
        },
        created_by=actor,
    )
    db.refresh(change)
    return change


def _plan_to_dict(plan: ChangePlan) -> dict:
    return {
        "creates": plan.creates,
        "updates": plan.updates,
        "deletes": plan.deletes,
        "total": plan.total,
    }


def _plan_from_dict(data: dict) -> ChangePlan:
    return ChangePlan(
        creates=data.get("creates", []),
        updates=data.get("updates", []),
        deletes=data.get("deletes", []),
    )


def run_deployment(db: Session, job_id: str) -> None:
    """Celery entry point. Applies (or dry-runs) a validated change request."""
    job = db.get(Job, job_id)
    if job is None:
        logger.error("deployment job %s not found", job_id)
        return

    job.status = "running"
    job.started_at = datetime.now(UTC)
    db.commit()

    params = job.result or {}
    change_id = params.get("change_id")
    dry_run = bool(params.get("dry_run", True))
    engine = params.get("engine", "rest")
    device_ids = params.get("deploy_to_devices") or []

    def progress(percent: int, message: str) -> None:
        job.progress = max(0, min(percent, 100))
        job.message = message
        db.commit()

    try:
        change = db.get(ChangeRequest, change_id)
        if change is None:
            raise ValueError("change request no longer exists")
        if not change.plan:
            raise ValueError("this change has no plan; validate it first")
        if change.error_count and not dry_run:
            raise ValueError("cannot deploy a change that still has validation errors")

        plugin, connection = _plugin_for(db, change)
        if not dry_run:
            change.status = "deploying"
            db.commit()

        result = plugin.deploy(
            to_context(connection),
            _plan_from_dict(change.plan),
            engine=engine,
            dry_run=dry_run,
            progress=progress,
        )

        change.deployment = {
            "ok": result.ok,
            "applied": result.applied,
            "failed": result.failed,
            "dry_run": dry_run,
            "engine": engine,
            "details": result.details,
            "finished_at": datetime.now(UTC).isoformat(),
        }
        if not dry_run:
            change.status = "deployed" if result.ok else "failed"
        db.commit()

        # Objects and rules now exist on the FMC; pushing them to the FTDs is a separate step.
        device_result = None
        if not dry_run and result.ok and device_ids:
            progress(96, "deploying to selected devices")
            device_result = plugin.push_to_devices(
                to_context(connection), device_ids, progress=progress
            )
            change.deployment = {**change.deployment, "device_deployment": device_result}
            if not device_result.get("ok"):
                change.status = "failed"
            db.commit()

        html = reports.render(
            "deployment.html",
            title="Dry run report" if dry_run else "Deployment report",
            connection=connection,
            change=change,
            result=change.deployment,
            preview=(change.plan or {}).get("preview", []),
        )
        report = reports.save_report(
            db,
            kind="dry_run" if dry_run else "deployment",
            title=f"{'Dry run' if dry_run else 'Deployment'}: {change.filename}",
            html=html,
            connection_id=connection.id,
            subject_id=change.id,
            summary={"applied": result.applied, "failed": result.failed},
            created_by=job.created_by,
        )

        job.status = "succeeded" if result.ok else "failed"
        job.progress = 100
        job.message = (
            f"Dry run: {len(result.details)} operations planned"
            if dry_run
            else f"Applied {result.applied}, failed {result.failed}"
        )
        if device_result is not None:
            if device_result.get("skipped"):
                job.message += " (nothing pending on the selected devices)"
            else:
                names = ", ".join(d["name"] for d in device_result.get("devices", []))
                job.message += f" | device deployment {device_result.get('state')}: {names}"
            if not device_result.get("ok"):
                job.status = "failed"

        job.result = {
            "change_id": change.id,
            "report_id": report.id,
            "dry_run": dry_run,
            "engine": engine,
            "applied": result.applied,
            "failed": result.failed,
            "device_deployment": device_result,
        }
        job.finished_at = datetime.now(UTC)
        db.commit()

    except Exception as exc:
        db.rollback()
        job = db.get(Job, job_id)
        if job is not None:
            job.status = "failed"
            job.message = f"{type(exc).__name__}: {exc}"
            job.finished_at = datetime.now(UTC)
            db.commit()
        change = db.get(ChangeRequest, change_id) if change_id else None
        if change is not None and change.status == "deploying":
            change.status = "failed"
            db.commit()
        logger.exception("deployment job %s failed", job_id)


def run_rollback(db: Session, job_id: str) -> None:
    """Reverts the last applied deployment for a change request."""
    job = db.get(Job, job_id)
    if job is None:
        return

    job.status = "running"
    job.started_at = datetime.now(UTC)
    db.commit()

    change_id = (job.result or {}).get("change_id")

    try:
        change = db.get(ChangeRequest, change_id)
        if change is None or not change.deployment:
            raise ValueError("nothing to roll back")
        if change.deployment.get("dry_run"):
            raise ValueError("a dry run has nothing to roll back")

        plugin, connection = _plugin_for(db, change)
        previous = DeploymentResult(
            ok=change.deployment.get("ok", False),
            applied=change.deployment.get("applied", 0),
            failed=change.deployment.get("failed", 0),
            details=change.deployment.get("details", []),
        )
        result = plugin.rollback(to_context(connection), previous)

        change.status = "rolled_back" if result.ok else "failed"
        change.deployment = {**change.deployment, "rollback": {
            "ok": result.ok,
            "reverted": result.applied,
            "failed": result.failed,
            "details": result.details,
        }}
        db.commit()

        job.status = "succeeded" if result.ok else "failed"
        job.progress = 100
        job.message = f"Reverted {result.applied}, failed {result.failed}"
        job.result = {"change_id": change.id, "reverted": result.applied, "failed": result.failed}
        job.finished_at = datetime.now(UTC)
        db.commit()

    except Exception as exc:
        db.rollback()
        job = db.get(Job, job_id)
        if job is not None:
            job.status = "failed"
            job.message = f"{type(exc).__name__}: {exc}"
            job.finished_at = datetime.now(UTC)
            db.commit()
        logger.exception("rollback job %s failed", job_id)
