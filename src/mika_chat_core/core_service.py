"""HTTP core service for host-agnostic event processing."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable, Optional

from fastapi import APIRouter, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .config import Config
from .contracts import EventEnvelope, NoopAction, SendMessageAction
from .engine import ChatEngine
from .runtime import (
    get_config as get_runtime_config,
    get_host_event_port as get_runtime_host_event_port,
    get_message_port as get_runtime_message_port,
)

CoreAction = SendMessageAction | NoopAction


class CoreEventRequest(BaseModel):
    envelope: dict[str, Any]
    dispatch: bool = False


class CoreEventResponse(BaseModel):
    schema_version: int = 1
    actions: list[dict[str, Any]] = Field(default_factory=list)


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
    return CoreEventResponse(actions=_serialize_actions(actions))


def create_core_service_router(
    *,
    settings_getter: Callable[[], Config] = get_runtime_config,
    ports_getter: Callable[[], Any] = _build_runtime_ports_bundle,
) -> APIRouter:
    router = APIRouter(tags=["mika-core"])

    @router.post("/v1/events", response_model=CoreEventResponse)
    async def post_event(
        payload: CoreEventRequest,
        authorization: str | None = Header(default=None),
        x_mika_core_token: str | None = Header(default=None),
    ) -> CoreEventResponse:
        config = settings_getter()
        required_token = str(getattr(config, "mika_core_service_token", "") or "").strip()
        provided_token = _extract_auth_token(authorization, x_mika_core_token)

        if required_token and provided_token != required_token:
            raise HTTPException(status_code=401, detail="invalid core service token")

        try:
            return await process_core_event(
                payload,
                settings=config,
                ports=ports_getter(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router


def create_core_service_app() -> FastAPI:
    app = FastAPI(title="mika-chat-core-service", version="1")
    app.include_router(create_core_service_router())
    return app


app = create_core_service_app()

