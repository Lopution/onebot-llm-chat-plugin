"""知识库存储（SQLite + 向量检索）。"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from ..infra.logging import logger as log


@dataclass
class KnowledgeChunkEntry:
    id: int
    corpus_id: str
    doc_id: str
    chunk_id: int
    content: str
    embedding: bytes
    title: str
    source: str
    tags: list[str]
    session_key: str
    created_at: float
    updated_at: float
    last_recalled_at: float
    recall_count: int


class KnowledgeStore:
    """知识库文档块存储。"""

    def __init__(self) -> None:
        self._init_lock = asyncio.Lock()
        self._initialized = False

    async def _get_db(self):
        from .context_db import get_db

        return await get_db()

    async def init_table(self) -> None:
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            db = await self._get_db()
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_embeddings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    corpus_id TEXT NOT NULL,
                    doc_id TEXT NOT NULL,
                    chunk_id INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT '',
                    tags TEXT NOT NULL DEFAULT '',
                    session_key TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    last_recalled_at REAL NOT NULL DEFAULT 0,
                    recall_count INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(corpus_id, doc_id, chunk_id)
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_corpus ON knowledge_embeddings(corpus_id)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_session ON knowledge_embeddings(session_key)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_doc ON knowledge_embeddings(corpus_id, doc_id)"
            )
            await db.commit()
            self._initialized = True

    @staticmethod
    def _normalize_tags(tags: Iterable[str] | str | None) -> list[str]:
        if tags is None:
            return []
        if isinstance(tags, str):
            value = tags.strip()
            if not value:
                return []
            try:
                loaded = json.loads(value)
            except Exception:
                return [item.strip() for item in value.split(",") if item.strip()]
            if isinstance(loaded, list):
                return [str(item).strip() for item in loaded if str(item).strip()]
            return [str(loaded).strip()] if str(loaded).strip() else []
        return [str(item).strip() for item in tags if str(item).strip()]

    async def delete_document(self, *, corpus_id: str, doc_id: str) -> int:
        await self.init_table()
        db = await self._get_db()
        cursor = await db.execute(
            "DELETE FROM knowledge_embeddings WHERE corpus_id = ? AND doc_id = ?",
            (str(corpus_id or "").strip(), str(doc_id or "").strip()),
        )
        await db.commit()
        return int(cursor.rowcount or 0)

    async def upsert_document(
        self,
        *,
        corpus_id: str,
        doc_id: str,
        chunks: list[str],
        embeddings: list[Any],
        title: str = "",
        source: str = "",
        tags: Iterable[str] | str | None = None,
        session_key: str = "",
    ) -> int:
        """覆盖写入文档块，返回写入块数。"""
        await self.init_table()

        if not chunks or not embeddings or len(chunks) != len(embeddings):
            return 0

        import numpy as np  # type: ignore

        corpus = str(corpus_id or "").strip() or "default"
        document = str(doc_id or "").strip()
        if not document:
            return 0

        now = time.time()
        normalized_tags = self._normalize_tags(tags)
        tags_json = json.dumps(normalized_tags, ensure_ascii=False)
        title_value = str(title or "").strip()
        source_value = str(source or "").strip()
        session_value = str(session_key or "").strip()

        db = await self._get_db()
        await db.execute(
            "DELETE FROM knowledge_embeddings WHERE corpus_id = ? AND doc_id = ?",
            (corpus, document),
        )

        inserted = 0
        for index, (chunk, emb) in enumerate(zip(chunks, embeddings), start=1):
            content = str(chunk or "").strip()
            if not content:
                continue
            emb_bytes = np.asarray(emb, dtype=np.float32).tobytes()
            await db.execute(
                """
                INSERT INTO knowledge_embeddings
                (corpus_id, doc_id, chunk_id, content, embedding, title, source, tags,
                 session_key, created_at, updated_at, last_recalled_at, recall_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    corpus,
                    document,
                    index,
                    content,
                    emb_bytes,
                    title_value,
                    source_value,
                    tags_json,
                    session_value,
                    now,
                    now,
                    0.0,
                ),
            )
            inserted += 1

        await db.commit()
        return inserted

    async def search(
        self,
        query_embedding: Any,
        *,
        corpus_id: Optional[str] = None,
        session_key: Optional[str] = None,
        top_k: int = 5,
        min_similarity: float = 0.5,
    ) -> list[tuple[KnowledgeChunkEntry, float]]:
        """按向量相似度检索知识块。"""
        await self.init_table()
        db = await self._get_db()

        where_parts = ["1=1"]
        params: list[Any] = []
        if corpus_id:
            where_parts.append("corpus_id = ?")
            params.append(str(corpus_id))
        if session_key:
            where_parts.append("(session_key = '' OR session_key = ?)")
            params.append(str(session_key))
        where_clause = " AND ".join(where_parts)

        async with db.execute(
            f"""
            SELECT id, corpus_id, doc_id, chunk_id, content, embedding,
                   title, source, tags, session_key,
                   created_at, updated_at, last_recalled_at, recall_count
            FROM knowledge_embeddings
            WHERE {where_clause}
            """,
            params,
        ) as cursor:
            rows = await cursor.fetchall()
        if not rows:
            return []

        import numpy as np  # type: ignore

        query = np.asarray(query_embedding, dtype=np.float32)
        query_norm = float(np.linalg.norm(query) or 1.0)

        scored: list[tuple[KnowledgeChunkEntry, float]] = []
        for row in rows:
            try:
                embedding = row[5]
                vec = np.frombuffer(embedding, dtype=np.float32)
                if vec.size == 0:
                    continue
                vec_norm = float(np.linalg.norm(vec) or 1.0)
                score = float(np.dot(query, vec) / (query_norm * vec_norm))
            except Exception:
                continue
            if score < float(min_similarity):
                continue

            entry = KnowledgeChunkEntry(
                id=int(row[0]),
                corpus_id=str(row[1] or ""),
                doc_id=str(row[2] or ""),
                chunk_id=int(row[3] or 0),
                content=str(row[4] or ""),
                embedding=row[5],
                title=str(row[6] or ""),
                source=str(row[7] or ""),
                tags=self._normalize_tags(row[8]),
                session_key=str(row[9] or ""),
                created_at=float(row[10] or 0.0),
                updated_at=float(row[11] or 0.0),
                last_recalled_at=float(row[12] or 0.0),
                recall_count=int(row[13] or 0),
            )
            scored.append((entry, score))

        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[: max(1, int(top_k or 1))]

    async def update_recall(self, knowledge_id: int) -> None:
        await self.init_table()
        db = await self._get_db()
        await db.execute(
            """
            UPDATE knowledge_embeddings
            SET last_recalled_at = ?, recall_count = recall_count + 1
            WHERE id = ?
            """,
            (time.time(), int(knowledge_id)),
        )
        await db.commit()

    async def count(self, *, corpus_id: Optional[str] = None) -> int:
        await self.init_table()
        db = await self._get_db()
        if corpus_id:
            async with db.execute(
                "SELECT COUNT(*) FROM knowledge_embeddings WHERE corpus_id = ?",
                (str(corpus_id),),
            ) as cursor:
                row = await cursor.fetchone()
        else:
            async with db.execute("SELECT COUNT(*) FROM knowledge_embeddings") as cursor:
                row = await cursor.fetchone()
        return int(row[0] if row else 0)

    async def list_corpora(self) -> list[dict[str, Any]]:
        """列出语料库统计。"""
        await self.init_table()
        db = await self._get_db()
        async with db.execute(
            """
            SELECT corpus_id, COUNT(DISTINCT doc_id) AS doc_count, COUNT(*) AS chunk_count
            FROM knowledge_embeddings
            GROUP BY corpus_id
            ORDER BY corpus_id
            """
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            {
                "corpus_id": str(row[0] or ""),
                "doc_count": int(row[1] or 0),
                "chunk_count": int(row[2] or 0),
            }
            for row in rows
        ]

    async def list_documents(self, corpus_id: str) -> list[dict[str, Any]]:
        """列出语料库中的文档。"""
        await self.init_table()
        db = await self._get_db()
        async with db.execute(
            """
            SELECT
                doc_id,
                COALESCE(MAX(title), '') AS title,
                COALESCE(MAX(source), '') AS source,
                COALESCE(MAX(tags), '') AS tags,
                MIN(created_at) AS created_at,
                COUNT(*) AS chunk_count
            FROM knowledge_embeddings
            WHERE corpus_id = ?
            GROUP BY doc_id
            ORDER BY created_at DESC, doc_id
            """,
            (str(corpus_id or "").strip(),),
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            {
                "doc_id": str(row[0] or ""),
                "title": str(row[1] or ""),
                "source": str(row[2] or ""),
                "tags": self._normalize_tags(row[3]),
                "created_at": float(row[4] or 0.0),
                "chunk_count": int(row[5] or 0),
            }
            for row in rows
        ]

    async def list_chunks(self, corpus_id: str, doc_id: str) -> list[dict[str, Any]]:
        """列出指定文档的切片。"""
        await self.init_table()
        db = await self._get_db()
        async with db.execute(
            """
            SELECT chunk_id, content, recall_count, created_at
            FROM knowledge_embeddings
            WHERE corpus_id = ? AND doc_id = ?
            ORDER BY chunk_id
            """,
            (str(corpus_id or "").strip(), str(doc_id or "").strip()),
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            {
                "chunk_id": int(row[0] or 0),
                "content": str(row[1] or ""),
                "recall_count": int(row[2] or 0),
                "created_at": float(row[3] or 0.0),
            }
            for row in rows
        ]


_knowledge_store: KnowledgeStore | None = None


def get_knowledge_store() -> KnowledgeStore:
    global _knowledge_store
    if _knowledge_store is None:
        _knowledge_store = KnowledgeStore()
    return _knowledge_store
