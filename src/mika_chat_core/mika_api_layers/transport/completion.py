"""Mika API - 非流式传输流程。"""

from __future__ import annotations

import asyncio
import copy
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import httpx

from ...config import plugin_config
from ...infra.logging import logger as log
from ...llm.providers import build_provider_request, parse_provider_response
from ...metrics import metrics
from .completion_utils import (
    attach_empty_reply_meta,
    bump_dict_counter,
    extract_choice,
    log_empty_reply_diagnostics,
    log_empty_reply_fingerprint,
    normalize_provider_usage,
    raise_mapped_http_error,
    record_timeline_metrics,
)


EMPTY_REPLY_LOCAL_RETRY_COUNT_DEFAULT = 1
EMPTY_REPLY_LOCAL_RETRY_DELAY_SECONDS_DEFAULT = 0.4


@dataclass
class ParsedCompletionResponse:
    assistant_message: Dict[str, Any]
    tool_calls: Optional[list]
    content: Any
    finish_reason: Any
    reasoning_content: Any
    choice: Dict[str, Any]
    data: Dict[str, Any]


def _resolve_timeout_retry_settings() -> tuple[int, float]:
    timeout_retries = int(
        plugin_config.mika_transport_timeout_retries
        if plugin_config.mika_transport_timeout_retries is not None
        else 1
    )
    timeout_retries = max(0, timeout_retries)

    timeout_retry_delay = float(
        plugin_config.mika_transport_timeout_retry_delay_seconds
        if plugin_config.mika_transport_timeout_retry_delay_seconds is not None
        else 0.6
    )
    timeout_retry_delay = max(0.0, timeout_retry_delay)
    return timeout_retries, timeout_retry_delay


async def _post_once(
    *,
    http_client: httpx.AsyncClient,
    provider_name: str,
    base_url: str,
    model: str,
    api_key: str,
    body: Dict[str, Any],
    extra_headers: Dict[str, Any],
) -> httpx.Response:
    prepared = build_provider_request(
        provider=provider_name,
        base_url=base_url,
        model=model,
        api_key=api_key,
        request_body=body,
        extra_headers=extra_headers,
        default_temperature=float(plugin_config.mika_temperature),
    )
    return await http_client.post(
        prepared.url,
        headers=prepared.headers,
        params=prepared.params,
        json=prepared.json_body,
    )


async def _post_with_timeout_retry(
    *,
    http_client: httpx.AsyncClient,
    provider_name: str,
    base_url: str,
    model: str,
    api_key: str,
    body: Dict[str, Any],
    extra_headers: Dict[str, Any],
    phase: str,
    request_id: str,
    timeout_retries: int,
    timeout_retry_delay: float,
    record_transport_error: Any,
) -> httpx.Response:
    for attempt in range(timeout_retries + 1):
        try:
            return await _post_once(
                http_client=http_client,
                provider_name=provider_name,
                base_url=base_url,
                model=model,
                api_key=api_key,
                body=body,
                extra_headers=extra_headers,
            )
        except httpx.TimeoutException:
            record_transport_error("timeout")
            if attempt >= timeout_retries:
                raise
            wait_seconds = timeout_retry_delay * (attempt + 1)
            log.warning(
                f"[req:{request_id}] {phase} 请求超时，本地重试 | "
                f"attempt={attempt + 1}/{timeout_retries} | wait={wait_seconds:.2f}s"
            )
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)


async def _post_and_parse(
    *,
    http_client: httpx.AsyncClient,
    provider_name: str,
    request_id: str,
    retry_count: int,
    base_url: str,
    model: str,
    api_key: str,
    body: Dict[str, Any],
    extra_headers: Dict[str, Any],
    phase: str,
    timeout_retries: int,
    timeout_retry_delay: float,
    record_transport_error: Any,
) -> ParsedCompletionResponse:
    response = await _post_with_timeout_retry(
        http_client=http_client,
        provider_name=provider_name,
        base_url=base_url,
        model=model,
        api_key=api_key,
        body=body,
        extra_headers=extra_headers,
        phase=phase,
        request_id=request_id,
        timeout_retries=timeout_retries,
        timeout_retry_delay=timeout_retry_delay,
        record_transport_error=record_transport_error,
    )

    response_elapsed_ms = (
        float(response.elapsed.total_seconds() * 1000.0)
        if getattr(response, "elapsed", None) is not None
        else 0.0
    )

    raise_mapped_http_error(
        response=response,
        phase=phase,
        request_id=request_id,
        retry_count=retry_count,
        on_error=record_transport_error,
    )
    response.raise_for_status()
    raw_data = response.json()

    if provider_name in {"openai_compat", "azure_openai"}:
        parsed_data = raw_data
        choice = extract_choice(parsed_data)
        assistant_message = (choice.get("message") or {})
        tool_calls = assistant_message.get("tool_calls")
        content = assistant_message.get("content")
        finish_reason = choice.get("finish_reason")
        reasoning_content = assistant_message.get("reasoning_content") or assistant_message.get("reasoning")
        record_timeline_metrics(
            latency_ms=response_elapsed_ms,
            usage=normalize_provider_usage(provider_name, parsed_data),
        )
        return ParsedCompletionResponse(
            assistant_message=assistant_message,
            tool_calls=tool_calls,
            content=content,
            finish_reason=finish_reason,
            reasoning_content=reasoning_content,
            choice=choice,
            data=parsed_data,
        )

    assistant_message, tool_calls, content, finish_reason = parse_provider_response(
        provider=provider_name,
        data=raw_data,
    )
    reasoning_content = assistant_message.get("reasoning_content") or assistant_message.get("reasoning")
    synthetic_choice: Dict[str, Any] = {
        "message": assistant_message,
        "finish_reason": finish_reason,
    }
    synthetic_data: Dict[str, Any] = {
        "id": str(raw_data.get("id") or raw_data.get("responseId") or ""),
        "choices": [synthetic_choice],
        "usage": normalize_provider_usage(provider_name, raw_data),
        "raw": raw_data,
    }
    record_timeline_metrics(
        latency_ms=response_elapsed_ms,
        usage=dict(synthetic_data.get("usage") or {}),
    )
    return ParsedCompletionResponse(
        assistant_message=assistant_message,
        tool_calls=tool_calls,
        content=content,
        finish_reason=finish_reason,
        reasoning_content=reasoning_content,
        choice=synthetic_choice,
        data=synthetic_data,
    )


async def send_api_request_flow(
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

    llm_cfg = plugin_config.get_llm_config()
    provider_name = str(llm_cfg.get("provider") or "openai_compat")
    extra_headers = dict(llm_cfg.get("extra_headers") or {})

    final_request_body = copy.deepcopy(request_body)
    if "temperature" not in final_request_body:
        final_request_body["temperature"] = plugin_config.mika_temperature

    timeout_retries, timeout_retry_delay = _resolve_timeout_retry_settings()

    def _record_transport_error(reason: str) -> None:
        bump_dict_counter(metrics.api_transport_error_total, reason)

    async def _run_post_and_parse(body: Dict[str, Any], *, phase: str) -> ParsedCompletionResponse:
        return await _post_and_parse(
            http_client=http_client,
            provider_name=provider_name,
            request_id=request_id,
            retry_count=retry_count,
            base_url=base_url,
            model=model,
            api_key=api_key,
            body=body,
            extra_headers=extra_headers,
            phase=phase,
            timeout_retries=timeout_retries,
            timeout_retry_delay=timeout_retry_delay,
            record_transport_error=_record_transport_error,
        )

    parsed = await _run_post_and_parse(final_request_body, phase="主请求")
    assistant_message = parsed.assistant_message
    tool_calls = parsed.tool_calls
    content = parsed.content
    finish_reason = parsed.finish_reason
    reasoning_content = parsed.reasoning_content
    choice = parsed.choice
    data = parsed.data

    api_elapsed = time.time() - api_start
    log.debug(f"[req:{request_id}] API 响应 | api_time={api_elapsed:.2f}s | provider={provider_name}")

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
        completion_parsed = await _run_post_and_parse(completion_body, phase="补全请求")

        if completion_parsed.tool_calls:
            log.warning(f"[req:{request_id}] 补全请求返回 tool_calls，按原流程交由上层处理")
            return completion_parsed.assistant_message, completion_parsed.tool_calls, completion_parsed.content

        if completion_parsed.content and str(completion_parsed.content).strip():
            log.info(f"[req:{request_id}] 补全请求成功 | reply_len={len(str(completion_parsed.content))}")
            return completion_parsed.assistant_message, None, completion_parsed.content

        log_empty_reply_diagnostics(
            request_id=request_id,
            phase="补全请求",
            parsed_data=completion_parsed.data,
            choice=completion_parsed.choice,
            finish_reason=completion_parsed.finish_reason,
            reasoning_content=completion_parsed.reasoning_content,
            local_retry_idx=0,
            local_retry_total=0,
        )
        return completion_parsed.assistant_message, None, completion_parsed.content

    if (not content or not str(content).strip()) and reasoning_content and not tool_calls:
        log_empty_reply_fingerprint(
            request_id=request_id,
            model=model,
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
            plugin_config.mika_empty_reply_local_retries
            if plugin_config.mika_empty_reply_local_retries is not None
            else EMPTY_REPLY_LOCAL_RETRY_COUNT_DEFAULT
        )
        delay_base = float(
            plugin_config.mika_empty_reply_local_retry_delay_seconds
            if plugin_config.mika_empty_reply_local_retry_delay_seconds is not None
            else EMPTY_REPLY_LOCAL_RETRY_DELAY_SECONDS_DEFAULT
        )

        log_empty_reply_diagnostics(
            request_id=request_id,
            phase="主请求",
            parsed_data=data,
            choice=choice,
            finish_reason=finish_reason,
            reasoning_content=reasoning_content,
            local_retry_idx=0,
            local_retry_total=max_local_retries,
        )
        log_empty_reply_fingerprint(
            request_id=request_id,
            model=model,
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
            retry_parsed = await _run_post_and_parse(final_request_body, phase=f"空回复重试#{attempt}")

            if retry_parsed.tool_calls:
                return retry_parsed.assistant_message, retry_parsed.tool_calls, api_key

            if retry_parsed.content and str(retry_parsed.content).strip():
                log.info(
                    f"[req:{request_id}] 空回复本地重试成功 | attempt={attempt} | "
                    f"reply_len={len(str(retry_parsed.content))}"
                )
                return retry_parsed.assistant_message, None, api_key

            if retry_parsed.reasoning_content:
                log_empty_reply_fingerprint(
                    request_id=request_id,
                    model=model,
                    phase=f"retry#{attempt}",
                    kind="reasoning_only_empty",
                    parsed_data=retry_parsed.data,
                    choice=retry_parsed.choice,
                    finish_reason=retry_parsed.finish_reason,
                    local_retry_idx=attempt,
                    local_retry_total=max_local_retries,
                )
                log.warning(
                    f"[req:{request_id}] 空回复重试返回 reasoning_content，触发补全请求 | "
                    f"attempt={attempt} | finish_reason={retry_parsed.finish_reason}"
                )
                completion_message, completion_tool_calls, completion_content = await _completion_request()
                if completion_tool_calls:
                    return completion_message, completion_tool_calls, api_key
                if completion_content and str(completion_content).strip():
                    return completion_message, None, api_key

            log_empty_reply_diagnostics(
                request_id=request_id,
                phase=f"空回复重试#{attempt}",
                parsed_data=retry_parsed.data,
                choice=retry_parsed.choice,
                finish_reason=retry_parsed.finish_reason,
                reasoning_content=retry_parsed.reasoning_content,
                local_retry_idx=attempt,
                local_retry_total=max_local_retries,
            )
            log_empty_reply_fingerprint(
                request_id=request_id,
                model=model,
                phase=f"retry#{attempt}",
                kind="provider_empty",
                parsed_data=retry_parsed.data,
                choice=retry_parsed.choice,
                finish_reason=retry_parsed.finish_reason,
                local_retry_idx=attempt,
                local_retry_total=max_local_retries,
            )

            assistant_message = retry_parsed.assistant_message
            finish_reason = retry_parsed.finish_reason
            data = retry_parsed.data
            reasoning_content = retry_parsed.reasoning_content

        empty_kind = "reasoning_only_empty" if (reasoning_content and str(reasoning_content).strip()) else "provider_empty"
        response_id = data.get("id") if isinstance(data, dict) else None
        attach_empty_reply_meta(
            message=assistant_message,
            kind=empty_kind,
            finish_reason=finish_reason,
            local_retries=max_local_retries,
            response_id=str(response_id or ""),
            phase="transport_final",
            request_id=request_id,
            model=model,
        )

    elif (not content or not str(content).strip()) and tool_calls:
        log_empty_reply_fingerprint(
            request_id=request_id,
            model=model,
            phase="main_tool_calls",
            kind="empty_with_tool_calls",
            parsed_data=data,
            choice=choice,
            finish_reason=finish_reason,
            local_retry_idx=0,
            local_retry_total=0,
        )

    return assistant_message, tool_calls, api_key
