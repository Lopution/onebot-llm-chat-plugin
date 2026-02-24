"""WebUI auth ticket API.

Provides ``POST /auth/ticket`` to obtain a short-lived ticket for
URL-only channels (SSE, WS, file download) where ``Authorization``
headers cannot be set.
"""

from __future__ import annotations
from typing import Any, Callable, Dict

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from ..config import Config
from ..runtime import get_config as get_runtime_config
from .auth import create_webui_auth_dependency
from .auth_ticket import get_ticket_store
from .base_route import BaseRouteHelper


class TicketRequest(BaseModel):
    scope: str = "general"


def create_auth_router(
    *,
    settings_getter: Callable[[], Config] = get_runtime_config,
) -> APIRouter:
    auth_dependency = create_webui_auth_dependency(settings_getter=settings_getter)
    router = APIRouter(
        prefix="/auth",
        tags=["mika-webui-auth"],
        dependencies=[Depends(auth_dependency)],
    )

    @router.post("/ticket")
    async def issue_ticket(payload: TicketRequest, request: Request) -> Dict[str, Any]:
        store = get_ticket_store()
        client_host = str(getattr(request.client, "host", "") or "").strip()
        ticket, _ = store.issue(scope=payload.scope, client_host=client_host)
        return BaseRouteHelper.ok(
            {
                "ticket": ticket,
                "scope": payload.scope,
                "expires_in_seconds": 60,
            }
        )

    return router


__all__ = ["TicketRequest", "create_auth_router"]
