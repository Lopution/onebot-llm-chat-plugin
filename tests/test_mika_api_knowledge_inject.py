from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest


class _DummyKnowledgeStore:
    def __init__(self, results: list[tuple[object, float]]) -> None:
        self._results = results
        self.recalled_ids: list[int] = []
        self.search_calls = 0

    async def init_table(self) -> None:
        return None

    async def search(self, *args, **kwargs):
        self.search_calls += 1
        return list(self._results)

    async def update_recall(self, memory_id: int) -> None:
        self.recalled_ids.append(int(memory_id))


@pytest.mark.asyncio
async def test_inject_knowledge_context_disabled():
    from mika_chat_core.mika_api import MikaClient

    cfg = SimpleNamespace(
        mika_knowledge_enabled=False,
        mika_knowledge_auto_inject=False,
        mika_knowledge_default_corpus="default",
        mika_knowledge_auto_inject_top_k=3,
        mika_knowledge_min_similarity=0.5,
    )
    with patch("mika_chat_core.mika_api.HAS_SQLITE_STORE", False):
        client = MikaClient(api_key="test-key")

    with patch("mika_chat_core.mika_api.plugin_config", cfg):
        output = await client._inject_knowledge_context(
            message="测试消息",
            user_id="u1",
            group_id="g1",
            request_id="req1",
            system_injection="BASE",
        )
    assert output == "BASE"


@pytest.mark.asyncio
async def test_inject_knowledge_context_appends_retrieved_chunks():
    from mika_chat_core.mika_api import MikaClient

    entry = SimpleNamespace(
        id=12,
        content="这是一段知识库内容，用于验证自动注入是否正常工作。",
        title="设定文档",
        doc_id="doc_1",
    )
    store = _DummyKnowledgeStore([(entry, 0.93)])
    cfg = SimpleNamespace(
        mika_knowledge_enabled=True,
        mika_knowledge_auto_inject=True,
        mika_knowledge_default_corpus="persona",
        mika_knowledge_auto_inject_top_k=2,
        mika_knowledge_min_similarity=0.3,
    )

    with patch("mika_chat_core.mika_api.HAS_SQLITE_STORE", False):
        client = MikaClient(api_key="test-key")

    with patch("mika_chat_core.mika_api.plugin_config", cfg):
        with patch(
            "mika_chat_core.utils.knowledge_store.get_knowledge_store",
            return_value=store,
        ):
            with patch(
                "mika_chat_core.utils.semantic_matcher.semantic_matcher.encode",
                return_value=[0.1, 0.2, 0.3],
            ):
                output = await client._inject_knowledge_context(
                    message="Mika 的设定是什么？",
                    user_id="u1",
                    group_id="g1",
                    request_id="req2",
                    system_injection="BASE",
                )

    assert output is not None
    assert "BASE" in output
    assert "[Knowledge Context | Retrieved]" in output
    assert "[设定文档]" in output
    assert "知识库内容" in output
    assert store.search_calls == 1
    assert store.recalled_ids == [12]
