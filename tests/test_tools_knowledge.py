from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

np = pytest.importorskip("numpy")


@pytest.mark.asyncio
async def test_ingest_and_search_knowledge_tools(monkeypatch, tmp_path):
    db_path = tmp_path / "tools_knowledge.db"
    monkeypatch.setenv("MIKA_CONTEXT_DB_PATH", str(db_path))

    from mika_chat_core.utils import context_db

    if context_db._db_connection is not None:
        await context_db._db_connection.close()
    context_db._db_connection = None
    context_db._db_connection_path = None

    cfg = SimpleNamespace(
        mika_knowledge_enabled=True,
        mika_knowledge_default_corpus="default",
        mika_knowledge_search_top_k=5,
        mika_knowledge_min_similarity=0.2,
        mika_knowledge_chunk_max_chars=80,
        mika_knowledge_chunk_overlap_chars=8,
    )
    monkeypatch.setattr("mika_chat_core.tools_builtin._knowledge.get_runtime_config", lambda: cfg)

    class _FakeSemantic:
        def encode(self, text: str):
            del text
            return np.ones(8, dtype=np.float32)

        def encode_batch(self, texts: list[str]):
            return [np.ones(8, dtype=np.float32) for _ in texts]

    monkeypatch.setattr("mika_chat_core.utils.semantic_matcher.semantic_matcher", _FakeSemantic())

    from mika_chat_core.tools import handle_ingest_knowledge, handle_search_knowledge

    ingest_resp = await handle_ingest_knowledge(
        {
            "doc_id": "doc-1",
            "title": "测试文档",
            "content": "Mika 喜欢粉色。Mika 也喜欢甜点。Mika 经常在茶会活动。",
        },
        group_id="10001",
    )
    ingest_payload = json.loads(ingest_resp)
    assert ingest_payload["ok"] is True
    assert ingest_payload["chunks"] >= 1

    search_resp = await handle_search_knowledge({"query": "Mika 喜欢什么？"}, group_id="10001")
    assert "[Knowledge Search Results]" in search_resp
    assert "测试文档" in search_resp

    if context_db._db_connection is not None:
        await context_db._db_connection.close()
    context_db._db_connection = None
    context_db._db_connection_path = None


@pytest.mark.asyncio
async def test_search_knowledge_disabled(monkeypatch):
    cfg = SimpleNamespace(
        mika_knowledge_enabled=False,
        mika_knowledge_default_corpus="default",
        mika_knowledge_search_top_k=5,
        mika_knowledge_min_similarity=0.5,
    )
    monkeypatch.setattr("mika_chat_core.tools_builtin._knowledge.get_runtime_config", lambda: cfg)
    from mika_chat_core.tools import handle_search_knowledge

    resp = await handle_search_knowledge({"query": "测试"})
    assert "未开启" in resp
