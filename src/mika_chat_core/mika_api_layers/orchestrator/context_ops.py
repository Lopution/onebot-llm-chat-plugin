"""Mika API - 上下文读写辅助逻辑。"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Union


def get_context_key(user_id: str, group_id: Optional[str] = None) -> tuple:
    if group_id:
        return (group_id, "GROUP_CHAT")
    return ("PRIVATE_CHAT", user_id)


def append_memory_context_message(
    *,
    contexts: Dict[tuple, List[Dict[str, Any]]],
    max_context: int,
    context_history_multiplier: int,
    user_id: str,
    role: str,
    content: Union[str, List[Dict[str, Any]]],
    group_id: Optional[str],
    timestamp: float,
    message_id: Optional[str],
    tool_calls: Optional[List[Dict[str, Any]]] = None,
    tool_call_id: Optional[str] = None,
) -> None:
    key = get_context_key(user_id, group_id)
    msg = {"role": role, "content": content, "timestamp": timestamp}
    if message_id:
        msg["message_id"] = str(message_id)
    if tool_calls and role == "assistant":
        msg["tool_calls"] = tool_calls
    if tool_call_id and role == "tool":
        msg["tool_call_id"] = str(tool_call_id)
    contexts[key].append(msg)

    max_history_messages = int(max_context) * max(1, int(context_history_multiplier or 1))
    if len(contexts[key]) > max_history_messages:
        contexts[key] = contexts[key][-max_history_messages:]


async def get_context_async(
    *,
    use_persistent: bool,
    context_store: Any,
    contexts: Dict[tuple, List[Dict[str, Any]]],
    user_id: str,
    group_id: Optional[str],
) -> List[Dict[str, Any]]:
    if use_persistent and context_store:
        return await context_store.get_context(user_id, group_id)
    return contexts[get_context_key(user_id, group_id)]


async def add_message_with_fallback(
    *,
    use_persistent: bool,
    context_store: Any,
    context_store_write_error_cls: Any,
    contexts: Dict[tuple, List[Dict[str, Any]]],
    max_context: int,
    context_history_multiplier: int,
    user_id: str,
    role: str,
    content: Union[str, List[Dict[str, Any]]],
    group_id: Optional[str],
    message_id: Optional[str],
    timestamp: Optional[float],
    tool_calls: Optional[List[Dict[str, Any]]],
    tool_call_id: Optional[str],
    log_obj: Any,
) -> None:
    current_time = float(timestamp if timestamp is not None else time.time())
    if use_persistent and context_store:
        try:
            await context_store.add_message(
                user_id,
                role,
                content,
                group_id,
                message_id,
                timestamp=current_time,
                tool_calls=tool_calls,
                tool_call_id=tool_call_id,
            )
            return
        except context_store_write_error_cls as exc:  # type: ignore[misc]
            log_obj.warning(f"持久化上下文写入失败，降级到内存上下文 | error={exc}")

    append_memory_context_message(
        contexts=contexts,
        max_context=max_context,
        context_history_multiplier=context_history_multiplier,
        user_id=user_id,
        role=role,
        content=content,
        group_id=group_id,
        timestamp=current_time,
        message_id=message_id,
        tool_calls=tool_calls,
        tool_call_id=tool_call_id,
    )


def get_context_sync(
    *,
    use_persistent: bool,
    contexts: Dict[tuple, List[Dict[str, Any]]],
    user_id: str,
    group_id: Optional[str],
    log_obj: Any,
) -> List[Dict[str, Any]]:
    if use_persistent:
        log_obj.warning("_get_context 在持久化模式下不可用，测试应使用 get_context")
        return []
    return contexts[get_context_key(user_id, group_id)]


def add_context_sync(
    *,
    use_persistent: bool,
    contexts: Dict[tuple, List[Dict[str, Any]]],
    max_context: int,
    context_history_multiplier: int,
    user_id: str,
    role: str,
    content: Union[str, List[Dict[str, Any]]],
    group_id: Optional[str],
    message_id: Optional[str],
    log_obj: Any,
) -> None:
    if use_persistent:
        log_obj.warning("_add_to_context 在持久化模式下不可用，测试应使用 add_message")
        return
    append_memory_context_message(
        contexts=contexts,
        max_context=max_context,
        context_history_multiplier=context_history_multiplier,
        user_id=user_id,
        role=role,
        content=content,
        group_id=group_id,
        timestamp=time.time(),
        message_id=message_id,
    )


async def clear_context_async(
    *,
    use_persistent: bool,
    context_store: Any,
    contexts: Dict[tuple, List[Dict[str, Any]]],
    user_id: str,
    group_id: Optional[str],
) -> None:
    if use_persistent and context_store:
        await context_store.clear_context(user_id, group_id)
        return
    contexts[get_context_key(user_id, group_id)] = []


def clear_context_sync(
    *,
    use_persistent: bool,
    contexts: Dict[tuple, List[Dict[str, Any]]],
    user_id: str,
    group_id: Optional[str],
    log_obj: Any,
) -> None:
    if use_persistent:
        log_obj.warning("在持久化模式下使用同步 clear_context")
        return
    contexts[get_context_key(user_id, group_id)] = []

