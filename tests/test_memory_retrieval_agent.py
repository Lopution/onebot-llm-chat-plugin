"""memory retrieval agent 单元测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mika_chat_core.memory.retrieval_agent import MemoryRetrievalAgent, RetrievalDecision
from mika_chat_core.memory.topic_store import get_topic_store
from mika_chat_core.utils.knowledge_store import get_knowledge_store
from mika_chat_core.utils.memory_store import get_memory_store

np = pytest.importorskip("numpy")


@pytest.fixture
async def prepared_db(tmp_path, monkeypatch):
    db_path = tmp_path / "memory_retrieval_agent_test.db"
    monkeypatch.setenv("MIKA_CONTEXT_DB_PATH", str(db_path))

    from mika_chat_core.memory import topic_store as topic_store_module
    from mika_chat_core.utils import context_db
    from mika_chat_core.utils import knowledge_store as knowledge_store_module
    from mika_chat_core.utils import memory_store as memory_store_module

    if context_db._db_connection is not None:
        await context_db._db_connection.close()
    context_db._db_connection = None
    context_db._db_connection_path = None
    topic_store_module._topic_store = None
    memory_store_module._memory_store = None
    knowledge_store_module._knowledge_store = None

    yield

    if context_db._db_connection is not None:
        await context_db._db_connection.close()
    context_db._db_connection = None
    context_db._db_connection_path = None
    topic_store_module._topic_store = None
    memory_store_module._memory_store = None
    knowledge_store_module._knowledge_store = None


@pytest.mark.asyncio
async def test_retrieve_returns_found_answer_directly():
    agent = MemoryRetrievalAgent()
    agent._decide_next_action = AsyncMock(
        return_value=RetrievalDecision(
            action="found_answer",
            args={"answer": "检索完成：用户偏好甜食"},
            reason="",
        )
    )

    output = await agent.retrieve(
        question="Mika 喜欢什么？",
        session_key="group:1",
        user_id="u1",
        group_id="g1",
        llm_cfg={"provider": "openai_compat", "api_keys": ["k"], "base_url": "", "extra_headers": {}},
        model="fast-model",
    )

    assert "检索完成" in output


@pytest.mark.asyncio
async def test_retrieve_runs_multi_source_actions(prepared_db):
    topic_store = get_topic_store()
    await topic_store.init_table()
    await topic_store.upsert_topic_summary(
        session_key="group:9",
        topic="游戏讨论",
        keywords=["游戏", "联机"],
        summary="大家在讨论周末开黑安排。",
        key_points=["周末", "联机"],
        participants=["Alice(101)", "Bob(102)"],
        timestamp_start=1.0,
        timestamp_end=2.0,
        source_message_count=4,
    )

    vector = np.random.randn(384).astype(np.float32)
    memory_store = get_memory_store()
    await memory_store.init_table()
    await memory_store.add_memory("group:9", "u9", "用户A喜欢策略游戏", vector)

    knowledge_store = get_knowledge_store()
    await knowledge_store.init_table()
    await knowledge_store.upsert_document(
        corpus_id="default",
        doc_id="doc_9",
        chunks=["项目文档提到周末需要复盘。"],
        embeddings=[vector],
        title="项目文档",
        source="manual",
        tags=["项目"],
        session_key="group:9",
    )

    agent = MemoryRetrievalAgent()
    agent._decide_next_action = AsyncMock(
        side_effect=[
            RetrievalDecision(action="query_chat_history", args={"top_k": 2}, reason="先看近期话题"),
            RetrievalDecision(action="query_memory", args={"query": "喜欢什么", "top_k": 2}, reason="查长期记忆"),
            RetrievalDecision(action="query_knowledge", args={"query": "复盘", "top_k": 2}, reason="查知识库"),
            RetrievalDecision(
                action="found_answer",
                args={"answer": "检索结论：群内近期围绕开黑与复盘展开。"},
                reason="信息足够",
            ),
        ]
    )

    with patch(
        "mika_chat_core.memory.retrieval_agent.semantic_matcher.encode",
        return_value=vector,
    ):
        output = await agent.retrieve(
            question="最近讨论了什么？",
            session_key="group:9",
            user_id="u9",
            group_id="g9",
            llm_cfg={
                "provider": "openai_compat",
                "api_keys": ["k"],
                "base_url": "https://api.example.com/v1",
                "extra_headers": {},
            },
            model="fast-model",
            max_iterations=4,
        )

    assert "检索结论" in output

    facts = await memory_store.list_facts("group:9")
    assert facts and facts[0]["recall_count"] == 1

    chunks = await knowledge_store.list_chunks("default", "doc_9")
    assert chunks and chunks[0]["recall_count"] == 1


@pytest.mark.asyncio
async def test_call_llm_reuses_http_client():
    agent = MemoryRetrievalAgent()
    mock_response = MagicMock()
    mock_response.raise_for_status = lambda: None
    mock_response.json.return_value = {
        "choices": [{"message": {"role": "assistant", "content": "ok"}}]
    }
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.is_closed = False

    llm_cfg = {
        "provider": "openai_compat",
        "base_url": "https://api.example.com/v1",
        "api_keys": ["test-key"],
        "extra_headers": {},
    }

    with patch(
        "mika_chat_core.memory.retrieval_agent.httpx.AsyncClient",
        return_value=mock_client,
    ) as client_factory:
        first = await agent._call_llm(
            system_prompt="sys",
            user_prompt="user",
            llm_cfg=llm_cfg,
            model="mika-test",
        )
        second = await agent._call_llm(
            system_prompt="sys2",
            user_prompt="user2",
            llm_cfg=llm_cfg,
            model="mika-test",
        )

    assert first == "ok"
    assert second == "ok"
    assert client_factory.call_count == 1
    await agent.close()
