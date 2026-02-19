"""Dream agent for offline topic-memory cleanup."""

from __future__ import annotations

import re
import time
from typing import Any, Dict, List

from ..infra.logging import logger as log
from ..utils.prompt_loader import load_prompt_yaml
from .dream_tools import get_dream_tools


def _normalize_topic_name(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE)
    return text


def _merge_unique_strings(*groups: List[str], limit: int) -> List[str]:
    result: List[str] = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            text = str(item or "").strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            result.append(text)
            if len(result) >= limit:
                return result
    return result


class DreamAgent:
    def __init__(self) -> None:
        self._tools = get_dream_tools()

    @staticmethod
    def _dream_defaults() -> Dict[str, Any]:
        config = load_prompt_yaml("dream.yaml")
        return {
            "min_summary_chars": int(config.get("min_summary_chars") or 12),
            "max_merged_summary_chars": int(config.get("max_merged_summary_chars") or 220),
            "max_keywords": int(config.get("max_keywords") or 8),
            "max_key_points": int(config.get("max_key_points") or 6),
            "max_participants": int(config.get("max_participants") or 8),
        }

    async def run_session(
        self,
        *,
        session_key: str,
        max_iterations: int = 5,
    ) -> Dict[str, int]:
        session = str(session_key or "").strip()
        if not session:
            return {"merged": 0, "deleted": 0, "updated": 0}

        defaults = self._dream_defaults()
        min_summary_chars = max(4, int(defaults["min_summary_chars"]))
        max_merged_summary_chars = max(64, int(defaults["max_merged_summary_chars"]))
        max_keywords = max(1, int(defaults["max_keywords"]))
        max_key_points = max(1, int(defaults["max_key_points"]))
        max_participants = max(1, int(defaults["max_participants"]))
        loop_budget = max(1, int(max_iterations or 5))

        topics = await self._tools.search_topics(session_key=session, limit=64)
        if len(topics) <= 1:
            return {"merged": 0, "deleted": 0, "updated": 0}

        merged = 0
        deleted = 0
        updated = 0
        used_budget = 0

        by_normalized: Dict[str, List[Dict[str, Any]]] = {}
        for item in topics:
            key = _normalize_topic_name(str(item.get("topic") or ""))
            if not key:
                continue
            by_normalized.setdefault(key, []).append(item)

        for group in by_normalized.values():
            if used_budget >= loop_budget:
                break
            if len(group) <= 1:
                continue

            sorted_group = sorted(group, key=lambda item: float(item.get("updated_at") or 0.0), reverse=True)
            primary = dict(sorted_group[0])
            duplicates = sorted_group[1:]
            primary_topic = str(primary.get("topic") or "").strip()
            if not primary_topic:
                continue

            merged_summary_parts = [str(primary.get("summary") or "").strip()]
            all_keywords = list(primary.get("keywords") or [])
            all_key_points = list(primary.get("key_points") or [])
            all_participants = list(primary.get("participants") or [])
            timestamp_start = float(primary.get("timestamp_start") or 0.0)
            timestamp_end = float(primary.get("timestamp_end") or 0.0)
            source_count = int(primary.get("source_message_count") or 0)

            for extra in duplicates:
                if used_budget >= loop_budget:
                    break
                used_budget += 1
                merged += 1

                extra_summary = str(extra.get("summary") or "").strip()
                if extra_summary:
                    merged_summary_parts.append(extra_summary)
                all_keywords.extend(list(extra.get("keywords") or []))
                all_key_points.extend(list(extra.get("key_points") or []))
                all_participants.extend(list(extra.get("participants") or []))
                timestamp_start = min(timestamp_start or float("inf"), float(extra.get("timestamp_start") or 0.0))
                timestamp_end = max(timestamp_end, float(extra.get("timestamp_end") or 0.0))
                source_count += int(extra.get("source_message_count") or 0)

                if await self._tools.delete_topic(session_key=session, topic=str(extra.get("topic") or "")):
                    deleted += 1

            merged_summary = "；".join(part for part in merged_summary_parts if part)
            if len(merged_summary) > max_merged_summary_chars:
                merged_summary = merged_summary[:max_merged_summary_chars].rstrip() + "..."
            merged_summary = merged_summary.strip()

            if merged_summary:
                await self._tools.update_topic(
                    session_key=session,
                    topic=primary_topic,
                    summary=merged_summary,
                    keywords=_merge_unique_strings(all_keywords, limit=max_keywords),
                    key_points=_merge_unique_strings(all_key_points, limit=max_key_points),
                    participants=_merge_unique_strings(all_participants, limit=max_participants),
                    timestamp_start=0.0 if timestamp_start == float("inf") else timestamp_start,
                    timestamp_end=timestamp_end,
                    source_message_count=max(1, source_count),
                )
                updated += 1

        if used_budget < loop_budget:
            refreshed = await self._tools.search_topics(session_key=session, limit=64)
            for item in refreshed:
                if used_budget >= loop_budget:
                    break
                summary = str(item.get("summary") or "").strip()
                source_count = int(item.get("source_message_count") or 0)
                if len(summary) >= min_summary_chars or source_count > 1:
                    continue
                used_budget += 1
                if await self._tools.delete_topic(session_key=session, topic=str(item.get("topic") or "")):
                    deleted += 1

        return {"merged": merged, "deleted": deleted, "updated": updated}


class DreamRunLock:
    def __init__(self) -> None:
        self._running_sessions: set[str] = set()

    def acquire(self, session_key: str) -> bool:
        session = str(session_key or "").strip()
        if not session or session in self._running_sessions:
            return False
        self._running_sessions.add(session)
        return True

    def release(self, session_key: str) -> None:
        self._running_sessions.discard(str(session_key or "").strip())


class DreamScheduler:
    def __init__(self) -> None:
        self._agent = DreamAgent()
        self._run_lock = DreamRunLock()
        self._last_activity: Dict[str, float] = {}

    async def on_session_activity(
        self,
        *,
        session_key: str,
        enabled: bool,
        idle_minutes: int,
        max_iterations: int,
        request_id: str = "",
    ) -> None:
        session = str(session_key or "").strip()
        if not session:
            return
        now = time.monotonic()
        previous = float(self._last_activity.get(session, 0.0) or 0.0)
        self._last_activity[session] = now
        if not bool(enabled):
            return
        idle_seconds = max(60, int(idle_minutes or 30) * 60)
        if previous <= 0 or (now - previous) < idle_seconds:
            return
        if not self._run_lock.acquire(session):
            return

        async def _run() -> None:
            try:
                result = await self._agent.run_session(
                    session_key=session,
                    max_iterations=max_iterations,
                )
                log.info(
                    f"[req:{request_id}] dream_run session={session} "
                    f"merged={result.get('merged', 0)} "
                    f"deleted={result.get('deleted', 0)} "
                    f"updated={result.get('updated', 0)}"
                )
            except Exception as exc:
                log.warning(f"[req:{request_id}] dream_run_failed session={session} error={exc}")
            finally:
                self._run_lock.release(session)

        import asyncio

        asyncio.create_task(_run())


_dream_scheduler: DreamScheduler | None = None


def get_dream_scheduler() -> DreamScheduler:
    global _dream_scheduler
    if _dream_scheduler is None:
        _dream_scheduler = DreamScheduler()
    return _dream_scheduler

