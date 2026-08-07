from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.api.deps import CurrentUser, DbSession, record_audit
from app.models import Report
from app.schemas import ReportOut
from app.services.storage import reports_dir, resolve_within

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("", response_model=list[ReportOut])
def list_reports(
    _user: CurrentUser,
    db: DbSession,
    kind: str | None = None,
    connection_id: str | None = None,
    subject_id: str | None = None,
    limit: int = 100,
) -> list[Report]:
    query = db.query(Report)
    if kind:
        query = query.filter(Report.kind == kind)
    if connection_id:
        query = query.filter(Report.connection_id == connection_id)
    if subject_id:
        query = query.filter(Report.subject_id == subject_id)
    return query.order_by(Report.created_at.desc()).limit(min(limit, 500)).all()


@router.get("/{report_id}/html", response_class=Response)
def get_report_html(report_id: str, _user: CurrentUser, db: DbSession) -> Response:
    report = db.get(Report, report_id)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found")

    try:
        path = resolve_within(reports_dir(), report.stored_path)
        html = path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        raise HTTPException(status.HTTP_410_GONE, "The report file is no longer available") from None

    return Response(content=html, media_type="text/html; charset=utf-8")


@router.get("/{report_id}/download", response_class=Response)
def download_report(report_id: str, _user: CurrentUser, db: DbSession) -> Response:
    report = db.get(Report, report_id)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found")

    try:
        path = resolve_within(reports_dir(), report.stored_path)
        html = path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        raise HTTPException(status.HTTP_410_GONE, "The report file is no longer available") from None

    stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in report.title)[:80]
    return Response(
        content=html,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{stem}.html"'},
    )


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_report(report_id: str, request: Request, user: CurrentUser, db: DbSession) -> None:
    report = db.get(Report, report_id)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found")
    Path(report.stored_path).unlink(missing_ok=True)
    db.delete(report)
    db.commit()
    record_audit(db, request, "report.delete", actor=user.email, target_type="report", target_id=report_id)
