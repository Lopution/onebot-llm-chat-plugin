"""chat_history_summarizer 单元测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from mika_chat_core.memory.chat_history_summarizer import ChatHistorySummarizer
from mika_chat_core.memory.topic_store import get_topic_store


@pytest.fixture
async def prepared_env(tmp_path, monkeypatch):
    db_path = tmp_path / "chat_history_summarizer_test.db"
    monkeypatch.setenv("MIKA_CONTEXT_DB_PATH", str(db_path))

    from mika_chat_core.utils import context_db
    from mika_chat_core.memory import topic_store as topic_store_module

    if context_db._db_connection is not None:
        await context_db._db_connection.close()
    context_db._db_connection = None
    context_db._db_connection_path = None
    topic_store_module._topic_store = None

    store = get_topic_store()
    await store.init_table()
    yield store

    if context_db._db_connection is not None:
        await context_db._db_connection.close()
    context_db._db_connection = None
    context_db._db_connection_path = None
    topic_store_module._topic_store = None


def _build_messages(total: int) -> list[dict]:
    messages: list[dict] = []
    for index in range(1, total + 1):
        messages.append(
            {
                "role": "user" if index % 2 else "assistant",
                "content": f"[用户{index}(10{index})]: 消息内容 {index}",
                "timestamp": float(index),
            }
        )
    return messages


@pytest.mark.asyncio
async def test_maybe_summarize_stores_topic(prepared_env):
    summarizer = ChatHistorySummarizer()
    summarizer._call_llm = AsyncMock(
        side_effect=[
            '{"topics":[{"topic":"游戏讨论","keywords":["游戏","联机"],"message_indices":[1,2,3,4,5]}]}',
            '{"summary":"大家讨论今晚开黑安排。","key_points":["确定时间","选择游戏"],"keywords":["开黑"]}',
        ]
    )

    llm_cfg = {
        "provider": "openai_compat",
        "base_url": "https://api.example.com/v1",
        "api_keys": ["test-key"],
        "extra_headers": {},
    }
    stored = await summarizer.maybe_summarize(
        session_key="group:1001",
        messages=_build_messages(5),
        llm_cfg=llm_cfg,
        model="fast-model",
        batch_size=5,
        request_id="r1",
    )
    assert stored == 1

    store = get_topic_store()
    topics = await store.list_topics("group:1001")
    assert len(topics) == 1
    assert topics[0].topic == "游戏讨论"
    assert topics[0].summary == "大家讨论今晚开黑安排。"
    assert await store.get_processed_message_count("group:1001") == 5


@pytest.mark.asyncio
async def test_maybe_summarize_skips_when_pending_not_enough(prepared_env):
    summarizer = ChatHistorySummarizer()
    summarizer._call_llm = AsyncMock(return_value="")

    llm_cfg = {
        "provider": "openai_compat",
        "base_url": "https://api.example.com/v1",
        "api_keys": ["test-key"],
        "extra_headers": {},
    }
    stored = await summarizer.maybe_summarize(
        session_key="group:1002",
        messages=_build_messages(4),
        llm_cfg=llm_cfg,
        model="fast-model",
        batch_size=5,
        request_id="r2",
    )
    assert stored == 0
    assert summarizer._call_llm.await_count == 0


@pytest.mark.asyncio
async def test_maybe_summarize_fallback_when_analysis_invalid(prepared_env):
    summarizer = ChatHistorySummarizer()
    summarizer._call_llm = AsyncMock(
        side_effect=[
            "not-json",
            '{"summary":"讨论了作业进度。","key_points":["明确截止时间"]}',
        ]
    )

    llm_cfg = {
        "provider": "openai_compat",
        "base_url": "https://api.example.com/v1",
        "api_keys": ["test-key"],
        "extra_headers": {},
    }
    stored = await summarizer.maybe_summarize(
        session_key="group:1003",
        messages=_build_messages(5),
        llm_cfg=llm_cfg,
        model="fast-model",
        batch_size=5,
        request_id="r3",
    )
    assert stored == 1

    store = get_topic_store()
    topics = await store.list_topics("group:1003")
    assert len(topics) == 1
    assert topics[0].topic == "对话片段"
    assert "作业进度" in topics[0].summary

