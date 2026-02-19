"""工具启停状态持久化存储。"""

from __future__ import annotations

import asyncio
import time
from typing import Dict

from ..infra.logging import logger as log


class ToolStateStore:
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
                CREATE TABLE IF NOT EXISTS tool_states (
                    tool_name TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_tool_states_updated_at ON tool_states(updated_at)"
            )
            await db.commit()
            self._initialized = True

    async def load_states(self) -> Dict[str, bool]:
        await self.init_table()
        db = await self._get_db()
        async with db.execute(
            "SELECT tool_name, enabled FROM tool_states"
        ) as cursor:
            rows = await cursor.fetchall()
        result: Dict[str, bool] = {}
        for row in rows:
            try:
                name = str(row[0] or "").strip()
                if not name:
                    continue
                result[name] = bool(int(row[1] or 0))
            except Exception:
                continue
        return result

    async def set_enabled(self, tool_name: str, enabled: bool) -> None:
        await self.init_table()
        name = str(tool_name or "").strip()
        if not name:
            return
        db = await self._get_db()
        await db.execute(
            """
            INSERT INTO tool_states (tool_name, enabled, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(tool_name) DO UPDATE SET
                enabled = excluded.enabled,
                updated_at = excluded.updated_at
            """,
            (name, 1 if bool(enabled) else 0, time.time()),
        )
        await db.commit()

    async def remove_state(self, tool_name: str) -> None:
        await self.init_table()
        name = str(tool_name or "").strip()
        if not name:
            return
        db = await self._get_db()
        await db.execute("DELETE FROM tool_states WHERE tool_name = ?", (name,))
        await db.commit()


_tool_state_store: ToolStateStore | None = None


def get_tool_state_store() -> ToolStateStore:
    global _tool_state_store
    if _tool_state_store is None:
        _tool_state_store = ToolStateStore()
    return _tool_state_store


async def apply_persisted_tool_states(registry) -> int:
    store = get_tool_state_store()
    try:
        states = await store.load_states()
    except Exception as exc:
        log.warning(f"加载工具持久化状态失败: {exc}")
        return 0

    applied = 0
    for tool_name, enabled in states.items():
        if registry.set_enabled(tool_name, enabled):
            applied += 1
    if applied:
        log.info(f"已应用持久化工具状态: {applied} 个")
    return applied

