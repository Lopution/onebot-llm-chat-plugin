"""Database maintenance service (SQLite).

Goals:
- Keep long-running deployments stable (DB size doesn't grow without bound).
- Best-effort: maintenance must never block chat flow (runs in background).
- Conservative pruning: only delete clearly old/overflow data.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from ..infra.logging import logger as log
from .context_db import get_db, get_db_path, init_database


def _now_wall() -> float:
    return time.time()


def _now_mono() -> float:
    return time.monotonic()


def _hours_to_seconds(hours: int) -> int:
    return max(1, int(hours or 0)) * 3600


@dataclass
class MaintenanceStats:
    archive_deleted_by_age: int = 0
    archive_deleted_by_rows: int = 0
    traces_deleted_by_age: int = 0
    traces_deleted_by_rows: int = 0
    memories_deleted: int = 0
    vacuum_ok: bool = False
    analyze_ok: bool = False
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "archive_deleted_by_age": int(self.archive_deleted_by_age),
            "archive_deleted_by_rows": int(self.archive_deleted_by_rows),
            "traces_deleted_by_age": int(self.traces_deleted_by_age),
            "traces_deleted_by_rows": int(self.traces_deleted_by_rows),
            "memories_deleted": int(self.memories_deleted),
            "vacuum_ok": bool(self.vacuum_ok),
            "analyze_ok": bool(self.analyze_ok),
            "error": str(self.error or ""),
            "db_path": str(get_db_path()),
        }


class DBMaintenanceService:
    def __init__(self) -> None:
        # Avoid running immediately on startup; first run happens after interval.
        now = _now_mono()
        self._last_run_at: float = now
        self._last_vacuum_at: float = now
        self._run_lock = asyncio.Lock()

    @staticmethod
    def _enabled(plugin_cfg: Any) -> bool:
        return bool(getattr(plugin_cfg, "mika_db_maintenance_enabled", True))

    @staticmethod
    def _interval_seconds(plugin_cfg: Any) -> int:
        hours = int(getattr(plugin_cfg, "mika_db_vacuum_interval_hours", 72) or 72)
        return _hours_to_seconds(hours)

    async def maybe_schedule(self, *, plugin_cfg: Any, request_id: str = "") -> bool:
        """Schedule a background maintenance run if interval has passed."""

        if not self._enabled(plugin_cfg):
            return False
        interval = self._interval_seconds(plugin_cfg)
        now = _now_mono()
        if (now - float(self._last_run_at or 0.0)) < float(interval):
            return False
        # Update before spawn to avoid stampede.
        self._last_run_at = now

        from ..runtime import get_task_supervisor

        get_task_supervisor().spawn(
            self.run_once(plugin_cfg=plugin_cfg, request_id=request_id),
            name="db_maintenance",
            owner="db_maintenance",
            key="periodic",
        )
        return True

    async def run_once(self, *, plugin_cfg: Any, request_id: str = "") -> Dict[str, Any]:
        """Run maintenance now (prune + optional vacuum/analyze)."""

        if not self._enabled(plugin_cfg):
            return {"skipped": True, "reason": "disabled", "db_path": str(get_db_path())}

        if self._run_lock.locked():
            return {"skipped": True, "reason": "already_running", "db_path": str(get_db_path())}

        stats = MaintenanceStats()
        async with self._run_lock:
            try:
                await init_database()
                await self._prune_message_archive(plugin_cfg=plugin_cfg, stats=stats)
                await self._prune_agent_traces(plugin_cfg=plugin_cfg, stats=stats)
                await self._prune_memory_embeddings(plugin_cfg=plugin_cfg, stats=stats)

                # Vacuum/Analyze are expensive; keep them on a separate interval.
                interval = self._interval_seconds(plugin_cfg)
                now = _now_mono()
                if (now - float(self._last_vacuum_at or 0.0)) >= float(interval):
                    await self._vacuum_analyze(stats=stats)
                    self._last_vacuum_at = now
            except Exception as exc:
                stats.error = f"{type(exc).__name__}: {exc}"
                log.warning(f"[req:{request_id}] db_maintenance_failed | {stats.error}", exc_info=True)

        result = stats.to_dict()
        if not stats.error:
            log.info(
                f"[req:{request_id}] db_maintenance_ok | "
                f"archive_age={stats.archive_deleted_by_age} archive_rows={stats.archive_deleted_by_rows} "
                f"traces_age={stats.traces_deleted_by_age} traces_rows={stats.traces_deleted_by_rows} "
                f"memories={stats.memories_deleted} vacuum={1 if stats.vacuum_ok else 0}"
            )
        return result

    async def _prune_message_archive(self, *, plugin_cfg: Any, stats: MaintenanceStats) -> None:
        max_days = int(getattr(plugin_cfg, "mika_db_prune_archive_max_days", 14) or 14)
        max_days = max(1, max_days)
        max_rows = int(getattr(plugin_cfg, "mika_db_prune_archive_max_rows_per_session", 20000) or 20000)
        max_rows = max(1, max_rows)

        cutoff = _now_wall() - max_days * 86400
        db = await get_db()

        # 1) prune by age (only when timestamp is present)
        cursor = await db.execute(
            "DELETE FROM message_archive WHERE timestamp IS NOT NULL AND timestamp > 0 AND timestamp < ?",
            (float(cutoff),),
        )
        stats.archive_deleted_by_age += int(cursor.rowcount or 0)

        # 2) enforce per-session row limit (keep newest max_rows)
        async with db.execute(
            """
            SELECT context_key, COUNT(*) AS cnt
            FROM message_archive
            GROUP BY context_key
            HAVING cnt > ?
            """,
            (int(max_rows),),
        ) as cur:
            keys = [str(row[0] or "") for row in (await cur.fetchall()) or []]

        for key in keys:
            if not key:
                continue
            cursor = await db.execute(
                """
                DELETE FROM message_archive
                WHERE id IN (
                    SELECT id FROM message_archive
                    WHERE context_key = ?
                    ORDER BY COALESCE(timestamp, 0) DESC, id DESC
                    LIMIT -1 OFFSET ?
                )
                """,
                (key, int(max_rows)),
            )
            stats.archive_deleted_by_rows += int(cursor.rowcount or 0)

        await db.commit()

    async def _prune_agent_traces(self, *, plugin_cfg: Any, stats: MaintenanceStats) -> None:
        retention_days = int(getattr(plugin_cfg, "mika_trace_retention_days", 7) or 7)
        retention_days = max(1, retention_days)
        max_rows = int(getattr(plugin_cfg, "mika_trace_max_rows", 20000) or 20000)
        max_rows = max(1, max_rows)

        cutoff = _now_wall() - retention_days * 86400
        db = await get_db()

        cursor = await db.execute(
            "DELETE FROM agent_traces WHERE created_at < ?",
            (float(cutoff),),
        )
        stats.traces_deleted_by_age += int(cursor.rowcount or 0)

        async with db.execute("SELECT COUNT(*) FROM agent_traces") as cur:
            row = await cur.fetchone()
        total = int(row[0] or 0) if row else 0
        if total > max_rows:
            to_delete = total - max_rows
            cursor = await db.execute(
                """
                DELETE FROM agent_traces
                WHERE request_id IN (
                    SELECT request_id FROM agent_traces
                    ORDER BY created_at ASC
                    LIMIT ?
                )
                """,
                (int(to_delete),),
            )
            stats.traces_deleted_by_rows += int(cursor.rowcount or 0)

        await db.commit()

    async def _prune_memory_embeddings(self, *, plugin_cfg: Any, stats: MaintenanceStats) -> None:
        try:
            from .memory_store import get_memory_store

            max_age_days = int(getattr(plugin_cfg, "mika_memory_max_age_days", 90) or 90)
            deleted = await get_memory_store().delete_old_memories(max_age_days=max(1, max_age_days))
            stats.memories_deleted += int(deleted or 0)
        except Exception:
            # best-effort
            return

    async def _vacuum_analyze(self, *, stats: MaintenanceStats) -> None:
        db = await get_db()
        try:
            # VACUUM cannot run inside a transaction.
            await db.commit()
            await db.execute("VACUUM")
            stats.vacuum_ok = True
        except Exception as exc:
            log.debug(f"db_maintenance vacuum failed: {exc}")
        try:
            await db.execute("ANALYZE")
            await db.commit()
            stats.analyze_ok = True
        except Exception as exc:
            log.debug(f"db_maintenance analyze failed: {exc}")


_service: Optional[DBMaintenanceService] = None


def get_db_maintenance_service() -> DBMaintenanceService:
    global _service
    if _service is None:
        _service = DBMaintenanceService()
    return _service


async def maybe_schedule_db_maintenance(*, plugin_cfg: Any, request_id: str = "") -> bool:
    """Best-effort public helper used by orchestrator."""

    try:
        return await get_db_maintenance_service().maybe_schedule(plugin_cfg=plugin_cfg, request_id=request_id)
    except Exception:
        return False

