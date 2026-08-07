from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import DbSession
from app.core.config import settings

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
def live() -> dict[str, str]:
    return {"status": "ok", "version": settings.csap_version}


@router.get("/ready")
def ready(db: DbSession) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ready", "version": settings.csap_version}
