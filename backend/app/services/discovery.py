"""Discovery orchestration: runs a plugin's discover(), persists a snapshot."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import Connection, InventoryItem, Job, Snapshot
from app.plugins import registry
from app.services.connections import to_context

logger = logging.getLogger(__name__)


def run_discovery(db: Session, job_id: str) -> None:
    job = db.get(Job, job_id)
    if job is None:
        logger.error("discovery job %s not found", job_id)
        return

    job.status = "running"
    job.started_at = datetime.now(UTC)
    db.commit()

    def progress(percent: int, message: str) -> None:
        job.progress = max(0, min(percent, 100))
        job.message = message
        db.commit()

    try:
        conn = db.get(Connection, job.connection_id)
        if conn is None:
            raise ValueError("connection was removed before the job started")

        plugin = registry.get(conn.product)
        result = plugin.discover(to_context(conn), progress=progress)

        snapshot = Snapshot(
            connection_id=conn.id,
            job_id=job.id,
            label=f"{conn.name} {datetime.now(UTC):%Y-%m-%d %H:%M UTC}",
            product=conn.product,
            product_version=result.product_version,
            object_count=len(result.items),
            summary=result.summary,
        )
        db.add(snapshot)
        db.flush()

        db.bulk_save_objects(
            [
                InventoryItem(
                    snapshot_id=snapshot.id,
                    item_type=item["item_type"],
                    external_id=item.get("external_id"),
                    name=item.get("name"),
                    payload=item["payload"],
                )
                for item in result.items
            ]
        )

        conn.last_status = "connected"
        conn.last_error = None
        conn.detected_version = result.product_version or conn.detected_version

        job.status = "succeeded"
        job.progress = 100
        job.message = f"Discovered {len(result.items)} objects"
        job.result = {"snapshot_id": snapshot.id, "summary": result.summary}
        job.finished_at = datetime.now(UTC)
        db.commit()
        logger.info("discovery job %s finished: %s objects", job_id, len(result.items))

    except Exception as exc:
        db.rollback()
        job = db.get(Job, job_id)
        if job is not None:
            job.status = "failed"
            job.message = f"{type(exc).__name__}: {exc}"
            job.finished_at = datetime.now(UTC)
            db.commit()
        logger.exception("discovery job %s failed", job_id)
