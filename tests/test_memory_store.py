"""memory_store 单元测试。"""

from __future__ import annotations

import pytest

from mika_chat_core.utils.memory_store import MemoryStore

np = pytest.importorskip("numpy")


@pytest.fixture
async def store(tmp_path, monkeypatch):
    db_path = tmp_path / "memory_test.db"
    monkeypatch.setenv("MIKA_CONTEXT_DB_PATH", str(db_path))

    from mika_chat_core.utils import context_db

    if context_db._db_connection is not None:
        await context_db._db_connection.close()
    context_db._db_connection = None
    context_db._db_connection_path = None

    memory_store = MemoryStore()
    await memory_store.init_table()
    yield memory_store

    if context_db._db_connection is not None:
        await context_db._db_connection.close()
    context_db._db_connection = None
    context_db._db_connection_path = None


@pytest.mark.asyncio
async def test_add_and_search(store: MemoryStore):
    emb = np.random.randn(384).astype(np.float32)
    memory_id = await store.add_memory("group:1", "u1", "用户A喜欢猫", emb)
    assert memory_id > 0

    results = await store.search(emb, top_k=5, min_similarity=0.5)
    assert len(results) >= 1
    assert results[0][0].fact == "用户A喜欢猫"
    assert results[0][1] > 0.99


@pytest.mark.asyncio
async def test_duplicate_fact_ignored(store: MemoryStore):
    emb = np.random.randn(384).astype(np.float32)
    await store.add_memory("group:1", "u1", "用户A喜欢猫", emb)
    await store.add_memory("group:1", "u1", "用户A喜欢猫", emb)
    count = await store.count("group:1")
    assert count == 1


@pytest.mark.asyncio
async def test_search_filters_by_session(store: MemoryStore):
    emb1 = np.random.randn(384).astype(np.float32)
    emb2 = np.random.randn(384).astype(np.float32)
    await store.add_memory("group:1", "u1", "事实A", emb1)
    await store.add_memory("group:2", "u2", "事实B", emb2)

    results = await store.search(emb1, session_key="group:1", min_similarity=0.0)
    facts = [item[0].fact for item in results]
    assert "事实A" in facts
    assert "事实B" not in facts


@pytest.mark.asyncio
async def test_update_recall(store: MemoryStore):
    emb = np.random.randn(384).astype(np.float32)
    memory_id = await store.add_memory("group:1", "u1", "test", emb)
    await store.update_recall(memory_id)
    results = await store.search(emb, min_similarity=0.0)
    assert results[0][0].recall_count == 1


@pytest.mark.asyncio
async def test_list_sessions_facts_and_delete(store: MemoryStore):
    emb = np.random.randn(384).astype(np.float32)
    memory_id = await store.add_memory("group:99", "u9", "用户偏好：奶茶", emb, source="extract")
    assert memory_id > 0

    sessions = await store.list_sessions()
    assert any(item["session_key"] == "group:99" for item in sessions)

    facts = await store.list_facts("group:99")
    assert len(facts) == 1
    assert facts[0]["fact"] == "用户偏好：奶茶"
    assert facts[0]["source"] == "extract"

    deleted = await store.delete_memory(memory_id)
    assert deleted is True
    facts_after = await store.list_facts("group:99")
    assert facts_after == []
