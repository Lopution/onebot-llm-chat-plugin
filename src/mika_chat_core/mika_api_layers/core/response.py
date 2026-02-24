"""Response/error handling helpers extracted from MikaClient.

保持原行为不变，仅将大段实现迁移出 MikaClient，降低 God Class 体积。
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

import httpx

from ...errors import AuthenticationError, MikaAPIError, RateLimitError, ServerError
from ...infra.logging import logger as log


async def handle_empty_reply_retry(
    *,
    request_id: str,
    start_time: float,
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
    search_result: str,
    plugin_cfg: Any,
    metrics_obj: Any,
    max_context_degradation_level: int,
    empty_reply_retry_delay_seconds: float,
    chat_caller: Callable[..., Awaitable[str]],
) -> Optional[str]:
    """处理空回复的上下文降级重试。"""
    total_elapsed = time.time() - start_time
    log.warning(
        f"[req:{request_id}] 空回复 (retry={retry_count}, context_level={context_level}) | "
        f"total_time={total_elapsed:.2f}s"
    )

    if not bool(getattr(plugin_cfg, "mika_empty_reply_context_degrade_enabled", False)):
        log.warning(f"[req:{request_id}] 空回复不触发业务级上下文降级（配置关闭）")
        return None

    max_degrade_level = int(
        getattr(
            plugin_cfg,
            "mika_empty_reply_context_degrade_max_level",
            max_context_degradation_level,
        )
        or max_context_degradation_level
    )
    if max_degrade_level < 0:
        max_degrade_level = 0

    # Level 0 -> Level 1 (20条) -> Level 2 (5条) -> 放弃
    next_context_level = context_level + 1
    if next_context_level <= max_degrade_level:
        await asyncio.sleep(float(empty_reply_retry_delay_seconds))
        metrics_obj.api_empty_reply_reason_total["context_degrade"] = (
            int(metrics_obj.api_empty_reply_reason_total.get("context_degrade", 0) or 0) + 1
        )
        log.warning(
            f"[req:{request_id}] 触发上下文降级重试 | "
            f"Level {context_level} -> Level {next_context_level} (max={max_degrade_level})"
        )
        return await chat_caller(
            message=message,
            user_id=user_id,
            group_id=group_id,
            image_urls=image_urls,
            enable_tools=enable_tools,
            retry_count=retry_count,
            message_id=message_id,
            system_injection=system_injection,
            context_level=next_context_level,
            history_override=history_override,
            search_result_override=search_result,
        )

    return None


def process_response(
    *,
    reply: str,
    request_id: str,
    clean_thinking_markers: Callable[[str], str],
) -> str:
    """清理响应文本（思考标记/角色标签/Markdown/空白）。"""
    original_len = len(reply)
    reply = clean_thinking_markers(reply)

    # ==================== Markdown/LaTeX 格式清理 ====================
    reply = re.sub(r"\*\*(.+?)\*\*", r"\1", reply)
    reply = re.sub(r"__(.+?)__", r"\1", reply)
    reply = re.sub(r"(?<!\*)\*([^\s*][^*]*?)\*(?!\*)", r"\1", reply)
    reply = re.sub(r"(?<!_)_([^\s_][^_]*?)_(?!_)", r"\1", reply)
    reply = re.sub(r"`([^`]+)`", r"\1", reply)
    reply = re.sub(r"```(?:\w+)?\n?(.*?)\n?```", r"\1", reply, flags=re.DOTALL)
    reply = re.sub(r"(?m)^(\d+)\.\s+", r"\1、", reply)
    reply = re.sub(r"(?m)^[\-\*]\s+", "· ", reply)
    reply = re.sub(r"(?m)^#{1,6}\s*(.+)$", r"【\1】", reply)
    reply = re.sub(r"(?m)^>\s*(.+)$", r"「\1」", reply)
    reply = re.sub(r"\$\$(.+?)\$\$", r"\1", reply, flags=re.DOTALL)
    reply = re.sub(r"\$([^$]+)\$", r"\1", reply)
    reply = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", reply)

    # ==================== 用户昵称标签清理 ====================
    zero_width_pattern = r"[\u200B-\u200F\u2060-\u206F\uFEFF\u202A-\u202E]"
    reply_cleaned = re.sub(zero_width_pattern, "", reply)
    reply_cleaned = re.sub(r"\[[^\]]*?\([^)]{1,64}\)\]:?\s*", "", reply_cleaned)
    reply_cleaned = re.sub(
        r"\[(Mika|Sensei|★Sensei|⭐Sensei|User|未花|圣园未花)\]:?\s*",
        "",
        reply_cleaned,
        flags=re.IGNORECASE,
    )
    reply_cleaned = re.sub(r"(?m)^\[[^\]]{1,20}\]:\s*", "", reply_cleaned)
    reply_cleaned = re.sub(
        r"\[(?=[^\]]*[♡★☆⭐♪♫✨💕🎵])[^\]]{1,30}\]",
        "",
        reply_cleaned,
    )
    reply_cleaned = re.sub(
        r"\[(?:"
        r"现在|刚才|刚刚|之前|稍后|马上|"
        r"几分钟前|半小时前|约?\d+(?:小时|天|分钟)前|1-2小时前|"
        r"[^\]]{1,15}の[^\]]{1,15}"
        r")\]\s*",
        "",
        reply_cleaned,
    )
    reply_cleaned = re.sub(r"^(?:\[[^\]]{1,10}\]\s*)+", "", reply_cleaned)
    reply_cleaned = re.sub(r"\[(?:搜索中|思考中|生成中|加载中|处理中)\]", "", reply_cleaned)

    reply = reply_cleaned
    reply = reply.strip()
    reply = re.sub(r"^[\s\u3000]+", "", reply)

    if len(reply) != original_len:
        log.debug(f"[req:{request_id}] 已清理格式/标签 | 原长度={original_len} | 清理后={len(reply)}")

    return reply


def handle_error(
    *,
    error: Exception,
    request_id: str,
    start_time: float,
    get_error_message: Callable[[str], str],
    error_response_body_preview_chars: int,
) -> str:
    """统一错误处理并映射为用户可读提示。"""
    total_elapsed = time.time() - start_time

    if isinstance(error, httpx.TimeoutException):
        log.error(f"[req:{request_id}] 超时错误 | error={str(error)} | total_time={total_elapsed:.2f}s")
        return get_error_message("timeout")

    if isinstance(error, RateLimitError):
        log.warning(
            f"[req:{request_id}] 限流错误 | retry_after={error.retry_after}s | total_time={total_elapsed:.2f}s"
        )
        return get_error_message("rate_limit")

    if isinstance(error, AuthenticationError):
        log.error(
            f"[req:{request_id}] 认证错误 | status={error.status_code} | total_time={total_elapsed:.2f}s"
        )
        return get_error_message("auth_error")

    if isinstance(error, ServerError):
        log.error(
            f"[req:{request_id}] 服务端错误 | status={error.status_code} | total_time={total_elapsed:.2f}s"
        )
        return get_error_message("server_error")

    if isinstance(error, MikaAPIError):
        log.error(f"[req:{request_id}] API 错误 | status={error.status_code} | total_time={total_elapsed:.2f}s")
        if "content filtered" in str(error.message).lower():
            return get_error_message("content_filter")
        return get_error_message("api_error")

    if isinstance(error, (httpx.ConnectError, httpx.NetworkError)):
        log.warning(
            f"[req:{request_id}] 网络连接错误 | error={str(error)} | total_time={total_elapsed:.2f}s"
        )
        return get_error_message("timeout")

    error_class_name = type(error).__name__
    if error_class_name == "RemoteProtocolError" or "Server disconnected" in str(error):
        log.warning(
            f"[req:{request_id}] 远程协议错误（服务器断开） | "
            f"error={str(error)} | total_time={total_elapsed:.2f}s | "
            f"hint=可能是中转服务器超时，建议检查代理配置或减少请求复杂度"
        )
        return get_error_message("timeout")

    log.error(
        f"[req:{request_id}] 未知错误 | error={type(error).__name__}: {str(error)} | total_time={total_elapsed:.2f}s",
        exc_info=True,
    )
    if hasattr(error, "response") and error.response:
        log.error(f"[req:{request_id}] Response Body: {error.response.text[:error_response_body_preview_chars]}")
    return get_error_message("unknown")
