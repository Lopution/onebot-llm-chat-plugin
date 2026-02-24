"""话题摘要存储（SQLite）。"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Iterable

@dataclass
class TopicSummaryEntry:
    """单条话题摘要记录。"""

    id: int
    session_key: str
    topic: str
    keywords: list[str]
    summary: str
    key_points: list[str]
    participants: list[str]
    timestamp_start: float
    timestamp_end: float
    source_message_count: int
    created_at: float
    updated_at: float


class TopicStore:
    """话题摘要与处理进度存储。"""

    def __init__(self) -> None:
        self._init_lock = asyncio.Lock()
        self._initialized = False

    async def _get_db(self):
        from ..utils.context_db import get_db

        return await get_db()

    @staticmethod
    def _normalize_list(value: Iterable[str] | str | None) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return []
            if text.startswith("[") and text.endswith("]"):
                try:
                    loaded = json.loads(text)
                except Exception:
                    loaded = []
                if isinstance(loaded, list):
                    return [str(item).strip() for item in loaded if str(item).strip()]
            return [item.strip() for item in text.split(",") if item.strip()]
        return [str(item).strip() for item in value if str(item).strip()]

    async def init_table(self) -> None:
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            db = await self._get_db()
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS topic_summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_key TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    keywords TEXT NOT NULL DEFAULT '[]',
                    summary TEXT NOT NULL DEFAULT '',
                    key_points TEXT NOT NULL DEFAULT '[]',
                    participants TEXT NOT NULL DEFAULT '[]',
                    timestamp_start REAL NOT NULL DEFAULT 0,
                    timestamp_end REAL NOT NULL DEFAULT 0,
                    source_message_count INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(session_key, topic)
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_topic_summaries_session ON topic_summaries(session_key)"
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS topic_summary_state (
                    session_key TEXT PRIMARY KEY,
                    processed_message_count INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL
                )
                """
            )
            await db.commit()
            self._initialized = True

    async def get_processed_message_count(self, session_key: str) -> int:
        await self.init_table()
        db = await self._get_db()
        async with db.execute(
            "SELECT processed_message_count FROM topic_summary_state WHERE session_key = ?",
            (str(session_key or "").strip(),),
        ) as cursor:
            row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def set_processed_message_count(self, session_key: str, count: int) -> None:
        await self.init_table()
        db = await self._get_db()
        await db.execute(
            """
            INSERT INTO topic_summary_state (session_key, processed_message_count, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(session_key) DO UPDATE SET
                processed_message_count = excluded.processed_message_count,
                updated_at = excluded.updated_at
            """,
            (str(session_key or "").strip(), int(max(0, count)), time.time()),
        )
        await db.commit()

    async def upsert_topic_summary(
        self,
        *,
        session_key: str,
        topic: str,
        keywords: Iterable[str] | str | None,
        summary: str,
        key_points: Iterable[str] | str | None,
        participants: Iterable[str] | str | None,
        timestamp_start: float,
        timestamp_end: float,
        source_message_count: int,
    ) -> int:
        await self.init_table()
        session = str(session_key or "").strip()
        topic_name = str(topic or "").strip()
        summary_text = str(summary or "").strip()
        if not session or not topic_name or not summary_text:
            return 0

        now = time.time()
        keywords_json = json.dumps(self._normalize_list(keywords), ensure_ascii=False)
        key_points_json = json.dumps(self._normalize_list(key_points), ensure_ascii=False)
        participants_json = json.dumps(self._normalize_list(participants), ensure_ascii=False)
        db = await self._get_db()
        cursor = await db.execute(
            """
            INSERT INTO topic_summaries (
                session_key, topic, keywords, summary, key_points, participants,
                timestamp_start, timestamp_end, source_message_count, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_key, topic) DO UPDATE SET
                keywords = excluded.keywords,
                summary = excluded.summary,
                key_points = excluded.key_points,
                participants = excluded.participants,
                timestamp_start = excluded.timestamp_start,
                timestamp_end = excluded.timestamp_end,
                source_message_count = topic_summaries.source_message_count + excluded.source_message_count,
                updated_at = excluded.updated_at
            """,
            (
                session,
                topic_name,
                keywords_json,
                summary_text,
                key_points_json,
                participants_json,
                float(timestamp_start or 0.0),
                float(timestamp_end or 0.0),
                int(max(0, source_message_count)),
                now,
                now,
            ),
        )
        await db.commit()
        if cursor.lastrowid:
            return int(cursor.lastrowid)

        async with db.execute(
            "SELECT id FROM topic_summaries WHERE session_key = ? AND topic = ?",
            (session, topic_name),
        ) as select_cursor:
            row = await select_cursor.fetchone()
        return int(row[0]) if row else 0

    async def list_topics(self, session_key: str, limit: int = 20) -> list[TopicSummaryEntry]:
        await self.init_table()
        db = await self._get_db()
        async with db.execute(
            """
            SELECT id, session_key, topic, keywords, summary, key_points, participants,
                   timestamp_start, timestamp_end, source_message_count, created_at, updated_at
            FROM topic_summaries
            WHERE session_key = ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (str(session_key or "").strip(), max(1, int(limit or 20))),
        ) as cursor:
            rows = await cursor.fetchall()

        return [
            TopicSummaryEntry(
                id=int(row[0] or 0),
                session_key=str(row[1] or ""),
                topic=str(row[2] or ""),
                keywords=self._normalize_list(row[3]),
                summary=str(row[4] or ""),
                key_points=self._normalize_list(row[5]),
                participants=self._normalize_list(row[6]),
                timestamp_start=float(row[7] or 0.0),
                timestamp_end=float(row[8] or 0.0),
                source_message_count=int(row[9] or 0),
                created_at=float(row[10] or 0.0),
                updated_at=float(row[11] or 0.0),
            )
            for row in rows
        ]

    async def get_topic(self, session_key: str, topic: str) -> TopicSummaryEntry | None:
        await self.init_table()
        db = await self._get_db()
        async with db.execute(
            """
            SELECT id, session_key, topic, keywords, summary, key_points, participants,
                   timestamp_start, timestamp_end, source_message_count, created_at, updated_at
            FROM topic_summaries
            WHERE session_key = ? AND topic = ?
            LIMIT 1
            """,
            (str(session_key or "").strip(), str(topic or "").strip()),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return TopicSummaryEntry(
            id=int(row[0] or 0),
            session_key=str(row[1] or ""),
            topic=str(row[2] or ""),
            keywords=self._normalize_list(row[3]),
            summary=str(row[4] or ""),
            key_points=self._normalize_list(row[5]),
            participants=self._normalize_list(row[6]),
            timestamp_start=float(row[7] or 0.0),
            timestamp_end=float(row[8] or 0.0),
            source_message_count=int(row[9] or 0),
            created_at=float(row[10] or 0.0),
            updated_at=float(row[11] or 0.0),
        )

    async def delete_topic(self, session_key: str, topic: str) -> bool:
        await self.init_table()
        db = await self._get_db()
        cursor = await db.execute(
            "DELETE FROM topic_summaries WHERE session_key = ? AND topic = ?",
            (str(session_key or "").strip(), str(topic or "").strip()),
        )
        await db.commit()
        return int(cursor.rowcount or 0) > 0

    async def list_sessions(self) -> list[dict[str, Any]]:
        await self.init_table()
        db = await self._get_db()
        async with db.execute(
            """
            SELECT session_key, COUNT(*) AS topic_count, MAX(updated_at) AS last_updated_at
            FROM topic_summaries
            GROUP BY session_key
            ORDER BY last_updated_at DESC
            """
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            {
                "session_key": str(row[0] or ""),
                "topic_count": int(row[1] or 0),
                "last_updated_at": float(row[2] or 0.0),
            }
            for row in rows
        ]

    async def clear_session(self, session_key: str) -> None:
        await self.init_table()
        session = str(session_key or "").strip()
        db = await self._get_db()
        await db.execute("DELETE FROM topic_summaries WHERE session_key = ?", (session,))
        await db.execute("DELETE FROM topic_summary_state WHERE session_key = ?", (session,))
        await db.commit()


_topic_store: TopicStore | None = None


def get_topic_store() -> TopicStore:
    global _topic_store
    if _topic_store is None:
        _topic_store = TopicStore()
    return _topic_store
