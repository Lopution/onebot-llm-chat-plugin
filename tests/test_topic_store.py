"""topic_store 单元测试。"""

from __future__ import annotations

import pytest

from mika_chat_core.memory.topic_store import TopicStore


@pytest.fixture
async def store(tmp_path, monkeypatch):
    db_path = tmp_path / "topic_store_test.db"
    monkeypatch.setenv("MIKA_CONTEXT_DB_PATH", str(db_path))

    from mika_chat_core.utils import context_db
    from mika_chat_core.memory import topic_store as topic_store_module

    if context_db._db_connection is not None:
        await context_db._db_connection.close()
    context_db._db_connection = None
    context_db._db_connection_path = None
    topic_store_module._topic_store = None

    topic_store = TopicStore()
    await topic_store.init_table()
    yield topic_store

    if context_db._db_connection is not None:
        await context_db._db_connection.close()
    context_db._db_connection = None
    context_db._db_connection_path = None
    topic_store_module._topic_store = None


@pytest.mark.asyncio
async def test_processed_message_count_roundtrip(store: TopicStore):
    key = "group:1001"
    assert await store.get_processed_message_count(key) == 0
    await store.set_processed_message_count(key, 25)
    assert await store.get_processed_message_count(key) == 25


@pytest.mark.asyncio
async def test_upsert_and_list_topics(store: TopicStore):
    session_key = "group:2002"
    topic_id = await store.upsert_topic_summary(
        session_key=session_key,
        topic="游戏讨论",
        keywords=["游戏", "联机"],
        summary="大家在讨论最近玩的联机游戏。",
        key_points=["多人联机", "周末开黑"],
        participants=["Alice(100)", "Bob(200)"],
        timestamp_start=1.0,
        timestamp_end=2.0,
        source_message_count=5,
    )
    assert topic_id > 0

    topics = await store.list_topics(session_key)
    assert len(topics) == 1
    assert topics[0].topic == "游戏讨论"
    assert "联机" in topics[0].keywords
    assert topics[0].source_message_count == 5

    topic_id_again = await store.upsert_topic_summary(
        session_key=session_key,
        topic="游戏讨论",
        keywords=["游戏"],
        summary="话题继续：今晚约时间。",
        key_points=["约定时间"],
        participants=["Alice(100)"],
        timestamp_start=2.0,
        timestamp_end=3.0,
        source_message_count=3,
    )
    assert topic_id_again == topic_id

    topics_after = await store.list_topics(session_key)
    assert len(topics_after) == 1
    assert topics_after[0].source_message_count == 8
    assert topics_after[0].summary == "话题继续：今晚约时间。"


@pytest.mark.asyncio
async def test_list_sessions_and_clear(store: TopicStore):
    await store.upsert_topic_summary(
        session_key="group:3003",
        topic="学习",
        keywords=["考试"],
        summary="讨论考试安排",
        key_points=["周三考试"],
        participants=["Sensei"],
        timestamp_start=1.0,
        timestamp_end=1.5,
        source_message_count=2,
    )
    sessions = await store.list_sessions()
    assert any(item["session_key"] == "group:3003" for item in sessions)

    await store.clear_session("group:3003")
    topics = await store.list_topics("group:3003")
    assert topics == []
    assert await store.get_processed_message_count("group:3003") == 0

