"""HTTP core service for host-agnostic event processing."""

from __future__ import annotations

import hmac
import ipaddress
from types import SimpleNamespace
from typing import Any, Callable, Optional

from fastapi import APIRouter, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from .config import Config
from .contracts import ContentPart, EventEnvelope, NoopAction, SendMessageAction
from .engine import ChatEngine
from .health_probe import get_cached_api_probe
from .runtime import (
    get_config as get_runtime_config,
    get_host_event_port as get_runtime_host_event_port,
    get_message_port as get_runtime_message_port,
)

CoreAction = SendMessageAction | NoopAction
HOST_RUNTIME_UNAVAILABLE_REPLY_TEXT = "当前运行节点上下文不可用，请稍后再试。"


class CoreEventRequest(BaseModel):
    envelope: dict[str, Any]
    dispatch: bool = False


class CoreEventResponse(BaseModel):
    schema_version: int = 1
    actions: list[dict[str, Any]] = Field(default_factory=list)


class CoreHealthResponse(BaseModel):
    status: str = "unknown"
    api_probe: dict[str, Any] = Field(default_factory=dict)
    runtime: dict[str, bool] = Field(default_factory=dict)
    version: str = "1"

def _build_runtime_ports_bundle() -> Any:
    message_port = get_runtime_message_port()
    host_event_port = get_runtime_host_event_port()
    if message_port is None and host_event_port is None:
        return None

    bundle = SimpleNamespace()
    if message_port is not None:
        bundle.message = message_port
    if host_event_port is not None:
        bundle.host_events = host_event_port
    return bundle


def _extract_auth_token(authorization: str | None, x_mika_core_token: str | None) -> str:
    bearer = (authorization or "").strip()
    if bearer.lower().startswith("bearer "):
        return bearer[7:].strip()
    header_token = (x_mika_core_token or "").strip()
    if header_token:
        return header_token
    return bearer


def _is_loopback_client(host: str) -> bool:
    value = str(host or "").strip().lower()
    if not value:
        return False
    if value in {"localhost", "testclient"}:
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def _tokens_match(required_token: str, provided_token: str) -> bool:
    required = str(required_token or "").strip()
    provided = str(provided_token or "").strip()
    if not required or not provided:
        return False
    return hmac.compare_digest(provided.encode("utf-8"), required.encode("utf-8"))


def _ensure_core_service_auth(
    *,
    request: Request,
    config: Config,
    authorization: str | None,
    x_mika_core_token: str | None,
) -> None:
    required_token = str(getattr(config, "mika_core_service_token", "") or "").strip()
    provided_token = _extract_auth_token(authorization, x_mika_core_token)

    if required_token:
        if not _tokens_match(required_token, provided_token):
            raise HTTPException(status_code=401, detail="invalid core service token")
        return

    client_host = str(getattr(request.client, "host", "") or "").strip()
    if not _is_loopback_client(client_host):
        raise HTTPException(
            status_code=403,
            detail="core service token is required for non-loopback access",
        )


def _serialize_actions(actions: list[CoreAction]) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for action in actions:
        if isinstance(action, SendMessageAction):
            serialized.append(action.to_dict())
            continue
        if isinstance(action, NoopAction):
            serialized.append(action.to_dict())
            continue
        if hasattr(action, "to_dict"):
            payload = action.to_dict()  # type: ignore[assignment]
            if isinstance(payload, dict):
                serialized.append(payload)
                continue
        raise TypeError(f"unsupported action type: {type(action).__name__}")
    return serialized


def _degrade_actions_for_missing_host_runtime(
    *,
    envelope: EventEnvelope,
    actions: list[CoreAction],
) -> list[CoreAction]:
    if len(actions) != 1:
        return actions

    action = actions[0]
    if not isinstance(action, NoopAction):
        return actions
    if str(action.reason or "") != "host_runtime_unavailable":
        return actions

    return [
        SendMessageAction(
            type="send_message",
            session_id=envelope.session_id,
            reply_to=envelope.message_id or "",
            parts=[ContentPart(kind="text", text=HOST_RUNTIME_UNAVAILABLE_REPLY_TEXT)],
            meta={
                "degraded_from": "host_runtime_unavailable",
                "intent": str(envelope.meta.get("intent") or ""),
            },
        )
    ]


async def process_core_event(
    request: CoreEventRequest,
    *,
    settings: Optional[Config] = None,
    ports: Any = None,
) -> CoreEventResponse:
    envelope = EventEnvelope.from_dict(request.envelope)
    effective_settings = settings or get_runtime_config()
    effective_ports = ports if ports is not None else _build_runtime_ports_bundle()

    actions = await ChatEngine.handle_event(
        envelope,
        effective_ports,
        effective_settings,
        dispatch=bool(request.dispatch),
    )
    actions = _degrade_actions_for_missing_host_runtime(envelope=envelope, actions=actions)
    return CoreEventResponse(actions=_serialize_actions(actions))


def create_core_service_router(
    *,
    settings_getter: Callable[[], Config] = get_runtime_config,
    ports_getter: Callable[[], Any] = _build_runtime_ports_bundle,
) -> APIRouter:
    router = APIRouter(tags=["mika-core"])

    @router.post("/v1/events", response_model=CoreEventResponse)
    async def post_event(
        request: Request,
        payload: CoreEventRequest,
        authorization: str | None = Header(default=None),
        x_mika_core_token: str | None = Header(default=None),
    ) -> CoreEventResponse:
        config = settings_getter()
        _ensure_core_service_auth(
            request=request,
            config=config,
            authorization=authorization,
            x_mika_core_token=x_mika_core_token,
        )

        try:
            return await process_core_event(
                payload,
                settings=config,
                ports=ports_getter(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/v1/health", response_model=CoreHealthResponse)
    async def get_health(
        request: Request,
        authorization: str | None = Header(default=None),
        x_mika_core_token: str | None = Header(default=None),
    ) -> CoreHealthResponse:
        config = settings_getter()
        _ensure_core_service_auth(
            request=request,
            config=config,
            authorization=authorization,
            x_mika_core_token=x_mika_core_token,
        )

        probe_result = await get_cached_api_probe(config)
        observability = config.get_observability_config()
        overall_status = "healthy"
        if bool(observability["health_api_probe_enabled"]) and probe_result.get("status") != "healthy":
            overall_status = "degraded"

        runtime_state = {
            "message_port_ready": get_runtime_message_port() is not None,
            "host_event_port_ready": get_runtime_host_event_port() is not None,
        }
        if not runtime_state["message_port_ready"] and not runtime_state["host_event_port_ready"]:
            overall_status = "degraded"

        return CoreHealthResponse(
            status=overall_status,
            api_probe=probe_result,
            runtime=runtime_state,
            version="1",
        )

    return router


def create_core_service_app() -> FastAPI:
    app = FastAPI(title="mika-chat-core-service", version="1")
    app.include_router(create_core_service_router())
    return app


app = create_core_service_app()
