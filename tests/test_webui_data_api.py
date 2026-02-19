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
        "mika_knowledge_enabled": True,
        "mika_health_check_api_probe_enabled": False,
    }
    payload.update(overrides)
    return Config(**payload)


class _DummyKnowledgeStore:
    async def init_table(self) -> None:
        return None

    async def list_corpora(self):
        return [{"corpus_id": "default", "doc_count": 1, "chunk_count": 2}]

    async def list_documents(self, corpus_id: str):
        return [{"doc_id": "d1", "title": "t", "chunk_count": 2, "corpus_id": corpus_id}]

    async def list_chunks(self, corpus_id: str, doc_id: str):
        return [{"chunk_id": 1, "content": "hello", "recall_count": 0, "created_at": 0.0}]

    async def upsert_document(self, **kwargs):
        return 1

    async def delete_document(self, *, corpus_id: str, doc_id: str):
        return 1


class _DummyMemoryStore:
    async def init_table(self) -> None:
        return None

    async def list_sessions(self):
        return [{"session_key": "group:1", "count": 2}]

    async def list_facts(self, session_key: str):
        return [{"id": 1, "fact": "f", "session_key": session_key}]

    async def delete_memory(self, memory_id: int):
        return True

    async def delete_old_memories(self, max_age_days: int = 90):
        return 3


def test_webui_knowledge_and_memory_endpoints(monkeypatch):
    config = _make_config()
    app = FastAPI()
    app.include_router(create_webui_router(settings_getter=lambda: config))
    client = TestClient(app)

    monkeypatch.setattr("mika_chat_core.webui.api_knowledge.get_knowledge_store", lambda: _DummyKnowledgeStore())
    monkeypatch.setattr("mika_chat_core.webui.api_memory.get_memory_store", lambda: _DummyMemoryStore())
    monkeypatch.setattr("mika_chat_core.webui.api_knowledge.semantic_matcher.encode_batch", lambda _texts: [[1.0, 0.0]])

    assert client.get("/webui/api/knowledge/corpora").status_code == 200
    assert client.get("/webui/api/knowledge/documents", params={"corpus_id": "default"}).status_code == 200
    assert client.get("/webui/api/knowledge/documents/d1/chunks", params={"corpus_id": "default"}).status_code == 200

    ingest_resp = client.post(
        "/webui/api/knowledge/ingest",
        json={"corpus_id": "default", "content": "这是知识文档正文内容，长度足够。"},
    )
    assert ingest_resp.status_code == 200
    assert ingest_resp.json()["data"]["ok"] is True

    delete_resp = client.delete("/webui/api/knowledge/documents/d1", params={"corpus_id": "default"})
    assert delete_resp.status_code == 200
    assert delete_resp.json()["data"]["deleted"] == 1

    assert client.get("/webui/api/memory/sessions").status_code == 200
    assert client.get("/webui/api/memory/facts", params={"session_key": "group:1"}).status_code == 200
    assert client.delete("/webui/api/memory/1").status_code == 200
    cleanup_resp = client.post("/webui/api/memory/cleanup", json={"max_age_days": 30})
    assert cleanup_resp.status_code == 200
    assert cleanup_resp.json()["data"]["deleted"] == 3
