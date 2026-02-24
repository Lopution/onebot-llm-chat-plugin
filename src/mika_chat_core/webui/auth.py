"""WebUI auth dependency."""

from __future__ import annotations

import logging
from typing import Callable

from fastapi import Header, HTTPException, Request

from ..config import Config
from ..core_service import _extract_auth_token, _is_loopback_client, _tokens_match
from ..runtime import get_config as get_runtime_config
from .auth_ticket import get_ticket_store

log = logging.getLogger(__name__)
_query_token_deprecation_warned = False


def create_webui_auth_dependency(
    *,
    settings_getter: Callable[[], Config] = get_runtime_config,
):
    """Create FastAPI dependency for WebUI authentication."""

    async def _require_webui_auth(
        request: Request,
        authorization: str | None = Header(default=None),
        x_mika_webui_token: str | None = Header(default=None),
    ) -> None:
        config = settings_getter()
        required_token = str(getattr(config, "mika_webui_token", "") or "").strip()
        provided_token = _extract_auth_token(authorization, x_mika_webui_token)

        # Try ticket-based auth (for SSE/WS/download channels)
        if not provided_token:
            ticket = str(request.query_params.get("ticket", "") or "").strip()
            if ticket:
                scope = str(request.query_params.get("scope", "general") or "general").strip()
                client_host = str(getattr(request.client, "host", "") or "").strip()
                if get_ticket_store().consume(ticket, scope=scope, client_host=client_host):
                    return  # ticket valid

        # Keep query-token fallback for backward compatibility, but prioritize headers.
        query_token = ""
        if not provided_token:
            query_token = str(request.query_params.get("token", "") or "").strip()
            provided_token = query_token
        if query_token:
            global _query_token_deprecation_warned
            if not _query_token_deprecation_warned:
                _query_token_deprecation_warned = True
                log.warning(
                    "webui query token 已进入兼容期，请尽快改用 Authorization "
                    "或 X-Mika-WebUI-Token 头，或使用 ticket 方案。"
                )

        if required_token:
            if not _tokens_match(required_token, provided_token):
                raise HTTPException(status_code=401, detail="invalid webui token")
            return

        client_host = str(getattr(request.client, "host", "") or "").strip()
        if not _is_loopback_client(client_host):
            raise HTTPException(
                status_code=403,
                detail="webui token is required for non-loopback access",
            )

    return _require_webui_auth


__all__ = ["create_webui_auth_dependency"]
