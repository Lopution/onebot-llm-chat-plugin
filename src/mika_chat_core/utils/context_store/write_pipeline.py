"""Write-path helpers for SQLiteContextStore."""

from __future__ import annotations

import copy
import json
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

from ..context_schema import normalize_content


@dataclass
class AddMessageDeps:
    get_context_caller: Callable[[str, Optional[str]], Awaitable[List[Dict[str, Any]]]]
    build_summary_for_messages_caller: Callable[..., Awaitable[str]]
    context_manager: Any
    summary_enabled: bool
    summary_trigger_turns: int
    summary_max_chars: int
    max_context: int
    context_message_multiplier: int
    compress_context_caller: Callable[[List[Dict[str, Any]], str], Awaitable[List[Dict[str, Any]]]]
    prepare_snapshot_messages_caller: Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]]
    cache_setter: Callable[[str, List[Dict[str, Any]]], None]
    cache_deleter: Callable[[str], None]
    get_db_fn: Callable[[], Awaitable[Any]]
    log_obj: Any
    context_write_error_cls: type[Exception]


def build_message_record(
    *,
    role: str,
    content: Any,
    message_id: Optional[str],
    timestamp: Optional[float],
    tool_calls: Optional[List[Dict[str, Any]]],
    tool_call_id: Optional[str],
) -> tuple[Dict[str, Any], Any, float]:
    normalized_content = normalize_content(content)
    message: Dict[str, Any] = {
        "role": role,
        "content": normalized_content,
    }
    if message_id:
        message["message_id"] = str(message_id)
    if tool_calls and role == "assistant":
        message["tool_calls"] = tool_calls
    if tool_call_id and role == "tool":
        message["tool_call_id"] = str(tool_call_id)

    effective_timestamp = float(timestamp if timestamp is not None else time.time())
    message["timestamp"] = effective_timestamp
    return message, normalized_content, effective_timestamp


def _build_archive_content(normalized_content: Any) -> str:
    if isinstance(normalized_content, (list, dict)):
        return json.dumps(normalized_content, ensure_ascii=False)
    return str(normalized_content)


async def _process_messages(
    *,
    deps: AddMessageDeps,
    messages: List[Dict[str, Any]],
    context_key: str,
) -> List[Dict[str, Any]]:
    if deps.summary_enabled:

        async def _summary_builder(old_messages: List[Dict[str, Any]]) -> str:
            return await deps.build_summary_for_messages_caller(
                context_key=context_key,
                messages=old_messages,
            )

        messages = await deps.context_manager.process_with_summary(
            messages,
            summary_builder=_summary_builder,
            summary_trigger_turns=deps.summary_trigger_turns,
            summary_max_chars=deps.summary_max_chars,
        )
    else:
        messages = deps.context_manager.process(messages)

    if len(messages) > deps.max_context * deps.context_message_multiplier:
        messages = await deps.compress_context_caller(messages, context_key)

    return messages


async def _persist_snapshot_and_archive(
    *,
    deps: AddMessageDeps,
    context_key: str,
    user_id: str,
    role: str,
    message_id: Optional[str],
    timestamp: float,
    normalized_content: Any,
    snapshot_messages: List[Dict[str, Any]],
) -> None:
    db = await deps.get_db_fn()
    await db.execute("BEGIN IMMEDIATE")
    try:
        await db.execute(
            """
            INSERT INTO contexts (context_key, messages, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(context_key) DO UPDATE SET
                messages = excluded.messages,
                updated_at = CURRENT_TIMESTAMP
            """,
            (context_key, json.dumps(snapshot_messages, ensure_ascii=False)),
        )

        await db.execute(
            """
            INSERT INTO message_archive (context_key, user_id, role, content, message_id, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                context_key,
                user_id,
                role,
                _build_archive_content(normalized_content),
                message_id,
                timestamp,
            ),
        )
        await db.commit()
        deps.log_obj.debug(f"上下文已保存: {context_key} | 消息数={len(snapshot_messages)}")
    except Exception:
        await db.rollback()
        raise


async def add_message_flow(
    *,
    deps: AddMessageDeps,
    context_key: str,
    user_id: str,
    role: str,
    content: Any,
    group_id: Optional[str],
    message_id: Optional[str],
    timestamp: Optional[float],
    tool_calls: Optional[List[Dict[str, Any]]],
    tool_call_id: Optional[str],
) -> None:
    messages = copy.deepcopy(await deps.get_context_caller(user_id, group_id))
    message, normalized_content, effective_timestamp = build_message_record(
        role=role,
        content=content,
        message_id=message_id,
        timestamp=timestamp,
        tool_calls=tool_calls,
        tool_call_id=tool_call_id,
    )
    messages.append(message)

    try:
        messages = await _process_messages(
            deps=deps,
            messages=messages,
            context_key=context_key,
        )
        snapshot_messages = deps.prepare_snapshot_messages_caller(messages)
        await _persist_snapshot_and_archive(
            deps=deps,
            context_key=context_key,
            user_id=user_id,
            role=role,
            message_id=message_id,
            timestamp=effective_timestamp,
            normalized_content=normalized_content,
            snapshot_messages=snapshot_messages,
        )
        deps.cache_setter(context_key, snapshot_messages)
    except Exception as exc:
        deps.cache_deleter(context_key)
        deps.log_obj.error(f"保存上下文失败: {exc}", exc_info=True)
        raise deps.context_write_error_cls(
            f"context write failed | key={context_key} | role={role} | message_id={message_id or ''}"
        ) from exc
