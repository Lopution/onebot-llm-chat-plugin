from __future__ import annotations

import pytest

from mika_chat_core.utils.knowledge_store import KnowledgeStore

np = pytest.importorskip("numpy")


@pytest.fixture
async def store(tmp_path, monkeypatch):
    db_path = tmp_path / "knowledge_test.db"
    monkeypatch.setenv("MIKA_CONTEXT_DB_PATH", str(db_path))

    from mika_chat_core.utils import context_db

    if context_db._db_connection is not None:
        await context_db._db_connection.close()
    context_db._db_connection = None
    context_db._db_connection_path = None

    knowledge_store = KnowledgeStore()
    await knowledge_store.init_table()
    yield knowledge_store

    if context_db._db_connection is not None:
        await context_db._db_connection.close()
    context_db._db_connection = None
    context_db._db_connection_path = None


@pytest.mark.asyncio
async def test_upsert_and_search(store: KnowledgeStore):
    emb_good = np.ones(8, dtype=np.float32)
    emb_bad = -np.ones(8, dtype=np.float32)
    inserted = await store.upsert_document(
        corpus_id="default",
        doc_id="doc-1",
        chunks=["喜欢猫", "喜欢狗"],
        embeddings=[emb_good, emb_bad],
        title="偏好文档",
        session_key="group:1",
    )
    assert inserted == 2

    results = await store.search(
        emb_good,
        corpus_id="default",
        session_key="group:1",
        top_k=2,
        min_similarity=0.1,
    )
    assert results
    assert results[0][0].doc_id == "doc-1"
    assert results[0][0].title == "偏好文档"


@pytest.mark.asyncio
async def test_session_filter_includes_global_chunks(store: KnowledgeStore):
    emb = np.arange(8, dtype=np.float32)
    await store.upsert_document(
        corpus_id="default",
        doc_id="doc-global",
        chunks=["全局知识"],
        embeddings=[emb],
        session_key="",
    )
    await store.upsert_document(
        corpus_id="default",
        doc_id="doc-group",
        chunks=["群知识"],
        embeddings=[emb],
        session_key="group:1",
    )

    results = await store.search(
        emb,
        corpus_id="default",
        session_key="group:1",
        top_k=5,
        min_similarity=-1.0,
    )
    docs = {item[0].doc_id for item in results}
    assert "doc-global" in docs
    assert "doc-group" in docs


@pytest.mark.asyncio
async def test_delete_document(store: KnowledgeStore):
    emb = np.ones(8, dtype=np.float32)
    await store.upsert_document(
        corpus_id="default",
        doc_id="doc-del",
        chunks=["需要删除"],
        embeddings=[emb],
    )
    deleted = await store.delete_document(corpus_id="default", doc_id="doc-del")
    assert deleted >= 1


@pytest.mark.asyncio
async def test_list_corpora_documents_chunks(store: KnowledgeStore):
    emb = np.ones(8, dtype=np.float32)
    await store.upsert_document(
        corpus_id="persona",
        doc_id="doc-001",
        chunks=["第一段", "第二段"],
        embeddings=[emb, emb],
        title="人设",
        source="manual",
        tags=["a", "b"],
    )

    corpora = await store.list_corpora()
    assert any(item["corpus_id"] == "persona" for item in corpora)

    docs = await store.list_documents("persona")
    assert len(docs) == 1
    assert docs[0]["doc_id"] == "doc-001"
    assert docs[0]["chunk_count"] == 2
    assert docs[0]["title"] == "人设"

    chunks = await store.list_chunks("persona", "doc-001")
    assert len(chunks) == 2
    assert chunks[0]["chunk_id"] == 1
    assert chunks[1]["chunk_id"] == 2
