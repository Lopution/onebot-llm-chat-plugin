"""Gemini API - 发送请求与错误映射逻辑。"""

from __future__ import annotations

import time
import copy
from typing import Any, Dict, Optional, Tuple

import httpx
from nonebot import logger as log

from .config import plugin_config
from .errors import GeminiAPIError, RateLimitError, AuthenticationError, ServerError


# ==================== Magic-number constants ====================
RETRY_AFTER_DEFAULT_SECONDS = 60
AUTH_ERROR_DETAIL_PREVIEW_CHARS = 200
API_ERROR_BODY_PREVIEW_CHARS = 500

# 指数退避：wait_time = 2 ** (2 - retry_count)
SERVER_ERROR_RETRY_BACKOFF_BASE = 2
SERVER_ERROR_RETRY_EXPONENT_OFFSET = 2


async def send_api_request(
    *,
    http_client: httpx.AsyncClient,
    request_body: Dict[str, Any],
    request_id: str,
    retry_count: int,
    api_key: str,
    base_url: str,
    model: str,
) -> Tuple[Dict[str, Any], Optional[list], str]:
    """发送 API 请求并处理响应，返回 (assistant_message, tool_calls, api_key)。"""
    api_start = time.time()
    log.info(f"[req:{request_id}] 发送主对话请求 | 使用模型: {model}")
    log.debug(f"[req:{request_id}] 发送 API 请求 | model={model}")

    final_request_body = request_body.copy()
    if "temperature" not in final_request_body:
        final_request_body["temperature"] = plugin_config.gemini_temperature

    final_request_body["safetySettings"] = [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    ]

    async def _post(body: Dict[str, Any]) -> httpx.Response:
        return await http_client.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=body,
        )

    response = await _post(final_request_body)

    api_elapsed = time.time() - api_start
    log.debug(f"[req:{request_id}] API 响应 | status={response.status_code} | api_time={api_elapsed:.2f}s")

    status_code = response.status_code

    if status_code == 429:
        retry_after = int(response.headers.get("Retry-After", RETRY_AFTER_DEFAULT_SECONDS))
        log.warning(f"[req:{request_id}] 限流! Retry-After: {retry_after}s")
        raise RateLimitError(
            "API rate limit exceeded",
            status_code=429,
            retry_after=retry_after,
        )

    if status_code in [401, 403]:
        error_detail = (
            response.text[:AUTH_ERROR_DETAIL_PREVIEW_CHARS] if response.text else "No details"
        )
        log.error(f"[req:{request_id}] 认证失败: {error_detail}")
        raise AuthenticationError(
            f"API authentication failed: {status_code}",
            status_code=status_code,
        )

    if status_code in [500, 502, 503, 504]:
        if retry_count > 0:
            wait_time = SERVER_ERROR_RETRY_BACKOFF_BASE ** (SERVER_ERROR_RETRY_EXPONENT_OFFSET - retry_count)
            log.warning(f"[req:{request_id}] 服务端错误 {status_code}, {wait_time}s 后重试...")
            raise ServerError(
                f"Server error {status_code}, will retry",
                status_code=status_code,
            )
        raise ServerError("Server error after retries", status_code=status_code)

    if status_code >= 400:
        error_body = response.text[:API_ERROR_BODY_PREVIEW_CHARS] if response.text else "Unknown error"
        log.error(f"[req:{request_id}] API 错误 {status_code}: {error_body}")

        if "safety" in error_body.lower() or "blocked" in error_body.lower():
            raise GeminiAPIError(
                f"Content filtered: {status_code}",
                status_code=status_code,
            )

        raise GeminiAPIError(f"API error: {status_code}", status_code=status_code)

    response.raise_for_status()
    data = response.json()

    def _extract_choice(parsed: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return parsed.get("choices", [{}])[0] or {}
        except Exception:
            return {}

    choice = _extract_choice(data)
    assistant_message = (choice.get("message") or {})
    tool_calls = assistant_message.get("tool_calls")

    content = assistant_message.get("content")
    finish_reason = choice.get("finish_reason")
    reasoning_content = assistant_message.get("reasoning_content") or assistant_message.get("reasoning")

    # =========================================================
    # [Fix-B] finish_reason=stop 但 content 为空、仅返回 reasoning_content
    # - 不将 reasoning_content 直接返回给上层（避免发给用户）
    # - 触发一次快速“补全请求”，强制模型把最终回答写入 content（不输出思考）
    # - 仅重试 1 次，避免死循环
    # =========================================================
    if (not content or not str(content).strip()) and reasoning_content and not tool_calls:
        log.warning(
            f"[req:{request_id}] ⚠️ content 为空但存在 reasoning_content，触发补全请求 | finish_reason={finish_reason}"
        )

        completion_body = copy.deepcopy(final_request_body)
        completion_messages = list(completion_body.get("messages") or [])
        completion_messages.append(
            {
                "role": "system",
                "content": (
                    "你上一条回复没有把最终答案写入 message.content，而是只给了 reasoning_content。\n"
                    "现在请基于同一上下文，输出【最终可给用户的答复】到 message.content。\n"
                    "要求：不要输出思考过程/推理/草稿；不要使用 <think> 等标签；只给最终答案。"
                ),
            }
        )
        completion_body["messages"] = completion_messages
        completion_body["stream"] = False

        completion_resp = await _post(completion_body)
        # 补全请求也复用同样的错误映射
        completion_status = completion_resp.status_code
        if completion_status == 429:
            retry_after = int(
                completion_resp.headers.get("Retry-After", RETRY_AFTER_DEFAULT_SECONDS)
            )
            log.warning(f"[req:{request_id}] 补全请求限流! Retry-After: {retry_after}s")
            raise RateLimitError(
                "API rate limit exceeded",
                status_code=429,
                retry_after=retry_after,
            )
        if completion_status in [401, 403]:
            error_detail = (
                completion_resp.text[:AUTH_ERROR_DETAIL_PREVIEW_CHARS]
                if completion_resp.text
                else "No details"
            )
            log.error(f"[req:{request_id}] 补全请求认证失败: {error_detail}")
            raise AuthenticationError(
                f"API authentication failed: {completion_status}",
                status_code=completion_status,
            )
        if completion_status in [500, 502, 503, 504]:
            # 补全请求不额外做指数退避重试，交由上层空回复/重试策略兜底
            raise ServerError(
                f"Server error {completion_status} during completion",
                status_code=completion_status,
            )
        if completion_status >= 400:
            error_body = (
                completion_resp.text[:API_ERROR_BODY_PREVIEW_CHARS]
                if completion_resp.text
                else "Unknown error"
            )
            log.error(f"[req:{request_id}] 补全请求 API 错误 {completion_status}: {error_body}")
            if "safety" in error_body.lower() or "blocked" in error_body.lower():
                raise GeminiAPIError(
                    f"Content filtered: {completion_status}",
                    status_code=completion_status,
                )
            raise GeminiAPIError(f"API error: {completion_status}", status_code=completion_status)

        completion_resp.raise_for_status()
        completion_data = completion_resp.json()
        completion_choice = _extract_choice(completion_data)
        completion_message = (completion_choice.get("message") or {})
        completion_tool_calls = completion_message.get("tool_calls")
        completion_content = completion_message.get("content")

        if completion_tool_calls:
            # 补全请求不应触发工具调用；若触发则仍返回给上层处理
            log.warning(f"[req:{request_id}] 补全请求返回 tool_calls，按原流程交由上层处理")
            return completion_message, completion_tool_calls, api_key

        if completion_content and str(completion_content).strip():
            log.info(f"[req:{request_id}] 补全请求成功 | reply_len={len(str(completion_content))}")
            return completion_message, None, api_key

        log.warning(f"[req:{request_id}] 补全请求仍为空回复，交由上层空回复重试机制")
        # 回退到原始空 content 结果

    if (not content or not str(content).strip()) and not tool_calls:
        log.warning(f"[req:{request_id}] ⚠️ 检测到空回复! finish_reason={finish_reason}")
        log.warning(f"[req:{request_id}] Full Choice Data: {choice}")

    return assistant_message, tool_calls, api_key
