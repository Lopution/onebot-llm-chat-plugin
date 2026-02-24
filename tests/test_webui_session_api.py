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


class _DummyContextStore:
    async def list_sessions(self, *, query: str = "", page: int = 1, page_size: int = 20):
        return {
            "items": [
                {
                    "session_key": "group:1001",
                    "updated_at": "2026-02-13 00:00:00",
                    "message_count": 12,
                    "last_message_at": 1700000000.0,
                    "is_group": True,
                }
            ],
            "total": 1,
            "page": page,
            "page_size": page_size,
            "query": query,
        }

    async def get_session_stats(self, session_key: str, *, preview_limit: int = 5):
        if session_key == "missing":
            return {"exists": False, "session_key": session_key}
        return {
            "exists": True,
            "session_key": session_key,
            "updated_at": "2026-02-13 00:00:00",
            "snapshot_message_count": 8,
            "message_count": 12,
            "user_message_count": 6,
            "assistant_message_count": 6,
            "tool_message_count": 0,
            "memory_count": 1,
            "topic_count": 2,
            "last_message_at": 1700000000.0,
            "preview": [{"role": "user", "content": "hello", "message_id": "m1", "timestamp": 1.0}],
            "preview_limit": preview_limit,
        }

    async def clear_session(
        self,
        session_key: str,
        *,
        purge_archive: bool = True,
        purge_topic_state: bool = True,
    ):
        return {
            "contexts": 1,
            "archive": 3 if purge_archive else 0,
            "summaries": 1,
            "topic_summaries": 1 if purge_topic_state else 0,
            "topic_state": 1 if purge_topic_state else 0,
            "session_key": session_key,
        }


def test_webui_session_api_endpoints(monkeypatch):
    config = _make_config()
    app = FastAPI()
    app.include_router(create_webui_router(settings_getter=lambda: config))
    client = TestClient(app)

    monkeypatch.setattr("mika_chat_core.webui.api_session.get_context_store", lambda: _DummyContextStore())

    list_resp = client.get("/webui/api/session", params={"page": 1, "page_size": 10, "query": "group:"})
    assert list_resp.status_code == 200
    assert list_resp.json()["status"] == "ok"
    assert list_resp.json()["data"]["total"] == 1

    detail_resp = client.get("/webui/api/session/group:1001", params={"preview_limit": 8})
    assert detail_resp.status_code == 200
    assert detail_resp.json()["data"]["session_key"] == "group:1001"
    assert detail_resp.json()["data"]["message_count"] == 12

    clear_resp = client.delete(
        "/webui/api/session/group:1001",
        params={"purge_archive": "true", "purge_topic_state": "false"},
    )
    assert clear_resp.status_code == 200
    assert clear_resp.json()["data"]["ok"] is True
    assert clear_resp.json()["data"]["deleted"]["archive"] == 3
    assert clear_resp.json()["data"]["deleted"]["topic_state"] == 0


def test_webui_session_detail_not_found(monkeypatch):
    config = _make_config()
    app = FastAPI()
    app.include_router(create_webui_router(settings_getter=lambda: config))
    client = TestClient(app)

    monkeypatch.setattr("mika_chat_core.webui.api_session.get_context_store", lambda: _DummyContextStore())

    response = client.get("/webui/api/session/missing")
    assert response.status_code == 404
    body = response.json()
    assert body["status"] == "error"
    assert body["message"] == "session not found"
