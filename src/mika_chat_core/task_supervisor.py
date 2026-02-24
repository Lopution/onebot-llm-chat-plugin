"""Managed background task supervisor.

Replaces bare ``asyncio.create_task`` calls with a centralized registry
that tracks, logs, and can cancel/await all outstanding background tasks.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Coroutine, Optional

log = logging.getLogger(__name__)


@dataclass
class TaskMeta:
    """Metadata attached to every supervised task."""

    name: str
    owner: str
    key: str = ""
    created_at: float = field(default_factory=time.monotonic)


class TaskSupervisor:
    """Registry and lifecycle manager for background asyncio tasks.

    Usage::

        supervisor = TaskSupervisor()
        supervisor.spawn(some_coro(), name="job", owner="startup")
        ...
        await supervisor.shutdown()
    """

    def __init__(self) -> None:
        self._tasks: dict[asyncio.Task[Any], TaskMeta] = {}

    # ------------------------------------------------------------------
    # spawn
    # ------------------------------------------------------------------

    def spawn(
        self,
        coro: Coroutine[Any, Any, Any],
        *,
        name: str,
        owner: str,
        key: str = "",
    ) -> asyncio.Task[Any]:
        """Create a tracked background task.

        Parameters
        ----------
        coro:
            The coroutine to run.
        name:
            Human-readable task name (for logs / metrics).
        owner:
            Logical owner (e.g. ``"startup"``, ``"chat_postprocess"``).
        key:
            Optional dedup/grouping key (e.g. ``"mem:<session_key>"``).
        """
        task_name = f"mika:{owner}:{name}"
        if key:
            task_name += f":{key}"
        task = asyncio.create_task(coro, name=task_name)
        meta = TaskMeta(name=name, owner=owner, key=key)
        self._tasks[task] = meta
        task.add_done_callback(self._on_done)
        return task

    # ------------------------------------------------------------------
    # cancel helpers
    # ------------------------------------------------------------------

    async def cancel_owner(
        self,
        owner: str,
        *,
        timeout_seconds: float = 5.0,
    ) -> int:
        """Cancel all tasks belonging to *owner*. Returns count cancelled."""
        targets = [t for t, m in self._tasks.items() if m.owner == owner and not t.done()]
        return await self._cancel_tasks(targets, timeout_seconds=timeout_seconds)

    async def cancel_all(self, *, timeout_seconds: float = 5.0) -> int:
        """Cancel every outstanding task. Returns count cancelled."""
        targets = [t for t in self._tasks if not t.done()]
        return await self._cancel_tasks(targets, timeout_seconds=timeout_seconds)

    # ------------------------------------------------------------------
    # shutdown
    # ------------------------------------------------------------------

    async def shutdown(self, *, timeout_seconds: float = 5.0) -> None:
        """Cancel all tasks and wait for them to finish."""
        pending = [t for t in self._tasks if not t.done()]
        if not pending:
            return
        log.info(f"TaskSupervisor: shutting down {len(pending)} background task(s)")
        await self._cancel_tasks(pending, timeout_seconds=timeout_seconds)

    # ------------------------------------------------------------------
    # introspection
    # ------------------------------------------------------------------

    def snapshot(self) -> list[dict[str, Any]]:
        """Return a list of task metadata dicts (for dashboards / debugging)."""
        result: list[dict[str, Any]] = []
        for task, meta in self._tasks.items():
            result.append(
                {
                    "name": meta.name,
                    "owner": meta.owner,
                    "key": meta.key,
                    "done": task.done(),
                    "cancelled": task.cancelled(),
                    "task_name": task.get_name(),
                    "age_seconds": round(time.monotonic() - meta.created_at, 2),
                }
            )
        return result

    @property
    def active_count(self) -> int:
        return sum(1 for t in self._tasks if not t.done())

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _on_done(self, task: asyncio.Task[Any]) -> None:
        meta = self._tasks.pop(task, None)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            label = f"{meta.owner}:{meta.name}" if meta else task.get_name()
            log.error(
                f"Background task failed: {label} | {type(exc).__name__}: {exc}",
                exc_info=exc,
            )

    async def _cancel_tasks(
        self,
        tasks: list[asyncio.Task[Any]],
        *,
        timeout_seconds: float,
    ) -> int:
        if not tasks:
            return 0
        for t in tasks:
            t.cancel()
        done, pending = await asyncio.wait(tasks, timeout=timeout_seconds)
        if pending:
            names = [t.get_name() for t in pending]
            log.warning(f"TaskSupervisor: {len(pending)} task(s) did not finish in time: {names}")
        return len(tasks)


__all__ = ["TaskMeta", "TaskSupervisor"]
