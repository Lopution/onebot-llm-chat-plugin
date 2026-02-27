"""Mika API - 工具调用处理逻辑（门面层）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from ...agent_hooks import emit_agent_hook
from ...config import plugin_config
from ...infra.logging import logger as log
from ...metrics import metrics
from .tool_loop_flow import (
    handle_tool_calls_flow as service_handle_tool_calls_flow,
    is_duplicate_search_query as service_is_duplicate_search_query,
)
from ...tools_registry import build_effective_allowlist


@dataclass
class ToolLoopResult:
    """工具循环结果。"""

    reply: str
    trace_messages: List[Dict[str, Any]]
    schema_mismatch_suspected: bool = False


def _is_duplicate_search_query(base_query: str, candidate_query: str) -> bool:
    return service_is_duplicate_search_query(base_query, candidate_query)


async def handle_tool_calls(
    *,
    messages: List[Dict[str, Any]],
    assistant_message: Dict[str, Any],
    tool_calls: List[Dict[str, Any]],
    api_key: str,
    group_id: Optional[str],
    request_id: str,
    session_key: Optional[str] = None,
    tool_handlers: Dict[str, Callable],
    model: str,
    base_url: str,
    http_client,
    tools: Optional[List[Dict[str, Any]]] = None,
    search_state: Optional[Any] = None,
    return_trace: bool = False,
) -> str | ToolLoopResult:
    """处理工具调用并返回最终回复（支持多轮 tool loop）。"""
    result = await service_handle_tool_calls_flow(
        messages=messages,
        assistant_message=assistant_message,
        tool_calls=tool_calls,
        api_key=api_key,
        group_id=group_id,
        request_id=request_id,
        session_key=session_key,
        tool_handlers=tool_handlers,
        model=model,
        base_url=base_url,
        http_client=http_client,
        tools=tools,
        search_state=search_state,
        return_trace=return_trace,
        plugin_cfg=plugin_config,
        log_obj=log,
        metrics_obj=metrics,
        emit_agent_hook_fn=emit_agent_hook,
        build_effective_allowlist_fn=build_effective_allowlist,
        is_duplicate_search_query_fn=_is_duplicate_search_query,
    )
    if not return_trace:
        return str(result or "")
    payload = result if isinstance(result, dict) else {"reply": str(result or ""), "trace_messages": []}
    return ToolLoopResult(
        reply=str(payload.get("reply") or ""),
        trace_messages=list(payload.get("trace_messages") or []),
        schema_mismatch_suspected=bool(payload.get("schema_mismatch_suspected", False)),
    )
