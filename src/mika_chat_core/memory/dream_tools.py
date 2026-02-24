"""Dream agent topic-maintenance tools."""

from __future__ import annotations

from typing import Any, Dict, List

from .topic_store import TopicSummaryEntry, get_topic_store


def _entry_to_dict(entry: TopicSummaryEntry) -> Dict[str, Any]:
    return {
        "id": int(entry.id),
        "session_key": entry.session_key,
        "topic": entry.topic,
        "summary": entry.summary,
        "keywords": list(entry.keywords),
        "key_points": list(entry.key_points),
        "participants": list(entry.participants),
        "timestamp_start": float(entry.timestamp_start),
        "timestamp_end": float(entry.timestamp_end),
        "source_message_count": int(entry.source_message_count),
        "created_at": float(entry.created_at),
        "updated_at": float(entry.updated_at),
    }


class DreamTools:
    async def search_topics(self, *, session_key: str, limit: int = 20) -> List[Dict[str, Any]]:
        rows = await get_topic_store().list_topics(session_key, limit=max(1, int(limit or 20)))
        return [_entry_to_dict(item) for item in rows]

    async def get_topic_detail(self, *, session_key: str, topic: str) -> Dict[str, Any] | None:
        row = await get_topic_store().get_topic(session_key, topic)
        return _entry_to_dict(row) if row is not None else None

    async def update_topic(
        self,
        *,
        session_key: str,
        topic: str,
        summary: str,
        keywords: list[str] | None = None,
        key_points: list[str] | None = None,
        participants: list[str] | None = None,
        timestamp_start: float = 0.0,
        timestamp_end: float = 0.0,
        source_message_count: int = 1,
    ) -> int:
        return await get_topic_store().upsert_topic_summary(
            session_key=session_key,
            topic=topic,
            keywords=keywords or [],
            summary=summary,
            key_points=key_points or [],
            participants=participants or [],
            timestamp_start=timestamp_start,
            timestamp_end=timestamp_end,
            source_message_count=max(1, int(source_message_count or 1)),
        )

    async def delete_topic(self, *, session_key: str, topic: str) -> bool:
        return await get_topic_store().delete_topic(session_key, topic)

    async def create_topic(
        self,
        *,
        session_key: str,
        topic: str,
        summary: str,
        keywords: list[str] | None = None,
        key_points: list[str] | None = None,
        participants: list[str] | None = None,
    ) -> int:
        return await self.update_topic(
            session_key=session_key,
            topic=topic,
            summary=summary,
            keywords=keywords,
            key_points=key_points,
            participants=participants,
            timestamp_start=0.0,
            timestamp_end=0.0,
            source_message_count=1,
        )


_dream_tools: DreamTools | None = None


def get_dream_tools() -> DreamTools:
    global _dream_tools
    if _dream_tools is None:
        _dream_tools = DreamTools()
    return _dream_tools

