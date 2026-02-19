from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
testclient = pytest.importorskip("fastapi.testclient")

FastAPI = fastapi.FastAPI
TestClient = testclient.TestClient

from mika_chat_core.config import Config
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


def test_webui_auth_requires_token_when_configured():
    config = _make_config(mika_webui_token="secret-token")
    app = FastAPI()
    app.include_router(create_webui_router(settings_getter=lambda: config))
    client = TestClient(app)

    denied = client.get("/webui/api/dashboard/health")
    assert denied.status_code == 401

    allowed = client.get(
        "/webui/api/dashboard/health",
        headers={"Authorization": "Bearer secret-token"},
    )
    assert allowed.status_code == 200


def test_webui_auth_allows_loopback_without_token():
    config = _make_config(mika_webui_token="")
    app = FastAPI()
    app.include_router(create_webui_router(settings_getter=lambda: config))
    client = TestClient(app)

    response = client.get("/webui/api/dashboard/health")
    assert response.status_code == 200


def test_webui_auth_denies_non_loopback_without_token(monkeypatch):
    config = _make_config(mika_webui_token="")
    app = FastAPI()
    app.include_router(create_webui_router(settings_getter=lambda: config))
    client = TestClient(app)

    monkeypatch.setattr("mika_chat_core.webui.auth._is_loopback_client", lambda _host: False)
    response = client.get("/webui/api/dashboard/health")
    assert response.status_code == 403
