"""Helpers for non-stream transport completion flow."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

import httpx

from ...errors import AuthenticationError, MikaAPIError, RateLimitError, ServerError
from ...infra.logging import logger as log
from ...infra.metrics_store import get_metrics_timeline_store
from ...metrics import metrics


RETRY_AFTER_DEFAULT_SECONDS = 60
AUTH_ERROR_DETAIL_PREVIEW_CHARS = 200
API_ERROR_BODY_PREVIEW_CHARS = 500

SERVER_ERROR_RETRY_BACKOFF_BASE = 2
SERVER_ERROR_RETRY_EXPONENT_OFFSET = 2


def bump_dict_counter(bucket: Dict[str, int], key: str) -> None:
    bucket[key] = int(bucket.get(key, 0) or 0) + 1


def attach_empty_reply_meta(
    *,
    message: Dict[str, Any],
    kind: str,
    finish_reason: Any,
    local_retries: int,
    response_id: Optional[str],
    phase: str,
    request_id: str,
    model: str,
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
    bump_dict_counter(metrics.api_empty_reply_reason_total, kind)


def log_empty_reply_fingerprint(
    *,
    request_id: str,
    model: str,
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


def extract_choice(parsed: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return parsed.get("choices", [{}])[0] or {}
    except Exception:
        return {}


def normalize_provider_usage(provider_name: str, parsed: Dict[str, Any]) -> Dict[str, Any]:
    usage = parsed.get("usage")
    if isinstance(usage, dict):
        return usage

    if provider_name == "anthropic":
        raw_usage = parsed.get("usage") or {}
        if isinstance(raw_usage, dict):
            prompt_tokens = int(raw_usage.get("input_tokens") or 0)
            completion_tokens = int(raw_usage.get("output_tokens") or 0)
            return {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            }

    if provider_name == "google_genai":
        raw_usage = parsed.get("usageMetadata") or {}
        if isinstance(raw_usage, dict):
            prompt_tokens = int(raw_usage.get("promptTokenCount") or 0)
            completion_tokens = int(raw_usage.get("candidatesTokenCount") or 0)
            total_tokens = int(raw_usage.get("totalTokenCount") or (prompt_tokens + completion_tokens))
            return {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            }

    return {}


def record_timeline_metrics(*, latency_ms: float, usage: Dict[str, Any]) -> None:
    try:
        timeline_store = get_metrics_timeline_store()
        timeline_store.record_llm(
            latency_ms=float(latency_ms),
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            total_tokens=int(usage.get("total_tokens") or 0),
        )
    except Exception:
        return


def log_empty_reply_diagnostics(
    *,
    request_id: str,
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


def raise_mapped_http_error(
    *,
    response: httpx.Response,
    phase: str,
    request_id: str,
    retry_count: int,
    on_error: Callable[[str], None],
) -> None:
    raw_status = getattr(response, "status_code", 200)
    try:
        status_code = int(raw_status)
    except (TypeError, ValueError):
        status_code = 200

    if status_code == 429:
        headers = getattr(response, "headers", {}) or {}
        retry_after = int(headers.get("Retry-After", RETRY_AFTER_DEFAULT_SECONDS))
        log.warning(f"[req:{request_id}] {phase} 限流! Retry-After: {retry_after}s")
        on_error("http_429")
        raise RateLimitError(
            "API rate limit exceeded",
            status_code=429,
            retry_after=retry_after,
        )

    if status_code in [401, 403]:
        text = str(getattr(response, "text", "") or "")
        error_detail = text[:AUTH_ERROR_DETAIL_PREVIEW_CHARS] if text else "No details"
        log.error(f"[req:{request_id}] {phase} 认证失败: {error_detail}")
        on_error(f"http_{status_code}")
        raise AuthenticationError(
            f"API authentication failed: {status_code}",
            status_code=status_code,
        )

    if status_code in [500, 502, 503, 504]:
        if retry_count > 0:
            wait_time = SERVER_ERROR_RETRY_BACKOFF_BASE ** (SERVER_ERROR_RETRY_EXPONENT_OFFSET - retry_count)
            log.warning(f"[req:{request_id}] {phase} 服务端错误 {status_code}, {wait_time}s 后重试...")
            on_error(f"http_{status_code}")
            raise ServerError(
                f"Server error {status_code}, will retry",
                status_code=status_code,
            )
        on_error(f"http_{status_code}")
        raise ServerError("Server error after retries", status_code=status_code)

    if status_code >= 400:
        text = str(getattr(response, "text", "") or "")
        error_body = text[:API_ERROR_BODY_PREVIEW_CHARS] if text else "Unknown error"
        log.error(f"[req:{request_id}] {phase} API 错误 {status_code}: {error_body}")
        on_error(f"http_{status_code}")

        if "safety" in error_body.lower() or "blocked" in error_body.lower():
            raise MikaAPIError(
                f"Content filtered: {status_code}",
                status_code=status_code,
            )

        raise MikaAPIError(f"API error: {status_code}", status_code=status_code)
