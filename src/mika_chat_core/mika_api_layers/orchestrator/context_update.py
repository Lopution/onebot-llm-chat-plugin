"""Mika API - 上下文写入与记忆节流逻辑。"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List, MutableMapping, Optional, Union


async def update_context(
    *,
    user_id: str,
    group_id: Optional[str],
    current_content: Union[str, List[Dict[str, Any]]],
    reply: str,
    user_message_id: Optional[str],
    tool_trace: Optional[List[Dict[str, Any]]],
    character_name: str,
    add_to_context_async: Callable[..., Awaitable[None]],
) -> None:
    await add_to_context_async(user_id, "user", current_content, group_id, user_message_id)

    for trace_msg in tool_trace or []:
        if not isinstance(trace_msg, dict):
            continue
        trace_role = str(trace_msg.get("role") or "").strip().lower()
        if trace_role not in {"assistant", "tool"}:
            continue
        trace_content: Union[str, List[Dict[str, Any]]] = trace_msg.get("content") or ""
        tool_calls = trace_msg.get("tool_calls")
        tool_call_id = trace_msg.get("tool_call_id")
        if (
            trace_role == "assistant"
            and not tool_calls
            and isinstance(trace_content, str)
            and trace_content.strip() == reply.strip()
        ):
            continue
        await add_to_context_async(
            user_id,
            trace_role,
            trace_content,
            group_id,
            tool_calls=tool_calls if isinstance(tool_calls, list) else None,
            tool_call_id=str(tool_call_id) if tool_call_id else None,
        )

    if group_id:
        formatted_reply = f"[{character_name}]: {reply}"
    else:
        formatted_reply = reply

    await add_to_context_async(user_id, "assistant", formatted_reply, group_id)


def memory_session_key(user_id: str, group_id: Optional[str]) -> str:
    if group_id:
        return f"group:{group_id}"
    return f"private:{user_id}"


def should_extract_memory(
    *,
    counters: MutableMapping[str, int],
    session_key: str,
    interval: int,
    counter_max_size: int,
) -> bool:
    interval_value = max(1, int(interval or 1))
    count = int(counters.get(session_key, 0)) + 1
    counters[session_key] = count

    if len(counters) > counter_max_size:
        for key in list(counters.keys())[: counter_max_size // 4]:
            counters.pop(key, None)

    return interval_value <= 1 or (count % interval_value == 0)
