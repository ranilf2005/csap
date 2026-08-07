from fastapi import APIRouter

from app.api.v1 import (
    audit,
    auth,
    changes,
    connections,
    discovery,
    drift,
    health,
    inventory,
    plugins,
    reports,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(plugins.router)
api_router.include_router(connections.router)
api_router.include_router(discovery.router)
api_router.include_router(inventory.router)
api_router.include_router(changes.router)
api_router.include_router(reports.router)
api_router.include_router(drift.router)
api_router.include_router(audit.router)
