import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging
from app.plugins import registry

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    keys = [p.manifest.key for p in registry.available()]
    logger.info("CSAP %s ready with plugins: %s", settings.csap_version, ", ".join(keys) or "none")
    yield


# The interactive docs describe every endpoint and parameter to anyone who can
# reach the port, so they are opt-in outside development.
_docs_enabled = settings.enable_api_docs

app = FastAPI(
    title=settings.app_name,
    version=settings.csap_version,
    description="Plugin-based automation for the Cisco security portfolio.",
    docs_url="/api/docs" if _docs_enabled else None,
    openapi_url="/api/openapi.json" if _docs_enabled else None,
    redoc_url=None,
    lifespan=lifespan,
)

app.include_router(api_router)


@app.exception_handler(Exception)
def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    # Never leak stack traces or connection strings to the client.
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
