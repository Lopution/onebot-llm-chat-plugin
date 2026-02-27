"""WebUI backend router factory."""

from __future__ import annotations

from typing import Callable, Optional

from fastapi import APIRouter

from ..config import Config
from ..runtime import get_config as get_runtime_config
from .api_auth import create_auth_router
from .api_config import create_config_router
from .api_dashboard import create_dashboard_router
from .api_backup import create_backup_router
from .api_knowledge import create_knowledge_router
from .api_live_chat import create_live_chat_router
from .api_log import create_log_router
from .api_memory import create_memory_router
from .api_persona import create_persona_router
from .api_session import create_session_router
from .api_tools import create_tools_router
from .api_user_profile import create_user_profile_router
from .api_trace import create_trace_router
from .api_maintenance import create_maintenance_router


def normalize_base_path(value: str) -> str:
    """Normalize webui base path to `/segment` style."""
    text = str(value or "/webui").strip()
    if not text:
        text = "/webui"
    if not text.startswith("/"):
        text = "/" + text
    if text != "/":
        text = text.rstrip("/")
    return text or "/webui"


def create_webui_router(
    *,
    settings_getter: Callable[[], Config] = get_runtime_config,
    base_path: Optional[str] = None,
) -> APIRouter:
    config = settings_getter()
    resolved_base_path = normalize_base_path(
        base_path if base_path is not None else getattr(config, "mika_webui_base_path", "/webui")
    )
    router = APIRouter(prefix=f"{resolved_base_path}/api", tags=["mika-webui"])
    router.include_router(create_auth_router(settings_getter=settings_getter))
    router.include_router(create_dashboard_router(settings_getter=settings_getter))
    router.include_router(create_log_router(settings_getter=settings_getter))
    router.include_router(create_config_router(settings_getter=settings_getter))
    router.include_router(create_knowledge_router(settings_getter=settings_getter))
    router.include_router(create_memory_router(settings_getter=settings_getter))
    router.include_router(create_session_router(settings_getter=settings_getter))
    router.include_router(create_persona_router(settings_getter=settings_getter))
    router.include_router(create_tools_router(settings_getter=settings_getter))
    router.include_router(create_user_profile_router(settings_getter=settings_getter))
    router.include_router(create_trace_router(settings_getter=settings_getter))
    router.include_router(create_maintenance_router(settings_getter=settings_getter))
    router.include_router(create_backup_router(settings_getter=settings_getter))
    router.include_router(create_live_chat_router(settings_getter=settings_getter))
    return router


__all__ = ["create_webui_router", "normalize_base_path"]
