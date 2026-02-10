from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
testclient = pytest.importorskip("fastapi.testclient")

FastAPI = fastapi.FastAPI
TestClient = testclient.TestClient

from mika_chat_core.config import Config
from mika_chat_core.core_service import CoreEventRequest, create_core_service_router, process_core_event
from mika_chat_core.ports.fake_ports import FakePorts


def _make_config(**overrides: object) -> Config:
    base = {
        "gemini_master_id": 1,
        "gemini_api_key": "A" * 32,
    }
    base.update(overrides)
    return Config(**base)


def _envelope_payload(text: str = "hello") -> dict:
    return {
        "schema_version": 1,
        "session_id": "group:10001",
        "platform": "onebot_v11",
        "protocol": "onebot",
        "message_id": "msg-1",
        "timestamp": 1730000000.0,
        "author": {"id": "42", "nickname": "alice", "role": "member"},
        "content_parts": [{"kind": "text", "text": text}],
        "meta": {"intent": "private", "user_id": "42"},
    }


def test_core_service_post_event_returns_actions():
    config = _make_config()
    app = FastAPI()
    app.include_router(
        create_core_service_router(
            settings_getter=lambda: config,
            ports_getter=lambda: None,
        )
    )
    client = TestClient(app)

    response = client.post("/v1/events", json={"envelope": _envelope_payload()})
    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == 1
    assert len(body["actions"]) == 1
    assert body["actions"][0]["type"] == "send_message"


def test_core_service_requires_token_when_configured():
    config = _make_config(mika_core_service_token="secret-token")
    app = FastAPI()
    app.include_router(
        create_core_service_router(
            settings_getter=lambda: config,
            ports_getter=lambda: None,
        )
    )
    client = TestClient(app)

    denied = client.post("/v1/events", json={"envelope": _envelope_payload()})
    assert denied.status_code == 401

    allowed = client.post(
        "/v1/events",
        headers={"Authorization": "Bearer secret-token"},
        json={"envelope": _envelope_payload()},
    )
    assert allowed.status_code == 200


@pytest.mark.asyncio
async def test_process_core_event_dispatch_uses_injected_ports():
    config = _make_config()
    ports = FakePorts()
    request = CoreEventRequest(envelope=_envelope_payload("trigger"), dispatch=True)

    response = await process_core_event(request, settings=config, ports=ports)
    assert len(response.actions) == 1
    assert response.actions[0]["type"] == "send_message"
    assert len(ports.message.sent_actions) == 1
