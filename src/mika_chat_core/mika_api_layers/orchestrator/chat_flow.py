"""Mika API - chat 编排辅助逻辑。"""

from __future__ import annotations

import asyncio
import random
import time
import uuid
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from ...errors import ServerError
from ...infra.logging import logger as log
from ..core.messages import PreSearchResult
from ..tools.tools import ToolLoopResult
from ...utils.prompt_context import get_prompt_context
from ...utils.prompt_loader import render_template


def prepare_chat_request(
    *,
    user_id: str,
    group_id: Optional[str],
    image_urls: Optional[List[str]],
    uuid_short_id_length: int,
    metrics_obj: Any,
) -> Tuple[str, float]:
    request_id = str(uuid.uuid4())[: max(1, int(uuid_short_id_length or 8))]
    start_time = time.time()
    metrics_obj.requests_total += 1
    log.info(
        f"[req:{request_id}] 开始处理请求 | "
        f"user={user_id} | group={group_id or 'private'} | "
        f"images={len(image_urls) if image_urls else 0}"
    )
    return request_id, start_time


async def log_context_diagnostics(
    *,
    user_id: str,
    group_id: Optional[str],
    request_id: str,
    plugin_cfg: Any,
    get_context_async: Callable[[str, Optional[str]], Awaitable[List[Dict[str, Any]]]],
    context_diagnostic_tail_count: int,
    history_message_preview_chars: int,
) -> None:
    trace_enabled = bool(getattr(plugin_cfg, "mika_context_trace_enabled", False))
    if not trace_enabled:
        return

    sample_rate = float(getattr(plugin_cfg, "mika_context_trace_sample_rate", 1.0) or 1.0)
    sample_rate = min(1.0, max(0.0, sample_rate))
    if sample_rate < 1.0 and random.random() > sample_rate:
        return

    history = await get_context_async(user_id, group_id)
    total_history_chars = sum(len(str(m.get("content", ""))) for m in history)
    log.info(
        f"[req:{request_id}] context_trace | phase=context_build | "
        f"history_count={len(history)} | "
        f"total_chars={total_history_chars} | "
        f"sample_rate={sample_rate:.2f}"
    )

    if history:
        tail = history[-max(1, int(context_diagnostic_tail_count or 1)) :]
        for i, msg in enumerate(tail):
            role = msg.get("role", "unknown")
            content = str(msg.get("content", ""))
            preview_chars = max(1, int(history_message_preview_chars or 80))
            content_preview = content[:preview_chars].replace("\n", " ")
            if len(content) > preview_chars:
                content_preview += "..."
            log.debug(
                f"[req:{request_id}] 历史[{len(history)-len(tail)+i}] | "
                f"role={role} | len={len(content)} | "
                f"preview={content_preview}"
            )


def log_search_result_status(search_result: str, request_id: str) -> None:
    if search_result:
        log.debug(f"[req:{request_id}] 搜索结果已注入 | length={len(search_result)}")
    else:
        log.debug(f"[req:{request_id}] 无搜索结果注入")


def resolve_time_block() -> str:
    hour = datetime.now().hour
    if 5 <= hour < 11:
        return "早上"
    if 11 <= hour < 13:
        return "中午"
    if 13 <= hour < 18:
        return "下午"
    if 18 <= hour < 23:
        return "晚上"
    return "深夜"


async def build_prompt_context_values(
    *,
    message: str,
    user_id: str,
    group_id: Optional[str],
    plugin_cfg: Any,
    memory_session_key: Callable[[str, Optional[str]], str],
    has_user_profile: bool,
    use_persistent: bool,
    get_user_profile_store: Any,
) -> Dict[str, Any]:
    now = datetime.now()
    context: Dict[str, Any] = {
        "master_name": str(getattr(plugin_cfg, "mika_master_name", "Sensei") or "Sensei"),
        "current_date": now.strftime("%Y年%m月%d日"),
        "current_time": now.strftime("%Y年%m月%d日 %H:%M"),
        "time_block": resolve_time_block(),
        "memory_snippets": "",
        "knowledge_context": "",
        "user_profile": "",
        "group_participants": "",
        "session_id": memory_session_key(user_id, group_id),
        "user_id": str(user_id or ""),
        "group_id": str(group_id or ""),
        "message": str(message or ""),
    }

    if has_user_profile and use_persistent and get_user_profile_store is not None:
        try:
            profile_store = get_user_profile_store()
            summary = await profile_store.get_profile_summary(str(user_id or ""))
            if summary:
                context["user_profile"] = str(summary)
        except Exception:
            pass

    return context


def render_system_prompt_with_context(*, system_prompt: str) -> str:
    context = get_prompt_context()
    if not context:
        return system_prompt
    rendered = render_template(system_prompt, context)
    if rendered:
        return rendered
    return system_prompt


def coerce_pre_search_result(
    *,
    raw_result: Any,
    message: str,
    decision: str = "compat",
    plugin_cfg: Any,
) -> PreSearchResult:
    from ...utils.search_engine import normalize_search_query

    bot_names = [
        getattr(plugin_cfg, "mika_bot_display_name", "") or "",
        getattr(plugin_cfg, "mika_master_name", "") or "",
    ]
    normalized_query = normalize_search_query(str(message or ""), bot_names=bot_names)

    if isinstance(raw_result, PreSearchResult):
        if not raw_result.normalized_query and normalized_query:
            raw_result.normalized_query = normalized_query
        return raw_result

    if isinstance(raw_result, dict):
        return PreSearchResult(
            search_result=str(raw_result.get("search_result") or ""),
            normalized_query=str(raw_result.get("normalized_query") or normalized_query),
            presearch_hit=bool(raw_result.get("presearch_hit")),
            allow_tool_refine=bool(raw_result.get("allow_tool_refine")),
            result_count=int(raw_result.get("result_count") or 0),
            refine_rounds_used=int(raw_result.get("refine_rounds_used") or 0),
            blocked_duplicate_total=int(raw_result.get("blocked_duplicate_total") or 0),
            decision=str(raw_result.get("decision") or decision),
        )

    search_result = str(raw_result or "")
    return PreSearchResult(
        search_result=search_result,
        normalized_query=normalized_query,
        presearch_hit=bool(search_result.strip()),
        allow_tool_refine=False,
        result_count=0,
        decision=decision,
    )


def log_search_decision(request_id: str, search_state: PreSearchResult, *, phase: str) -> None:
    log.info(
        f"[req:{request_id}] search_decision phase={phase} "
        f"presearch_hit={1 if search_state.presearch_hit else 0} "
        f"allow_refine={1 if search_state.allow_tool_refine else 0} "
        f"refine_used={search_state.refine_rounds_used} "
        f"blocked_duplicate={search_state.blocked_duplicate_total} "
        f"result_count={search_state.result_count}"
    )


def log_request_messages(
    *,
    messages: List[Dict[str, Any]],
    api_content: Any,
    request_id: str,
    api_content_debug_min_chars: int,
    api_content_debug_preview_chars: int,
) -> None:
    log.debug(f"[req:{request_id}] 发送消息数量: {len(messages)}")
    if isinstance(api_content, str) and len(api_content) > api_content_debug_min_chars:
        log.debug(
            f"[req:{request_id}] API消息内容（前{api_content_debug_preview_chars}字）:\n"
            f"{api_content[:api_content_debug_preview_chars]}..."
        )


async def handle_server_error_retry(
    *,
    error: ServerError,
    message: str,
    user_id: str,
    group_id: Optional[str],
    image_urls: Optional[List[str]],
    enable_tools: bool,
    retry_count: int,
    message_id: Optional[str],
    system_injection: Optional[str],
    context_level: int,
    history_override: Optional[List[Dict[str, Any]]],
    search_result: Optional[str],
    server_error_retry_backoff_base: int,
    server_error_retry_exponent_offset: int,
    chat_caller: Callable[..., Awaitable[str]],
) -> Optional[str]:
    if retry_count > 0 and "will retry" in str(error.message):
        wait_time = int(server_error_retry_backoff_base) ** (
            int(server_error_retry_exponent_offset) - int(retry_count)
        )
        await asyncio.sleep(wait_time)
        return await chat_caller(
            message=message,
            user_id=user_id,
            group_id=group_id,
            image_urls=image_urls,
            enable_tools=enable_tools,
            retry_count=retry_count - 1,
            message_id=message_id,
            system_injection=system_injection,
            context_level=context_level,
            history_override=history_override,
            search_result_override=search_result,
        )
    return None


async def resolve_reply(
    *,
    messages: List[Dict[str, Any]],
    assistant_message: Dict[str, Any],
    tool_calls: List[Dict[str, Any]],
    api_key: str,
    group_id: Optional[str],
    request_id: str,
    enable_tools: bool,
    tools: Optional[List[Dict[str, Any]]],
    search_state: Optional[PreSearchResult],
    session_key: Optional[str],
    handle_tool_calls: Callable[..., Awaitable[str | ToolLoopResult]],
    activate_tool_schema_full_fallback: Callable[..., None],
) -> Tuple[str, List[Dict[str, Any]]]:
    if tool_calls and enable_tools:
        result = await handle_tool_calls(
            messages,
            assistant_message,
            tool_calls,
            api_key,
            group_id,
            request_id,
            tools,
            search_state=search_state,
            return_trace=True,
        )
        if isinstance(result, ToolLoopResult):
            if (
                bool(result.schema_mismatch_suspected)
                and isinstance(session_key, str)
                and session_key.strip()
            ):
                activate_tool_schema_full_fallback(
                    session_key=session_key.strip(),
                    request_id=request_id,
                    reason="tool_schema_mismatch_suspected",
                )
            return result.reply, result.trace_messages
        return str(result), []
    return assistant_message.get("content") or "", []


def log_raw_model_reply(
    *,
    reply: str,
    request_id: str,
    raw_model_reply_preview_chars: int,
) -> None:
    preview_chars = max(1, int(raw_model_reply_preview_chars or 300))
    log.debug(
        f"[req:{request_id}] 模型原始回复（前{preview_chars}字）:\n"
        f"{reply[:preview_chars]}..."
        if len(reply) > preview_chars
        else f"[req:{request_id}] 模型原始回复:\n{reply}"
    )


def log_request_success(
    *,
    request_id: str,
    start_time: float,
    reply: str,
    tool_calls: List[Dict[str, Any]],
) -> None:
    total_elapsed = time.time() - start_time
    tool_info = f" | tools_called={len(tool_calls)}" if tool_calls else ""
    log.success(
        f"[req:{request_id}] 请求完成 | "
        f"reply_len={len(reply)}{tool_info} | "
        f"total_time={total_elapsed:.2f}s"
    )
