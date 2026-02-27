"""Mika API - 非流式传输流程。"""

from __future__ import annotations

import asyncio
import copy
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import httpx

from ...config import plugin_config
from ...infra.logging import logger as log
from ...observability.trace_store import get_trace_store
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


def _estimate_request_body_bytes(body: Dict[str, Any]) -> int:
    try:
        dumped = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        return len(dumped.encode("utf-8"))
    except Exception:
        return len(str(body or "").encode("utf-8"))


def _estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    # Best-effort heuristic token estimator; must never break transport.
    try:
        from ...utils.context_schema import estimate_message_tokens

        total = 0
        for item in messages or []:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip().lower()
            msg: Dict[str, Any] = {"role": role, "content": item.get("content", "")}
            if role == "assistant" and isinstance(item.get("tool_calls"), list):
                msg["tool_calls"] = item["tool_calls"]
            if role == "tool" and item.get("tool_call_id"):
                msg["tool_call_id"] = item["tool_call_id"]
            total += int(estimate_message_tokens(msg))
        return int(total)
    except Exception:
        return 0


def _is_empty_content(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return not str(value).strip()


def _should_self_heal() -> bool:
    try:
        return bool(getattr(plugin_config, "mika_transport_self_heal_enabled", True))
    except Exception:
        return False


def _resolve_self_heal_max_attempts() -> int:
    try:
        raw = getattr(plugin_config, "mika_transport_self_heal_max_attempts", 3)
        return max(0, int(raw or 0))
    except Exception:
        return 0


def _is_self_heal_exception(exc: BaseException) -> tuple[bool, str]:
    # Keep this conservative: only retry with degraded context when the error
    # strongly suggests size/capability issues.
    if isinstance(exc, httpx.HTTPStatusError) and getattr(exc, "response", None) is not None:
        status = int(getattr(exc.response, "status_code", 0) or 0)
        if status == 413:
            return True, "http_413"

        # Some proxy endpoints return 400 for "too many tokens"/"context length".
        if status in {400, 422}:
            try:
                text = str(exc.response.text or "")
            except Exception:
                text = ""
            lowered = text.lower()
            patterns = [
                "maximum context length",
                "max context length",
                "context length exceeded",
                "too many tokens",
                "tokens",
                "request too large",
                "payload too large",
            ]
            if any(p in lowered for p in patterns):
                return True, "context_limit"

    msg = str(exc or "").lower()
    if any(
        p in msg
        for p in [
            "maximum context length",
            "context length exceeded",
            "too many tokens",
            "request too large",
            "payload too large",
            "entity too large",
        ]
    ):
        return True, "context_limit"
    return False, ""


def _find_transcript_idx(messages: list[dict[str, Any]]) -> Optional[int]:
    try:
        from ...utils.transcript_builder import TRANSCRIPT_HEADER

        for idx, msg in enumerate(messages or []):
            if not isinstance(msg, dict):
                continue
            if str(msg.get("role") or "").strip().lower() != "system":
                continue
            content = msg.get("content")
            if isinstance(content, str) and TRANSCRIPT_HEADER in content:
                return idx
    except Exception:
        return None
    return None


def _shrink_transcript_in_body(body: Dict[str, Any]) -> bool:
    """Shrink transcript block (best-effort). Returns whether any change happened."""
    messages = body.get("messages")
    if not isinstance(messages, list):
        return False

    idx = _find_transcript_idx(messages)
    if idx is None:
        return False

    content = messages[idx].get("content")
    if not isinstance(content, str):
        return False

    try:
        from ...utils.context_token_budget import resolve_context_max_tokens_soft
        from ...utils.transcript_builder import shrink_transcript_block

        max_bytes = int(getattr(plugin_config, "mika_request_body_max_bytes", 1_800_000) or 1_800_000)
        max_bytes = max(200_000, max_bytes)

        model = str(body.get("model") or "").strip()
        max_tokens_soft = int(resolve_context_max_tokens_soft(plugin_config, models=[model]) or 0)
        max_tokens_soft = max(0, max_tokens_soft)

        bytes_before = _estimate_request_body_bytes(body)
        tokens_before = _estimate_messages_tokens(messages)

        ratios = [0.7, 0.5]
        changed = False
        for ratio in ratios:
            shrunk = shrink_transcript_block(content, keep_ratio=ratio)
            messages[idx]["content"] = shrunk.text
            changed = True

            bytes_after = _estimate_request_body_bytes(body)
            tokens_after = _estimate_messages_tokens(messages)

            # If we are already within our own conservative budgets, stop shrinking.
            if bytes_after <= max_bytes and (not max_tokens_soft or tokens_after <= max_tokens_soft):
                break

            content = messages[idx].get("content") if isinstance(messages[idx], dict) else ""
            if not isinstance(content, str):
                break

        if changed:
            log.warning(
                f"[transport] shrink_transcript | bytes={bytes_before}->{_estimate_request_body_bytes(body)} | "
                f"tokens={tokens_before}->{_estimate_messages_tokens(messages)}"
            )
        return changed
    except Exception:
        return False


def _drop_tools_in_body(body: Dict[str, Any]) -> bool:
    messages = body.get("messages")
    if not isinstance(messages, list):
        return False

    changed = False
    if "tools" in body:
        body["tools"] = []
        changed = True
    if "tool_choice" in body:
        body.pop("tool_choice", None)
        changed = True

    new_messages: list[dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "").strip().lower()
        if role == "tool":
            changed = True
            continue
        if role == "assistant" and msg.get("tool_calls"):
            # If the assistant message is purely a tool_call wrapper, drop it.
            content = msg.get("content")
            if _is_empty_content(content):
                changed = True
                continue
            new_msg = dict(msg)
            new_msg.pop("tool_calls", None)
            new_messages.append(new_msg)
            changed = True
            continue
        new_messages.append(msg)

    if changed:
        body["messages"] = new_messages
    return changed


def _drop_images_in_body(body: Dict[str, Any]) -> bool:
    messages = body.get("messages")
    if not isinstance(messages, list):
        return False

    try:
        from ...utils.media_semantics import placeholder_from_content_part
    except Exception:
        placeholder_from_content_part = None  # type: ignore[assignment]

    changed = False
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if isinstance(content, list):
            new_parts: list[dict[str, Any]] = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                part_type = str(part.get("type") or "").strip().lower()
                if part_type == "image_url":
                    token = "[图片]"
                    if placeholder_from_content_part is not None:
                        try:
                            token = str(placeholder_from_content_part(part) or token)
                        except Exception:
                            token = "[图片]"
                    new_parts.append({"type": "text", "text": token})
                    changed = True
                else:
                    new_parts.append(part)
            msg["content"] = new_parts
        elif isinstance(content, str) and ("data:image" in content or "http" in content):
            # Don't attempt to parse provider-specific formats; leave plain strings unchanged.
            pass

    return changed


def _minimal_context_in_body(body: Dict[str, Any]) -> bool:
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        return False

    transcript_idx = _find_transcript_idx(messages)

    first_system: Optional[dict[str, Any]] = None
    system_injections: list[dict[str, Any]] = []
    last_user: Optional[dict[str, Any]] = None

    for idx, msg in enumerate(messages):
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "").strip().lower()
        if role == "system":
            if transcript_idx is not None and idx == transcript_idx:
                continue
            if first_system is None:
                first_system = msg
            else:
                # Keep additional system injection blocks (mapping/caption/proactive reason).
                system_injections.append(msg)
        elif role == "user":
            last_user = msg

    new_messages: list[dict[str, Any]] = []
    if first_system is not None:
        new_messages.append(first_system)
    if system_injections:
        new_messages.extend(system_injections[-2:])  # keep last few injections
    if last_user is not None:
        new_messages.append(last_user)

    if not new_messages:
        return False

    body["messages"] = new_messages
    # Also ensure tools are not sent in minimal mode.
    body["tools"] = []
    body.pop("tool_choice", None)
    return True


def _combine_self_heal_actions(max_attempts: int) -> list[list[str]]:
    base = ["shrink_transcript", "drop_tools", "drop_images", "minimal_context"]
    if max_attempts <= 0:
        return []
    if max_attempts >= len(base):
        return [[x] for x in base]
    # Not enough attempts: combine tail actions into the last attempt, preserving order.
    head = base[: max_attempts - 1]
    tail = base[max_attempts - 1 :]
    out: list[list[str]] = [[x] for x in head]
    out.append(tail)
    return out


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

    async def _trace_self_heal_event(event: Dict[str, Any]) -> None:
        if not _should_self_heal():
            return
        try:
            await get_trace_store().append_event(
                request_id=request_id,
                session_key="unknown",
                event={"type": "transport_self_heal", **(event or {})},
            )
        except Exception:
            pass

    try:
        parsed = await _run_post_and_parse(final_request_body, phase="主请求")
    except Exception as exc:
        retryable, kind = _is_self_heal_exception(exc)
        if _should_self_heal() and retryable:
            max_attempts = _resolve_self_heal_max_attempts()
            action_groups = _combine_self_heal_actions(max_attempts)
            await _trace_self_heal_event(
                {
                    "phase": "trigger",
                    "trigger": kind or "error",
                    "max_attempts": max_attempts,
                    "bytes_before": _estimate_request_body_bytes(final_request_body),
                    "tokens_before": _estimate_messages_tokens(list(final_request_body.get("messages") or [])),
                    "err": str(exc),
                }
            )

            healed_body = copy.deepcopy(final_request_body)
            last_exc: Optional[BaseException] = exc

            for idx, actions in enumerate(action_groups, start=1):
                for act in actions:
                    if act == "shrink_transcript":
                        _shrink_transcript_in_body(healed_body)
                    elif act == "drop_tools":
                        _drop_tools_in_body(healed_body)
                    elif act == "drop_images":
                        _drop_images_in_body(healed_body)
                    elif act == "minimal_context":
                        _minimal_context_in_body(healed_body)

                await _trace_self_heal_event(
                    {
                        "phase": "attempt",
                        "attempt": idx,
                        "actions": list(actions),
                        "bytes": _estimate_request_body_bytes(healed_body),
                        "tokens": _estimate_messages_tokens(list(healed_body.get("messages") or [])),
                    }
                )

                try:
                    healed_parsed = await _run_post_and_parse(
                        healed_body,
                        phase=f"自愈#{idx}({'+'.join(actions)})",
                    )
                    last_exc = None
                except Exception as healed_exc:
                    last_exc = healed_exc
                    healed_retryable, healed_kind = _is_self_heal_exception(healed_exc)
                    await _trace_self_heal_event(
                        {
                            "phase": "attempt_error",
                            "attempt": idx,
                            "actions": list(actions),
                            "kind": healed_kind or "unknown",
                            "err": str(healed_exc),
                        }
                    )
                    if healed_retryable:
                        continue
                    raise

                if healed_parsed.tool_calls:
                    await _trace_self_heal_event(
                        {"phase": "success", "attempt": idx, "actions": list(actions), "result": "tool_calls"}
                    )
                    return healed_parsed.assistant_message, healed_parsed.tool_calls, api_key
                if healed_parsed.content and str(healed_parsed.content).strip():
                    await _trace_self_heal_event(
                        {
                            "phase": "success",
                            "attempt": idx,
                            "actions": list(actions),
                            "result": "content",
                            "reply_len": len(str(healed_parsed.content)),
                        }
                    )
                    return healed_parsed.assistant_message, None, api_key

                await _trace_self_heal_event(
                    {"phase": "attempt_empty", "attempt": idx, "actions": list(actions)}
                )

            await _trace_self_heal_event(
                {
                    "phase": "exhausted",
                    "attempts": len(action_groups),
                    "last_error": str(last_exc) if last_exc else "",
                }
            )
            if last_exc is not None:
                raise last_exc
        raise
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

    # -------------------- Transport self-heal (best-effort) --------------------
    # If we still have an empty reply (or size/context errors), try progressively
    # degraded requests (shrink transcript, drop tools/images, minimal context).
    if _should_self_heal() and _is_empty_content(content) and not tool_calls:
        max_attempts = _resolve_self_heal_max_attempts()
        action_groups = _combine_self_heal_actions(max_attempts)
        if action_groups:
            await _trace_self_heal_event(
                {
                    "phase": "trigger",
                    "trigger": "empty_reply",
                    "max_attempts": max_attempts,
                    "bytes_before": _estimate_request_body_bytes(final_request_body),
                    "tokens_before": _estimate_messages_tokens(list(final_request_body.get("messages") or [])),
                }
            )

            healed_body = copy.deepcopy(final_request_body)
            last_exc: Optional[BaseException] = None
            last_parsed: Optional[ParsedCompletionResponse] = None

            for idx, actions in enumerate(action_groups, start=1):
                for act in actions:
                    if act == "shrink_transcript":
                        _shrink_transcript_in_body(healed_body)
                    elif act == "drop_tools":
                        _drop_tools_in_body(healed_body)
                    elif act == "drop_images":
                        _drop_images_in_body(healed_body)
                    elif act == "minimal_context":
                        _minimal_context_in_body(healed_body)

                await _trace_self_heal_event(
                    {
                        "phase": "attempt",
                        "attempt": idx,
                        "actions": list(actions),
                        "bytes": _estimate_request_body_bytes(healed_body),
                        "tokens": _estimate_messages_tokens(list(healed_body.get("messages") or [])),
                    }
                )

                try:
                    last_parsed = await _run_post_and_parse(
                        healed_body,
                        phase=f"自愈#{idx}({'+'.join(actions)})",
                    )
                    last_exc = None
                except Exception as exc:
                    last_exc = exc
                    should, reason = _is_self_heal_exception(exc)
                    await _trace_self_heal_event(
                        {
                            "phase": "attempt_error",
                            "attempt": idx,
                            "actions": list(actions),
                            "kind": reason or "unknown",
                            "err": str(exc),
                        }
                    )
                    if should:
                        continue
                    raise

                if last_parsed.tool_calls:
                    await _trace_self_heal_event(
                        {
                            "phase": "success",
                            "attempt": idx,
                            "actions": list(actions),
                            "result": "tool_calls",
                        }
                    )
                    return last_parsed.assistant_message, last_parsed.tool_calls, api_key
                if last_parsed.content and str(last_parsed.content).strip():
                    await _trace_self_heal_event(
                        {
                            "phase": "success",
                            "attempt": idx,
                            "actions": list(actions),
                            "result": "content",
                            "reply_len": len(str(last_parsed.content)),
                        }
                    )
                    return last_parsed.assistant_message, None, api_key

                await _trace_self_heal_event(
                    {
                        "phase": "attempt_empty",
                        "attempt": idx,
                        "actions": list(actions),
                    }
                )

            # Exhausted: keep existing empty reply meta and return.
            await _trace_self_heal_event(
                {
                    "phase": "exhausted",
                    "attempts": len(action_groups),
                    "last_error": str(last_exc) if last_exc else "",
                }
            )

    return assistant_message, tool_calls, api_key
