"""长期语义记忆存储（SQLite + numpy 向量检索）。"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Optional

from ..infra.logging import logger as log


@dataclass
class MemoryEntry:
    """一条长期记忆。"""

    id: int
    session_key: str
    user_id: str
    fact: str
    embedding: bytes
    created_at: float
    last_recalled_at: float
    recall_count: int
    source: str


class MemoryStore:
    """SQLite 长期记忆存储 + numpy 余弦相似度检索。"""

    def __init__(self) -> None:
        self._init_lock = asyncio.Lock()
        self._initialized = False

    async def _get_db(self):
        from .context_db import get_db

        return await get_db()

    async def init_table(self) -> None:
        """创建 memory_embeddings 表（幂等）。"""
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            db = await self._get_db()
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_embeddings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_key TEXT NOT NULL,
                    user_id TEXT NOT NULL DEFAULT '',
                    fact TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    created_at REAL NOT NULL,
                    last_recalled_at REAL NOT NULL,
                    recall_count INTEGER NOT NULL DEFAULT 0,
                    source TEXT NOT NULL DEFAULT 'extract',
                    UNIQUE(session_key, fact)
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_session ON memory_embeddings(session_key)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_user ON memory_embeddings(user_id)"
            )
            await db.commit()
            self._initialized = True
            log.debug("[MemoryStore] Table initialized.")

    async def add_memory(
        self,
        session_key: str,
        user_id: str,
        fact: str,
        embedding,
        source: str = "extract",
    ) -> int:
        """写入一条记忆，返回 ID；重复 fact（同 session）会被忽略。"""
        await self.init_table()

        import numpy as np  # type: ignore

        now = time.time()
        emb_bytes = np.asarray(embedding, dtype=np.float32).tobytes()
        db = await self._get_db()
        try:
            cursor = await db.execute(
                """
                INSERT OR IGNORE INTO memory_embeddings
                (session_key, user_id, fact, embedding, created_at, last_recalled_at, source)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(session_key or "").strip(),
                    str(user_id or "").strip(),
                    str(fact or "").strip(),
                    emb_bytes,
                    now,
                    now,
                    str(source or "extract").strip() or "extract",
                ),
            )
            await db.commit()
            return int(cursor.lastrowid or 0)
        except Exception as exc:
            log.warning(f"[MemoryStore] add_memory failed: {exc}")
            return 0

    async def search(
        self,
        query_embedding,
        *,
        top_k: int = 5,
        session_key: str | None = None,
        user_id: str | None = None,
        min_similarity: float = 0.5,
    ) -> list[tuple[MemoryEntry, float]]:
        """向量检索：SQL 过滤候选 -> numpy 余弦相似度 -> top-k。"""
        await self.init_table()
        db = await self._get_db()

        where_parts = ["1=1"]
        params: list[Any] = []
        if session_key:
            where_parts.append("session_key = ?")
            params.append(str(session_key))
        if user_id:
            where_parts.append("user_id = ?")
            params.append(str(user_id))
        where_clause = " AND ".join(where_parts)

        async with db.execute(
            f"""
            SELECT id, session_key, user_id, fact, embedding,
                   created_at, last_recalled_at, recall_count, source
            FROM memory_embeddings
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

        scored: list[tuple[MemoryEntry, float]] = []
        for row in rows:
            entry = MemoryEntry(
                id=int(row[0]),
                session_key=str(row[1] or ""),
                user_id=str(row[2] or ""),
                fact=str(row[3] or ""),
                embedding=row[4],
                created_at=float(row[5] or 0.0),
                last_recalled_at=float(row[6] or 0.0),
                recall_count=int(row[7] or 0),
                source=str(row[8] or "extract"),
            )
            try:
                vec = np.frombuffer(entry.embedding, dtype=np.float32)
                if vec.size == 0:
                    continue
                vec_norm = float(np.linalg.norm(vec) or 1.0)
                score = float(np.dot(query, vec) / (query_norm * vec_norm))
            except Exception:
                continue
            if score >= float(min_similarity):
                scored.append((entry, score))

        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[: max(1, int(top_k or 1))]

    async def update_recall(self, memory_id: int) -> None:
        """更新召回时间和次数。"""
        await self.init_table()
        db = await self._get_db()
        await db.execute(
            """
            UPDATE memory_embeddings
            SET last_recalled_at = ?, recall_count = recall_count + 1
            WHERE id = ?
            """,
            (time.time(), int(memory_id)),
        )
        await db.commit()

    async def delete_old_memories(self, max_age_days: int = 90) -> int:
        """清理过期记忆（低召回 + 超龄），返回删除条数。"""
        await self.init_table()
        cutoff = time.time() - int(max_age_days) * 86400
        db = await self._get_db()
        cursor = await db.execute(
            "DELETE FROM memory_embeddings WHERE created_at < ? AND recall_count < 3",
            (cutoff,),
        )
        await db.commit()
        return int(cursor.rowcount or 0)

    async def count(self, session_key: Optional[str] = None) -> int:
        await self.init_table()
        db = await self._get_db()
        if session_key:
            async with db.execute(
                "SELECT COUNT(*) FROM memory_embeddings WHERE session_key = ?",
                (str(session_key),),
            ) as cursor:
                row = await cursor.fetchone()
        else:
            async with db.execute("SELECT COUNT(*) FROM memory_embeddings") as cursor:
                row = await cursor.fetchone()
        return int(row[0] if row else 0)

    async def list_sessions(self) -> list[dict[str, Any]]:
        """列出会话维度的记忆统计。"""
        await self.init_table()
        db = await self._get_db()
        async with db.execute(
            """
            SELECT session_key, COUNT(*) AS fact_count
            FROM memory_embeddings
            GROUP BY session_key
            ORDER BY session_key
            """
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            {
                "session_key": str(row[0] or ""),
                "count": int(row[1] or 0),
            }
            for row in rows
        ]

    async def list_facts(self, session_key: str) -> list[dict[str, Any]]:
        """列出指定会话下的记忆。"""
        await self.init_table()
        db = await self._get_db()
        async with db.execute(
            """
            SELECT id, user_id, fact, created_at, last_recalled_at, recall_count, source
            FROM memory_embeddings
            WHERE session_key = ?
            ORDER BY created_at DESC, id DESC
            """,
            (str(session_key or "").strip(),),
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            {
                "id": int(row[0] or 0),
                "user_id": str(row[1] or ""),
                "fact": str(row[2] or ""),
                "created_at": float(row[3] or 0.0),
                "last_recalled_at": float(row[4] or 0.0),
                "recall_count": int(row[5] or 0),
                "source": str(row[6] or "extract"),
            }
            for row in rows
        ]

    async def delete_memory(self, memory_id: int) -> bool:
        """删除指定记忆条目。"""
        await self.init_table()
        db = await self._get_db()
        cursor = await db.execute(
            "DELETE FROM memory_embeddings WHERE id = ?",
            (int(memory_id),),
        )
        await db.commit()
        return int(cursor.rowcount or 0) > 0


_memory_store: MemoryStore | None = None


def get_memory_store() -> MemoryStore:
    global _memory_store
    if _memory_store is None:
        _memory_store = MemoryStore()
    return _memory_store
