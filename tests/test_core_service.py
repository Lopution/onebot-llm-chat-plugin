from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
testclient = pytest.importorskip("fastapi.testclient")

FastAPI = fastapi.FastAPI
TestClient = testclient.TestClient

from mika_chat_core.config import Config
from mika_chat_core.core_service import (
    CoreEventRequest,
    _is_loopback_client,
    create_core_service_router,
    process_core_event,
)
from mika_chat_core.ports.fake_ports import FakePorts


def _make_config(**overrides: object) -> Config:
    base = {
        "mika_master_id": 1,
        "llm_api_key": "A" * 32,
    }
    base.update(overrides)
    return Config(**base)


def _envelope_payload(text: str = "hello", *, include_intent: bool = True) -> dict:
    meta = {"user_id": "42"}
    if include_intent:
        meta["intent"] = "private"
    return {
        "schema_version": 1,
        "session_id": "group:10001",
        "platform": "onebot_v11",
        "protocol": "onebot",
        "message_id": "msg-1",
        "timestamp": 1730000000.0,
        "author": {"id": "42", "nickname": "alice", "role": "member"},
        "content_parts": [{"kind": "text", "text": text}],
        "meta": meta,
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
    assert "上下文不可用" in body["actions"][0]["parts"][0]["text"]


def test_core_service_health_endpoint_available():
    config = _make_config(mika_health_check_api_probe_enabled=False)
    app = FastAPI()
    app.include_router(
        create_core_service_router(
            settings_getter=lambda: config,
            ports_getter=lambda: None,
        )
    )
    client = TestClient(app)

    response = client.get("/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert "status" in body
    assert "api_probe" in body
    assert "runtime" in body


def test_core_service_proactive_evaluate_endpoint_removed():
    config = _make_config()
    app = FastAPI()
    app.include_router(
        create_core_service_router(
            settings_getter=lambda: config,
            ports_getter=lambda: None,
        )
    )
    client = TestClient(app)

    response = client.post(
        "/v1/proactive/evaluate",
        json={"envelope": _envelope_payload()},
    )
    assert response.status_code == 404


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

    denied_health = client.get("/v1/health")
    assert denied_health.status_code == 401

    allowed_health = client.get("/v1/health", headers={"Authorization": "Bearer secret-token"})
    assert allowed_health.status_code == 200


def test_core_service_loopback_guard_helper():
    assert _is_loopback_client("127.0.0.1") is True
    assert _is_loopback_client("::1") is True
    assert _is_loopback_client("localhost") is True
    assert _is_loopback_client("testclient") is True
    assert _is_loopback_client("10.0.0.2") is False


def test_core_service_denies_non_loopback_when_token_not_set(monkeypatch):
    config = _make_config(mika_core_service_token="")
    app = FastAPI()
    app.include_router(
        create_core_service_router(
            settings_getter=lambda: config,
            ports_getter=lambda: None,
        )
    )
    client = TestClient(app)
    monkeypatch.setattr("mika_chat_core.core_service._is_loopback_client", lambda _host: False)
    response = client.post("/v1/events", json={"envelope": _envelope_payload()})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_process_core_event_dispatch_uses_injected_ports():
    config = _make_config()
    ports = FakePorts()
    request = CoreEventRequest(envelope=_envelope_payload("trigger", include_intent=False), dispatch=True)

    response = await process_core_event(request, settings=config, ports=ports)
    assert len(response.actions) == 1
    assert response.actions[0]["type"] == "send_message"
    assert len(ports.message.sent_actions) == 1
