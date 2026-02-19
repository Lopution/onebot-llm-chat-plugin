"""Agent lifecycle hook helpers.

支持在不侵入主流程的前提下，为关键执行节点注入观测/审计逻辑。
"""

from __future__ import annotations

import inspect
from typing import Any, Protocol, runtime_checkable

from .infra.logging import logger as log
from .runtime import get_agent_run_hooks


@runtime_checkable
class AgentRunHooks(Protocol):
    async def on_before_llm(self, payload: dict[str, Any]) -> None:
        ...

    async def on_after_llm(self, payload: dict[str, Any]) -> None:
        ...

    async def on_tool_start(self, payload: dict[str, Any]) -> None:
        ...

    async def on_tool_end(self, payload: dict[str, Any]) -> None:
        ...


def _resolve_hook_callable(hooks: Any, event_name: str) -> Any:
    if hooks is None:
        return None
    if isinstance(hooks, dict):
        return hooks.get(event_name)
    return getattr(hooks, event_name, None)


async def emit_agent_hook(event_name: str, payload: dict[str, Any]) -> None:
    """调用已注册的 agent hook，异常仅记录日志，不打断主流程。"""
    hooks = get_agent_run_hooks()
    callback = _resolve_hook_callable(hooks, event_name)
    if not callable(callback):
        return

    safe_payload = dict(payload or {})
    try:
        result = callback(safe_payload)
        if inspect.isawaitable(result):
            await result
    except Exception as exc:
        log.warning(f"[agent-hook] {event_name} 执行失败: {exc}")


__all__ = ["AgentRunHooks", "emit_agent_hook"]
