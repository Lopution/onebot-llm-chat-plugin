"""WebUI database maintenance APIs."""

from __future__ import annotations

from typing import Any, Callable, Dict

from fastapi import APIRouter, Depends

from ..config import Config
from ..runtime import get_config as get_runtime_config
from ..utils.db_maintenance import get_db_maintenance_service
from .auth import create_webui_auth_dependency
from .base_route import BaseRouteHelper


def create_maintenance_router(
    *,
    settings_getter: Callable[[], Config] = get_runtime_config,
) -> APIRouter:
    auth_dependency = create_webui_auth_dependency(settings_getter=settings_getter)
    router = APIRouter(
        prefix="/maintenance",
        tags=["mika-webui-maintenance"],
        dependencies=[Depends(auth_dependency)],
    )

    @router.post("/run")
    async def run_db_maintenance() -> Dict[str, Any]:
        cfg = settings_getter()
        result = await get_db_maintenance_service().run_once(plugin_cfg=cfg, request_id="webui")
        return BaseRouteHelper.ok(result)

    return router


__all__ = ["create_maintenance_router"]

