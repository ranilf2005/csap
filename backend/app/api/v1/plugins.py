from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.plugins import registry
from app.schemas import PluginOut

router = APIRouter(prefix="/plugins", tags=["plugins"])


@router.get("", response_model=list[PluginOut])
def list_plugins(_user: CurrentUser) -> list[PluginOut]:
    return [
        PluginOut(
            key=p.manifest.key,
            display_name=p.manifest.display_name,
            vendor=p.manifest.vendor,
            description=p.manifest.description,
            default_port=p.manifest.default_port,
            engines=list(p.manifest.engines),
            entity_types=list(p.manifest.entity_types),
        )
        for p in registry.available()
    ]
