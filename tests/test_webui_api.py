from __future__ import annotations

from unittest.mock import patch

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
        "mika_semantic_model": "BAAI/bge-small-zh-v1.5",
    }
    payload.update(overrides)
    return Config(**payload)


class _DummyContextStore:
    async def get_stats(self):
        return {"total_contexts": 11, "cached_contexts": 3}


class _DummyMemoryStore:
    async def init_table(self) -> None:
        return None

    async def count(self) -> int:
        return 5


class _DummyKnowledgeStore:
    async def init_table(self) -> None:
        return None

    async def count(self) -> int:
        return 8


def test_webui_router_respects_base_path():
    config = _make_config(mika_webui_base_path="panel")
    app = FastAPI()
    app.include_router(create_webui_router(settings_getter=lambda: config))
    client = TestClient(app)

    response = client.get("/panel/api/dashboard/metrics")
    assert response.status_code == 200


def test_dashboard_metrics_returns_snapshot():
    config = _make_config()
    app = FastAPI()
    app.include_router(create_webui_router(settings_getter=lambda: config))
    client = TestClient(app)

    with patch(
        "mika_chat_core.webui.api_dashboard.metrics.snapshot",
        return_value={"requests_total": 123, "tool_calls_total": 9},
    ):
        response = client.get("/webui/api/dashboard/metrics")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["data"]["requests_total"] == 123


def test_dashboard_stats_aggregates_store_data(monkeypatch):
    config = _make_config()
    app = FastAPI()
    app.include_router(create_webui_router(settings_getter=lambda: config))
    client = TestClient(app)

    monkeypatch.setattr("mika_chat_core.webui.api_dashboard.get_context_store", lambda: _DummyContextStore())
    monkeypatch.setattr(
        "mika_chat_core.utils.memory_store.get_memory_store",
        lambda: _DummyMemoryStore(),
    )
    monkeypatch.setattr(
        "mika_chat_core.utils.knowledge_store.get_knowledge_store",
        lambda: _DummyKnowledgeStore(),
    )
    monkeypatch.setattr("mika_chat_core.webui.api_dashboard.semantic_matcher._model", object())
    monkeypatch.setattr("mika_chat_core.webui.api_dashboard.semantic_matcher._backend", "fastembed")

    response = client.get("/webui/api/dashboard/stats")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    data = body["data"]
    assert data["memory_count"] == 5
    assert data["knowledge_count"] == 8
    assert data["context_stats"]["total_contexts"] == 11
    assert data["semantic_model_status"]["loaded"] is True
    assert data["semantic_model_status"]["backend"] == "fastembed"
