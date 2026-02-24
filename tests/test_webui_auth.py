from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
httpx = pytest.importorskip("httpx")

FastAPI = fastapi.FastAPI

from mika_chat_core.config import Config
from mika_chat_core.webui import create_webui_router
from mika_chat_core.webui.auth_ticket import configure_ticket_store, get_ticket_store


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
async def test_webui_auth_requires_token_when_configured():
    config = _make_config(mika_webui_token="secret-token")
    app = FastAPI()
    app.include_router(create_webui_router(settings_getter=lambda: config))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        denied = await client.get("/webui/api/dashboard/health")
    assert denied.status_code == 401

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        allowed = await client.get(
            "/webui/api/dashboard/health",
            headers={"Authorization": "Bearer secret-token"},
        )
    assert allowed.status_code == 200


@pytest.mark.asyncio
async def test_webui_auth_allows_loopback_without_token():
    config = _make_config(mika_webui_token="")
    app = FastAPI()
    app.include_router(create_webui_router(settings_getter=lambda: config))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/webui/api/dashboard/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_webui_auth_denies_non_loopback_without_token(monkeypatch):
    config = _make_config(mika_webui_token="")
    app = FastAPI()
    app.include_router(create_webui_router(settings_getter=lambda: config))
    transport = httpx.ASGITransport(app=app)

    monkeypatch.setattr("mika_chat_core.webui.auth._is_loopback_client", lambda _host: False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/webui/api/dashboard/health")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_webui_auth_ticket_can_authenticate_follow_up_request():
    configure_ticket_store(ttl_seconds=60, single_use=True, max_active=50)
    config = _make_config(mika_webui_token="secret-token")
    app = FastAPI()
    app.include_router(create_webui_router(settings_getter=lambda: config))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        issue = await client.post(
            "/webui/api/auth/ticket",
            json={"scope": "general"},
            headers={"Authorization": "Bearer secret-token"},
        )
    assert issue.status_code == 200
    ticket = issue.json()["data"]["ticket"]

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        allowed = await client.get(f"/webui/api/dashboard/health?ticket={ticket}&scope=general")
    assert allowed.status_code == 200

    # ticket 默认单次可用，重复使用应失败
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        denied = await client.get(f"/webui/api/dashboard/health?ticket={ticket}&scope=general")
    assert denied.status_code == 401


@pytest.mark.asyncio
async def test_webui_auth_ticket_binds_client_host():
    configure_ticket_store(ttl_seconds=60, single_use=True, max_active=50)
    config = _make_config(mika_webui_token="secret-token")
    app = FastAPI()
    app.include_router(create_webui_router(settings_getter=lambda: config))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        issue = await client.post(
            "/webui/api/auth/ticket",
            json={"scope": "general"},
            headers={"Authorization": "Bearer secret-token"},
        )
    assert issue.status_code == 200
    ticket = issue.json()["data"]["ticket"]

    store = get_ticket_store()
    assert store.consume(ticket, scope="general", client_host="other-host") is False
    stored_host = ""
    try:
        entry = getattr(store, "_tickets", {}).get(ticket)  # type: ignore[attr-defined]
        stored_host = str(getattr(entry, "client_host", "") or "").strip()
    except Exception:
        stored_host = ""
    assert store.consume(ticket, scope="general", client_host=stored_host or "127.0.0.1") is True
