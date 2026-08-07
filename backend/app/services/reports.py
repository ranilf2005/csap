"""Renders self-contained HTML reports (no external assets) into DATA_DIR/reports."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Report
from app.services.storage import reports_dir

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "report_templates"

_env = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def render(template: str, **context: Any) -> str:
    return _env.get_template(template).render(
        generated_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        platform_version=settings.csap_version,
        **context,
    )


def save_report(
    db: Session,
    kind: str,
    title: str,
    html: str,
    connection_id: str | None = None,
    subject_id: str | None = None,
    summary: dict[str, Any] | None = None,
    created_by: str | None = None,
) -> Report:
    report = Report(
        kind=kind,
        title=title,
        connection_id=connection_id,
        subject_id=subject_id,
        summary=summary,
        created_by=created_by,
        stored_path="",
    )
    db.add(report)
    db.flush()

    path = reports_dir() / f"{report.id}.html"
    path.write_text(html, encoding="utf-8")
    report.stored_path = str(path)
    db.commit()
    db.refresh(report)
    logger.info("wrote %s report %s", kind, report.id)
    return report
