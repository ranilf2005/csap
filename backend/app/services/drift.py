"""Compares two snapshots of the same system and reports what changed."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models import Connection, InventoryItem, Snapshot
from app.services import reports

logger = logging.getLogger(__name__)

# Volatile FMC bookkeeping fields that would otherwise show up as false drift.
IGNORED_FIELDS = {"metadata", "links", "version", "timestamp", "lastUser", "id"}


def _fingerprint(payload: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in payload.items() if k not in IGNORED_FIELDS}


def _load(db: Session, snapshot_id: str) -> dict[tuple[str, str], InventoryItem]:
    items = db.query(InventoryItem).filter(InventoryItem.snapshot_id == snapshot_id).all()
    return {(item.item_type, (item.name or item.id).lower()): item for item in items}


def compare(db: Session, baseline_id: str, current_id: str) -> dict[str, Any]:
    baseline = _load(db, baseline_id)
    current = _load(db, current_id)

    added, removed, modified = [], [], []

    for key, item in current.items():
        if key not in baseline:
            added.append({"item_type": item.item_type, "name": item.name})

    for key, item in baseline.items():
        if key not in current:
            removed.append({"item_type": item.item_type, "name": item.name})
            continue
        before, after = _fingerprint(item.payload), _fingerprint(current[key].payload)
        if before != after:
            changed_fields = sorted(
                {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
            )
            modified.append(
                {
                    "item_type": item.item_type,
                    "name": item.name,
                    "fields": changed_fields,
                    "before": {k: before.get(k) for k in changed_fields},
                    "after": {k: after.get(k) for k in changed_fields},
                }
            )

    for bucket in (added, removed, modified):
        bucket.sort(key=lambda row: (row["item_type"], row["name"] or ""))

    return {
        "added": added,
        "removed": removed,
        "modified": modified,
        "counts": {"added": len(added), "removed": len(removed), "modified": len(modified)},
        "has_drift": bool(added or removed or modified),
    }


def run_drift(db: Session, baseline_id: str, current_id: str, actor: str | None = None) -> dict[str, Any]:
    baseline = db.get(Snapshot, baseline_id)
    current = db.get(Snapshot, current_id)
    if baseline is None or current is None:
        raise ValueError("both snapshots must exist")
    if baseline.connection_id != current.connection_id:
        raise ValueError("snapshots belong to different systems")

    result = compare(db, baseline_id, current_id)
    connection = db.get(Connection, current.connection_id)

    html = reports.render(
        "drift.html",
        title="Configuration drift report",
        connection=connection,
        baseline=baseline,
        current=current,
        drift=result,
    )
    report = reports.save_report(
        db,
        kind="drift",
        title=f"Drift: {baseline.label} vs {current.label}",
        html=html,
        connection_id=current.connection_id,
        subject_id=current_id,
        summary=result["counts"],
        created_by=actor,
    )
    return {"report_id": report.id, **result["counts"], "has_drift": result["has_drift"]}
