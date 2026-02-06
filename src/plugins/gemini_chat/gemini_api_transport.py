"""Gemini API - 发送请求与错误映射逻辑。"""

from __future__ import annotations

import asyncio
import time
import copy
from typing import Any, Dict, Optional, Tuple

import httpx
from nonebot import logger as log

from .config import plugin_config
from .errors import GeminiAPIError, RateLimitError, AuthenticationError, ServerError
from .metrics import metrics


# ==================== Magic-number constants ====================
RETRY_AFTER_DEFAULT_SECONDS = 60
AUTH_ERROR_DETAIL_PREVIEW_CHARS = 200
API_ERROR_BODY_PREVIEW_CHARS = 500

# 指数退避：wait_time = 2 ** (2 - retry_count)
SERVER_ERROR_RETRY_BACKOFF_BASE = 2
SERVER_ERROR_RETRY_EXPONENT_OFFSET = 2

# 空回复本地重试（避免直接回到上层重跑完整业务链）
EMPTY_REPLY_LOCAL_RETRY_COUNT_DEFAULT = 1
EMPTY_REPLY_LOCAL_RETRY_DELAY_SECONDS_DEFAULT = 0.4


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

    async def _post_once(body: Dict[str, Any]) -> httpx.Response:
        return await http_client.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=body,
        )

    def _bump_dict_counter(bucket: Dict[str, int], key: str) -> None:
        bucket[key] = int(bucket.get(key, 0) or 0) + 1

    def _record_transport_error(reason: str) -> None:
        _bump_dict_counter(metrics.api_transport_error_total, reason)

    timeout_retries = int(
        plugin_config.gemini_transport_timeout_retries
        if plugin_config.gemini_transport_timeout_retries is not None
        else 1
    )
    timeout_retries = max(0, timeout_retries)
    timeout_retry_delay = float(
        plugin_config.gemini_transport_timeout_retry_delay_seconds
        if plugin_config.gemini_transport_timeout_retry_delay_seconds is not None
        else 0.6
    )
    timeout_retry_delay = max(0.0, timeout_retry_delay)

    async def _post_with_timeout_retry(body: Dict[str, Any], *, phase: str) -> httpx.Response:
        """仅对超时进行本地重试，避免把请求直接抛回上层重跑整条链路。"""
        for attempt in range(timeout_retries + 1):
            try:
                return await _post_once(body)
            except httpx.TimeoutException:
                _record_transport_error("timeout")
                if attempt >= timeout_retries:
                    raise
                wait_seconds = timeout_retry_delay * (attempt + 1)
                log.warning(
                    f"[req:{request_id}] {phase} 请求超时，本地重试 | "
                    f"attempt={attempt + 1}/{timeout_retries} | wait={wait_seconds:.2f}s"
                )
                if wait_seconds > 0:
                    await asyncio.sleep(wait_seconds)

    def _attach_empty_reply_meta(
        *,
        message: Dict[str, Any],
        kind: str,
        finish_reason: Any,
        local_retries: int,
        response_id: Optional[str],
        phase: str,
    ) -> None:
        message["_empty_reply_meta"] = {
            "kind": kind,
            "finish_reason": str(finish_reason or ""),
            "local_retries": int(local_retries),
            "response_id": str(response_id or ""),
            "phase": phase,
            "request_id": request_id,
            "model": model,
        }
        metrics.api_empty_reply_total += 1
        _bump_dict_counter(metrics.api_empty_reply_reason_total, kind)

    def _log_empty_reply_fingerprint(
        *,
        phase: str,
        kind: str,
        parsed_data: Dict[str, Any],
        choice: Dict[str, Any],
        finish_reason: Any,
        local_retry_idx: int,
        local_retry_total: int,
    ) -> None:
        usage = parsed_data.get("usage") if isinstance(parsed_data, dict) else {}
        if not isinstance(usage, dict):
            usage = {}
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        total_tokens = usage.get("total_tokens")
        response_id = parsed_data.get("id") if isinstance(parsed_data, dict) else None
        tool_calls = (choice.get("message") or {}).get("tool_calls") if isinstance(choice, dict) else None
        tool_count = len(tool_calls) if isinstance(tool_calls, list) else 0
        log.warning(
            f"[req:{request_id}] empty_fingerprint phase={phase} kind={kind} "
            f"model={model} finish={finish_reason or 'unknown'} tool_calls={tool_count} "
            f"tokens={prompt_tokens}/{completion_tokens}/{total_tokens} "
            f"response_id={response_id or '-'} local_retry={local_retry_idx}/{local_retry_total}"
        )

    def _extract_choice(parsed: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return parsed.get("choices", [{}])[0] or {}
        except Exception:
            return {}

    def _log_empty_reply_diagnostics(
        *,
        phase: str,
        parsed_data: Dict[str, Any],
        choice: Dict[str, Any],
        finish_reason: Any,
        reasoning_content: Any,
        local_retry_idx: int,
        local_retry_total: int,
    ) -> None:
        usage = parsed_data.get("usage") if isinstance(parsed_data, dict) else {}
        if not isinstance(usage, dict):
            usage = {}
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        total_tokens = usage.get("total_tokens")
        response_id = parsed_data.get("id") if isinstance(parsed_data, dict) else None
        choices_count = len(parsed_data.get("choices") or []) if isinstance(parsed_data, dict) else 0
        tool_calls = (choice.get("message") or {}).get("tool_calls") if isinstance(choice, dict) else None
        tool_count = len(tool_calls) if isinstance(tool_calls, list) else 0
        has_reasoning = bool(reasoning_content and str(reasoning_content).strip())
        log.warning(
            f"[req:{request_id}] 空回复诊断 | phase={phase} | finish_reason={finish_reason or 'unknown'} | "
            f"has_reasoning={has_reasoning} | tool_calls={tool_count} | "
            f"tokens={prompt_tokens}/{completion_tokens}/{total_tokens} | "
            f"choices={choices_count} | response_id={response_id or '-'} | "
            f"local_retry={local_retry_idx}/{local_retry_total}"
        )
        log.warning(f"[req:{request_id}] Full Choice Data: {choice}")

    def _raise_mapped_http_error(response: httpx.Response, *, phase: str) -> None:
        status_code = response.status_code

        if status_code == 429:
            retry_after = int(response.headers.get("Retry-After", RETRY_AFTER_DEFAULT_SECONDS))
            log.warning(f"[req:{request_id}] {phase} 限流! Retry-After: {retry_after}s")
            _record_transport_error("http_429")
            raise RateLimitError(
                "API rate limit exceeded",
                status_code=429,
                retry_after=retry_after,
            )

        if status_code in [401, 403]:
            error_detail = (
                response.text[:AUTH_ERROR_DETAIL_PREVIEW_CHARS] if response.text else "No details"
            )
            log.error(f"[req:{request_id}] {phase} 认证失败: {error_detail}")
            _record_transport_error(f"http_{status_code}")
            raise AuthenticationError(
                f"API authentication failed: {status_code}",
                status_code=status_code,
            )

        if status_code in [500, 502, 503, 504]:
            if retry_count > 0:
                wait_time = SERVER_ERROR_RETRY_BACKOFF_BASE ** (SERVER_ERROR_RETRY_EXPONENT_OFFSET - retry_count)
                log.warning(f"[req:{request_id}] {phase} 服务端错误 {status_code}, {wait_time}s 后重试...")
                _record_transport_error(f"http_{status_code}")
                raise ServerError(
                    f"Server error {status_code}, will retry",
                    status_code=status_code,
                )
            _record_transport_error(f"http_{status_code}")
            raise ServerError("Server error after retries", status_code=status_code)

        if status_code >= 400:
            error_body = response.text[:API_ERROR_BODY_PREVIEW_CHARS] if response.text else "Unknown error"
            log.error(f"[req:{request_id}] {phase} API 错误 {status_code}: {error_body}")
            _record_transport_error(f"http_{status_code}")

            if "safety" in error_body.lower() or "blocked" in error_body.lower():
                raise GeminiAPIError(
                    f"Content filtered: {status_code}",
                    status_code=status_code,
                )

            raise GeminiAPIError(f"API error: {status_code}", status_code=status_code)

    async def _post_and_parse(
        body: Dict[str, Any],
        *,
        phase: str,
    ) -> Tuple[Dict[str, Any], Optional[list], Any, Any, Dict[str, Any], Dict[str, Any]]:
        response = await _post_with_timeout_retry(body, phase=phase)
        _raise_mapped_http_error(response, phase=phase)
        response.raise_for_status()
        parsed_data = response.json()
        choice = _extract_choice(parsed_data)
        assistant_message = (choice.get("message") or {})
        tool_calls = assistant_message.get("tool_calls")
        content = assistant_message.get("content")
        finish_reason = choice.get("finish_reason")
        reasoning_content = assistant_message.get("reasoning_content") or assistant_message.get("reasoning")
        return assistant_message, tool_calls, content, finish_reason, reasoning_content, choice, parsed_data

    response = await _post_with_timeout_retry(final_request_body, phase="主请求")
    api_elapsed = time.time() - api_start
    log.debug(f"[req:{request_id}] API 响应 | status={response.status_code} | api_time={api_elapsed:.2f}s")
    _raise_mapped_http_error(response, phase="主请求")
    response.raise_for_status()
    data = response.json()
    choice = _extract_choice(data)
    assistant_message = (choice.get("message") or {})
    tool_calls = assistant_message.get("tool_calls")
    content = assistant_message.get("content")
    finish_reason = choice.get("finish_reason")
    reasoning_content = assistant_message.get("reasoning_content") or assistant_message.get("reasoning")

    async def _completion_request() -> Tuple[Dict[str, Any], Optional[list], Any]:
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
        c_assistant, c_tool_calls, c_content, c_finish, c_reasoning, c_choice, c_data = await _post_and_parse(
            completion_body,
            phase="补全请求",
        )
        if c_tool_calls:
            log.warning(f"[req:{request_id}] 补全请求返回 tool_calls，按原流程交由上层处理")
            return c_assistant, c_tool_calls, c_content
        if c_content and str(c_content).strip():
            log.info(f"[req:{request_id}] 补全请求成功 | reply_len={len(str(c_content))}")
            return c_assistant, None, c_content
        _log_empty_reply_diagnostics(
            phase="补全请求",
            parsed_data=c_data,
            choice=c_choice,
            finish_reason=c_finish,
            reasoning_content=c_reasoning,
            local_retry_idx=0,
            local_retry_total=0,
        )
        return c_assistant, None, c_content

    # =========================================================
    # [Fix-B] finish_reason=stop 但 content 为空、仅返回 reasoning_content
    # - 不将 reasoning_content 直接返回给上层（避免发给用户）
    # - 触发一次快速“补全请求”，强制模型把最终回答写入 content（不输出思考）
    # - 仅重试 1 次，避免死循环
    # =========================================================
    if (not content or not str(content).strip()) and reasoning_content and not tool_calls:
        _log_empty_reply_fingerprint(
            phase="main_reasoning_only",
            kind="reasoning_only_empty",
            parsed_data=data,
            choice=choice,
            finish_reason=finish_reason,
            local_retry_idx=0,
            local_retry_total=0,
        )
        log.warning(
            f"[req:{request_id}] ⚠️ content 为空但存在 reasoning_content，触发补全请求 | finish_reason={finish_reason}"
        )
        completion_message, completion_tool_calls, completion_content = await _completion_request()
        if completion_tool_calls:
            return completion_message, completion_tool_calls, api_key
        if completion_content and str(completion_content).strip():
            return completion_message, None, api_key
        log.warning(f"[req:{request_id}] 补全请求仍为空回复，继续尝试本地重试")

    if (not content or not str(content).strip()) and not tool_calls:
        max_local_retries = int(
            plugin_config.gemini_empty_reply_local_retries
            if plugin_config.gemini_empty_reply_local_retries is not None
            else EMPTY_REPLY_LOCAL_RETRY_COUNT_DEFAULT
        )
        delay_base = float(
            plugin_config.gemini_empty_reply_local_retry_delay_seconds
            if plugin_config.gemini_empty_reply_local_retry_delay_seconds is not None
            else EMPTY_REPLY_LOCAL_RETRY_DELAY_SECONDS_DEFAULT
        )
        _log_empty_reply_diagnostics(
            phase="主请求",
            parsed_data=data,
            choice=choice,
            finish_reason=finish_reason,
            reasoning_content=reasoning_content,
            local_retry_idx=0,
            local_retry_total=max_local_retries,
        )
        _log_empty_reply_fingerprint(
            phase="main",
            kind="provider_empty",
            parsed_data=data,
            choice=choice,
            finish_reason=finish_reason,
            local_retry_idx=0,
            local_retry_total=max_local_retries,
        )

        for attempt in range(1, max_local_retries + 1):
            if delay_base > 0:
                await asyncio.sleep(delay_base * attempt)
            log.warning(f"[req:{request_id}] 空回复本地重试 | attempt={attempt}/{max_local_retries}")
            (
                retry_assistant,
                retry_tool_calls,
                retry_content,
                retry_finish_reason,
                retry_reasoning_content,
                retry_choice,
                retry_data,
            ) = await _post_and_parse(final_request_body, phase=f"空回复重试#{attempt}")

            if retry_tool_calls:
                return retry_assistant, retry_tool_calls, api_key

            if retry_content and str(retry_content).strip():
                log.info(
                    f"[req:{request_id}] 空回复本地重试成功 | attempt={attempt} | "
                    f"reply_len={len(str(retry_content))}"
                )
                return retry_assistant, None, api_key

            if retry_reasoning_content:
                _log_empty_reply_fingerprint(
                    phase=f"retry#{attempt}",
                    kind="reasoning_only_empty",
                    parsed_data=retry_data,
                    choice=retry_choice,
                    finish_reason=retry_finish_reason,
                    local_retry_idx=attempt,
                    local_retry_total=max_local_retries,
                )
                log.warning(
                    f"[req:{request_id}] 空回复重试返回 reasoning_content，触发补全请求 | "
                    f"attempt={attempt} | finish_reason={retry_finish_reason}"
                )
                completion_message, completion_tool_calls, completion_content = await _completion_request()
                if completion_tool_calls:
                    return completion_message, completion_tool_calls, api_key
                if completion_content and str(completion_content).strip():
                    return completion_message, None, api_key

            _log_empty_reply_diagnostics(
                phase=f"空回复重试#{attempt}",
                parsed_data=retry_data,
                choice=retry_choice,
                finish_reason=retry_finish_reason,
                reasoning_content=retry_reasoning_content,
                local_retry_idx=attempt,
                local_retry_total=max_local_retries,
            )
            _log_empty_reply_fingerprint(
                phase=f"retry#{attempt}",
                kind="provider_empty",
                parsed_data=retry_data,
                choice=retry_choice,
                finish_reason=retry_finish_reason,
                local_retry_idx=attempt,
                local_retry_total=max_local_retries,
            )
            assistant_message = retry_assistant
            finish_reason = retry_finish_reason
            data = retry_data
            reasoning_content = retry_reasoning_content

        empty_kind = "reasoning_only_empty" if (reasoning_content and str(reasoning_content).strip()) else "provider_empty"
        response_id = data.get("id") if isinstance(data, dict) else None
        _attach_empty_reply_meta(
            message=assistant_message,
            kind=empty_kind,
            finish_reason=finish_reason,
            local_retries=max_local_retries,
            response_id=str(response_id or ""),
            phase="transport_final",
        )
    elif (not content or not str(content).strip()) and tool_calls:
        _log_empty_reply_fingerprint(
            phase="main_tool_calls",
            kind="empty_with_tool_calls",
            parsed_data=data,
            choice=choice,
            finish_reason=finish_reason,
            local_retry_idx=0,
            local_retry_total=0,
        )

    return assistant_message, tool_calls, api_key
