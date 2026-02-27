"""Persistent agent trace store (SQLite).

Design goals:
- Best-effort: tracing must never break the main chat flow.
- Stable schema: a single `agent_traces` table keyed by request_id.
- WebUI-friendly: store plan/events as JSON strings for easy export.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..config import plugin_config
from ..infra.logging import logger as log
from ..utils.context_db import get_db


def _now() -> float:
    return time.time()


def _safe_json_dumps(value: Any, *, default: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return json.dumps(default, ensure_ascii=False)


def _safe_json_loads(value: str, *, default: Any) -> Any:
    try:
        return json.loads(value)
    except Exception:
        return default


def _resolve_session_key(user_id: str, group_id: str) -> str:
    gid = str(group_id or "").strip()
    uid = str(user_id or "").strip()
    if gid:
        return f"group:{gid}"
    if uid:
        return f"private:{uid}"
    return ""


@dataclass
class TraceRow:
    request_id: str
    session_key: str
    user_id: str
    group_id: str
    created_at: float
    plan: Dict[str, Any]
    events: List[Dict[str, Any]]


class SQLiteTraceStore:
    """SQLite-backed trace store."""

    def __init__(self) -> None:
        self._last_prune_at: float = 0.0

    async def init_table(self) -> None:
        """Ensure tables exist (idempotent)."""
        db = await get_db()
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_traces (
                request_id TEXT PRIMARY KEY,
                session_key TEXT NOT NULL,
                user_id TEXT NOT NULL DEFAULT '',
                group_id TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                plan_json TEXT NOT NULL DEFAULT '',
                events_json TEXT NOT NULL DEFAULT '[]'
            )
            """
        )
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_agent_traces_session_created
            ON agent_traces(session_key, created_at)
            """
        )
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_agent_traces_created
            ON agent_traces(created_at)
            """
        )
        await db.commit()

    def _enabled(self) -> bool:
        try:
            return bool(getattr(plugin_config, "mika_trace_enabled", True))
        except Exception:
            return False

    async def _ensure_row(
        self,
        *,
        request_id: str,
        session_key: str,
        user_id: str,
        group_id: str,
        created_at: float,
    ) -> None:
        db = await get_db()
        await db.execute(
            """
            INSERT OR IGNORE INTO agent_traces
                (request_id, session_key, user_id, group_id, created_at, plan_json, events_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request_id,
                session_key,
                user_id,
                group_id,
                float(created_at),
                "",
                "[]",
            ),
        )

    async def append_event(
        self,
        *,
        request_id: str,
        session_key: str,
        user_id: str = "",
        group_id: str = "",
        event: Dict[str, Any],
    ) -> None:
        if not self._enabled():
            return
        rid = str(request_id or "").strip()
        if not rid:
            return

        sk = str(session_key or "").strip() or _resolve_session_key(user_id, group_id)
        if not sk:
            # Keep schema stable: still allow storing with an "unknown" session key.
            sk = "unknown"

        safe_event = dict(event or {})
        safe_event.setdefault("ts", _now())

        try:
            await self.init_table()
            await self._ensure_row(
                request_id=rid,
                session_key=sk,
                user_id=str(user_id or "").strip(),
                group_id=str(group_id or "").strip(),
                created_at=float(safe_event["ts"] or _now()),
            )

            db = await get_db()
            async with db.execute(
                "SELECT events_json FROM agent_traces WHERE request_id = ? LIMIT 1",
                (rid,),
            ) as cursor:
                row = await cursor.fetchone()

            events = _safe_json_loads(str(row[0] or "[]") if row else "[]", default=[])
            if not isinstance(events, list):
                events = []
            events.append(safe_event)

            await db.execute(
                "UPDATE agent_traces SET events_json = ? WHERE request_id = ?",
                (_safe_json_dumps(events, default=[]), rid),
            )
            await db.commit()
        except Exception as exc:
            log.debug(f"[trace] append_event failed: {exc}")
        finally:
            try:
                await self.prune_if_needed()
            except Exception:
                pass

    async def set_plan(
        self,
        *,
        request_id: str,
        session_key: str,
        user_id: str = "",
        group_id: str = "",
        plan: Dict[str, Any],
    ) -> None:
        if not self._enabled():
            return
        rid = str(request_id or "").strip()
        if not rid:
            return
        sk = str(session_key or "").strip() or _resolve_session_key(user_id, group_id) or "unknown"
        try:
            await self.init_table()
            await self._ensure_row(
                request_id=rid,
                session_key=sk,
                user_id=str(user_id or "").strip(),
                group_id=str(group_id or "").strip(),
                created_at=_now(),
            )
            db = await get_db()
            await db.execute(
                "UPDATE agent_traces SET plan_json = ? WHERE request_id = ?",
                (_safe_json_dumps(plan or {}, default={}), rid),
            )
            await db.commit()
        except Exception as exc:
            log.debug(f"[trace] set_plan failed: {exc}")

    async def get_trace(self, request_id: str) -> Optional[TraceRow]:
        rid = str(request_id or "").strip()
        if not rid:
            return None
        try:
            await self.init_table()
            db = await get_db()
            async with db.execute(
                """
                SELECT request_id, session_key, user_id, group_id, created_at, plan_json, events_json
                FROM agent_traces
                WHERE request_id = ?
                LIMIT 1
                """,
                (rid,),
            ) as cursor:
                row = await cursor.fetchone()
            if not row:
                return None
            plan = _safe_json_loads(str(row[5] or ""), default={})
            events = _safe_json_loads(str(row[6] or "[]"), default=[])
            if not isinstance(plan, dict):
                plan = {}
            if not isinstance(events, list):
                events = []
            return TraceRow(
                request_id=str(row[0] or ""),
                session_key=str(row[1] or ""),
                user_id=str(row[2] or ""),
                group_id=str(row[3] or ""),
                created_at=float(row[4] or 0.0),
                plan=plan,
                events=[e for e in events if isinstance(e, dict)],
            )
        except Exception as exc:
            log.debug(f"[trace] get_trace failed: {exc}")
            return None

    async def list_recent(self, *, session_key: str = "", limit: int = 20) -> List[Dict[str, Any]]:
        resolved_limit = max(1, min(200, int(limit or 20)))
        sk = str(session_key or "").strip()
        try:
            await self.init_table()
            db = await get_db()
            if sk:
                async with db.execute(
                    """
                    SELECT request_id, session_key, user_id, group_id, created_at
                    FROM agent_traces
                    WHERE session_key = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (sk, resolved_limit),
                ) as cursor:
                    rows = await cursor.fetchall()
            else:
                async with db.execute(
                    """
                    SELECT request_id, session_key, user_id, group_id, created_at
                    FROM agent_traces
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (resolved_limit,),
                ) as cursor:
                    rows = await cursor.fetchall()
            out: List[Dict[str, Any]] = []
            for row in rows or []:
                out.append(
                    {
                        "request_id": str(row[0] or ""),
                        "session_key": str(row[1] or ""),
                        "user_id": str(row[2] or ""),
                        "group_id": str(row[3] or ""),
                        "created_at": float(row[4] or 0.0),
                    }
                )
            return out
        except Exception as exc:
            log.debug(f"[trace] list_recent failed: {exc}")
            return []

    async def prune_if_needed(self) -> None:
        if not self._enabled():
            return

        now = _now()
        # Avoid pruning too often.
        if now - self._last_prune_at < 600:
            return
        self._last_prune_at = now

        retention_days = int(getattr(plugin_config, "mika_trace_retention_days", 7) or 7)
        max_rows = int(getattr(plugin_config, "mika_trace_max_rows", 20000) or 20000)
        retention_days = max(1, retention_days)
        max_rows = max(100, max_rows)

        cutoff = now - float(retention_days) * 86400.0
        db = await get_db()
        await db.execute("DELETE FROM agent_traces WHERE created_at < ?", (cutoff,))

        async with db.execute("SELECT COUNT(*) FROM agent_traces") as cursor:
            row = await cursor.fetchone()
        total = int(row[0] or 0) if row else 0
        if total > max_rows:
            to_delete = total - max_rows
            await db.execute(
                """
                DELETE FROM agent_traces
                WHERE request_id IN (
                    SELECT request_id FROM agent_traces
                    ORDER BY created_at ASC
                    LIMIT ?
                )
                """,
                (to_delete,),
            )
        await db.commit()


_trace_store: Optional[SQLiteTraceStore] = None


def get_trace_store() -> SQLiteTraceStore:
    global _trace_store
    if _trace_store is None:
        _trace_store = SQLiteTraceStore()
    return _trace_store


class TraceAgentHooks:
    """Default AgentRunHooks implementation that persists traces to SQLite."""

    def __init__(self, *, store: Optional[SQLiteTraceStore] = None) -> None:
        self._store = store or get_trace_store()

    async def on_before_llm(self, payload: dict[str, Any]) -> None:
        rid = str(payload.get("request_id") or "").strip()
        if not rid:
            return
        user_id = str(payload.get("user_id") or "").strip()
        group_id = str(payload.get("group_id") or "").strip()
        session_key = _resolve_session_key(user_id, group_id)
        await self._store.append_event(
            request_id=rid,
            session_key=session_key,
            user_id=user_id,
            group_id=group_id,
            event={"type": "before_llm", **payload},
        )

    async def on_after_llm(self, payload: dict[str, Any]) -> None:
        rid = str(payload.get("request_id") or "").strip()
        if not rid:
            return
        user_id = str(payload.get("user_id") or "").strip()
        group_id = str(payload.get("group_id") or "").strip()
        session_key = _resolve_session_key(user_id, group_id)
        await self._store.append_event(
            request_id=rid,
            session_key=session_key,
            user_id=user_id,
            group_id=group_id,
            event={"type": "after_llm", **payload},
        )

    async def on_tool_start(self, payload: dict[str, Any]) -> None:
        rid = str(payload.get("request_id") or "").strip()
        if not rid:
            return
        user_id = str(payload.get("user_id") or "").strip()
        group_id = str(payload.get("group_id") or "").strip()
        session_key = str(payload.get("session_key") or "").strip() or _resolve_session_key(user_id, group_id)
        await self._store.append_event(
            request_id=rid,
            session_key=session_key or "unknown",
            user_id=user_id,
            group_id=group_id,
            event={"type": "tool_start", **payload},
        )

    async def on_tool_end(self, payload: dict[str, Any]) -> None:
        rid = str(payload.get("request_id") or "").strip()
        if not rid:
            return
        user_id = str(payload.get("user_id") or "").strip()
        group_id = str(payload.get("group_id") or "").strip()
        session_key = str(payload.get("session_key") or "").strip() or _resolve_session_key(user_id, group_id)
        await self._store.append_event(
            request_id=rid,
            session_key=session_key or "unknown",
            user_id=user_id,
            group_id=group_id,
            event={"type": "tool_end", **payload},
        )


__all__ = ["SQLiteTraceStore", "TraceAgentHooks", "TraceRow", "get_trace_store"]
