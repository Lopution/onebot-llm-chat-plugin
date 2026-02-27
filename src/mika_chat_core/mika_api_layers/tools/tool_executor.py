"""Tool execution helpers: TTL cache + in-flight de-duplication.

Design goals:
- Best-effort: never change tool semantics when caching is disabled.
- Safe-by-default: only enable TTL caching when a stable `session_key` is provided.
- In-flight de-dupe always works per-key to avoid duplicate concurrent calls.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional, Tuple


def _now() -> float:
    return time.monotonic()


def normalize_args(args: Any) -> str:
    try:
        return json.dumps(args, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except Exception:
        return str(args)


def is_cacheable_tool(tool_name: str) -> bool:
    """Return True for known idempotent tools (read-only / query-like).

    Avoid caching arbitrary dynamic tools (e.g. MCP) which might have side effects.
    """

    name = str(tool_name or "").strip()
    return name in {
        "web_search",
        "search_group_history",
        "search_knowledge",
        "fetch_history_images",
    }


@dataclass
class _CacheEntry:
    value: str
    expires_at: float


class ToolExecutor:
    def __init__(self) -> None:
        self._cache: "OrderedDict[str, _CacheEntry]" = OrderedDict()
        self._inflight: dict[str, asyncio.Future[str]] = {}
        self._lock = asyncio.Lock()

    async def execute(
        self,
        *,
        cache_enabled: bool,
        cache_ttl_seconds: float,
        cache_max_entries: int,
        cache_scope: str,
        tool_name: str,
        args: Any,
        run: Callable[[], Awaitable[str]],
    ) -> Tuple[str, bool, bool]:
        """Execute a tool handler with optional caching.

        Returns:
        - result: str
        - cache_hit: bool
        - inflight_deduped: bool (awaited an existing in-flight execution)
        """

        scope = str(cache_scope or "").strip()
        name = str(tool_name or "").strip()
        normalized_args = normalize_args(args)
        key = f"{scope}|{name}|{normalized_args}"

        ttl = max(0.0, float(cache_ttl_seconds or 0.0))
        max_entries = max(0, int(cache_max_entries or 0))
        ttl_cache_on = bool(cache_enabled) and ttl > 0 and max_entries > 0 and bool(scope)

        now = _now()
        if ttl_cache_on:
            async with self._lock:
                entry = self._cache.get(key)
                if entry is not None:
                    if entry.expires_at > now:
                        # LRU: refresh entry position.
                        self._cache.move_to_end(key)
                        return entry.value, True, False
                    # Expired.
                    self._cache.pop(key, None)

        async with self._lock:
            existing = self._inflight.get(key)
            if existing is not None:
                fut = existing
                inflight_deduped = True
            else:
                fut = asyncio.get_running_loop().create_future()
                self._inflight[key] = fut
                inflight_deduped = False

        if inflight_deduped:
            # Propagate any error from the primary execution.
            return await fut, False, True

        try:
            result = await run()
        except Exception as exc:
            try:
                fut.set_exception(exc)
            finally:
                async with self._lock:
                    self._inflight.pop(key, None)
            raise

        try:
            fut.set_result(str(result or ""))
        finally:
            async with self._lock:
                self._inflight.pop(key, None)

        if ttl_cache_on and is_cacheable_tool(name):
            expires_at = now + ttl
            async with self._lock:
                self._cache[key] = _CacheEntry(value=str(result or ""), expires_at=float(expires_at))
                self._cache.move_to_end(key)
                # Prune: drop expired first, then LRU.
                cutoff = _now()
                expired_keys = [k for k, v in self._cache.items() if v.expires_at <= cutoff]
                for k in expired_keys:
                    self._cache.pop(k, None)
                while len(self._cache) > max_entries:
                    self._cache.popitem(last=False)

        return str(result or ""), False, False


_executor: Optional[ToolExecutor] = None


def get_tool_executor() -> ToolExecutor:
    global _executor
    if _executor is None:
        _executor = ToolExecutor()
    return _executor

