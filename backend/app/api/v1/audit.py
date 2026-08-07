from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DbSession
from app.models import AuditLog
from app.schemas import AuditLogOut

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=list[AuditLogOut])
def list_audit_events(
    _user: CurrentUser,
    db: DbSession,
    action: str | None = None,
    actor: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list[AuditLog]:
    query = db.query(AuditLog)
    if action:
        query = query.filter(AuditLog.action == action)
    if actor:
        query = query.filter(AuditLog.actor.ilike(f"%{actor}%"))
    return query.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit).all()
