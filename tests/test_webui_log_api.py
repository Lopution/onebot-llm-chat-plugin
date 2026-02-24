from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
httpx = pytest.importorskip("httpx")

FastAPI = fastapi.FastAPI

from mika_chat_core.config import Config
from mika_chat_core.infra.log_broker import LogBroker
from mika_chat_core.webui import create_webui_router


def _make_config(**overrides: object) -> Config:
    payload: dict[str, object] = {
        "mika_master_id": "1",
        "llm_api_key": "A" * 32,
        "mika_webui_enabled": True,
        "mika_webui_base_path": "/webui",
        "mika_webui_token": "",
        "mika_health_check_api_probe_enabled": False,
    }
    payload.update(overrides)
    return Config(**payload)


@pytest.mark.asyncio
async def test_webui_log_history_returns_envelope(monkeypatch):
    broker = LogBroker(max_events=20)
    broker.publish("info", "boot")
    broker.publish("warning", "warn")
    monkeypatch.setattr("mika_chat_core.webui.api_log.get_log_broker", lambda: broker)

    config = _make_config()
    app = FastAPI()
    app.include_router(create_webui_router(settings_getter=lambda: config))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/webui/api/log/history", params={"limit": 10})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["data"]["next_id"] == 2
    assert [item["message"] for item in body["data"]["events"]] == ["boot", "warn"]


@pytest.mark.asyncio
async def test_webui_log_history_supports_min_level(monkeypatch):
    broker = LogBroker(max_events=20)
    broker.publish("debug", "debug-msg")
    broker.publish("info", "info-msg")
    broker.publish("warning", "warn-msg")
    monkeypatch.setattr("mika_chat_core.webui.api_log.get_log_broker", lambda: broker)

    config = _make_config()
    app = FastAPI()
    app.include_router(create_webui_router(settings_getter=lambda: config))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/webui/api/log/history", params={"limit": 10, "min_level": "WARNING"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert [item["message"] for item in body["data"]["events"]] == ["warn-msg"]
