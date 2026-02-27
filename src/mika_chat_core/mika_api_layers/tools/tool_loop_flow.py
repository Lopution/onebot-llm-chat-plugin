"""Mika API - 工具循环流程。"""

from __future__ import annotations

import asyncio
from difflib import SequenceMatcher
import json
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Union

from .tool_executor import get_tool_executor


def is_duplicate_search_query(base_query: str, candidate_query: str) -> bool:
    """判断补搜 query 是否与预搜索 query 高度重复。"""
    base = str(base_query or "").strip().lower()
    candidate = str(candidate_query or "").strip().lower()
    if not base or not candidate:
        return False
    if base == candidate:
        return True
    if base in candidate or candidate in base:
        shorter = min(len(base), len(candidate))
        longer = max(len(base), len(candidate))
        if longer > 0 and shorter / longer >= 0.8:
            return True
    return SequenceMatcher(None, base, candidate).ratio() >= 0.9


def resolve_tool_name_alias(
    requested_name: str,
    *,
    tool_handlers: Dict[str, Callable],
    allowlist: set[str],
) -> str:
    """将 provider 前缀工具名映射为实际注册名（如 google:xxx -> xxx）。"""
    name = str(requested_name or "").strip()
    if not name:
        return ""
    if name in tool_handlers or name in allowlist:
        return name
    if ":" not in name:
        return name
    _, candidate = name.split(":", 1)
    candidate = candidate.strip()
    if not candidate:
        return name
    if candidate in tool_handlers or candidate in allowlist:
        return candidate
    return name


async def handle_tool_calls_flow(
    *,
    messages: List[Dict[str, Any]],
    assistant_message: Dict[str, Any],
    tool_calls: List[Dict[str, Any]],
    api_key: str,
    group_id: Optional[str],
    request_id: str,
    session_key: Optional[str] = None,
    tool_handlers: Dict[str, Callable],
    model: str,
    base_url: str,
    http_client,
    tools: Optional[List[Dict[str, Any]]],
    search_state: Optional[Any],
    return_trace: bool,
    plugin_cfg: Any,
    log_obj: Any,
    metrics_obj: Any,
    emit_agent_hook_fn,
    build_effective_allowlist_fn,
    is_duplicate_search_query_fn,
) -> Union[str, Dict[str, Any]]:
    max_rounds = max(1, int(getattr(plugin_cfg, "mika_tool_max_rounds", 5) or 5))
    tool_timeout = float(getattr(plugin_cfg, "mika_tool_timeout_seconds", 20.0) or 20.0)
    force_final = bool(getattr(plugin_cfg, "mika_tool_force_final_on_max_rounds", True))
    react_enabled = bool(getattr(plugin_cfg, "mika_react_enabled", False))
    if react_enabled:
        react_rounds = max(1, int(getattr(plugin_cfg, "mika_react_max_rounds", max_rounds) or max_rounds))
        max_rounds = max(max_rounds, react_rounds)

    allowlist = build_effective_allowlist_fn(
        getattr(plugin_cfg, "mika_tool_allowlist", []),
        include_dynamic_sources=bool(
            getattr(plugin_cfg, "mika_tool_allow_dynamic_registered", True)
        ),
    )
    search_refine_enabled = bool(getattr(plugin_cfg, "mika_search_allow_tool_refine", True))
    search_refine_max_rounds = max(
        0, int(getattr(plugin_cfg, "mika_search_tool_refine_max_rounds", 1) or 0)
    )

    tool_cache_ttl = float(getattr(plugin_cfg, "mika_tool_cache_ttl_seconds", 60) or 60)
    tool_cache_max_entries = int(getattr(plugin_cfg, "mika_tool_cache_max_entries", 500) or 500)
    # TTL cache requires a stable session_key; otherwise only in-flight de-dupe is used.
    raw_session_key = str(session_key or "").strip()
    tool_cache_enabled = bool(getattr(plugin_cfg, "mika_tool_cache_enabled", True)) and bool(raw_session_key)
    cache_scope = raw_session_key or f"req:{request_id}"
    tool_executor = get_tool_executor()

    current_assistant_message = assistant_message
    current_tool_calls = list(tool_calls or [])
    trace_messages: List[Dict[str, Any]] = []
    schema_mismatch_suspected = False

    round_idx = 0
    while current_tool_calls:
        round_idx += 1
        log_obj.info(
            f"[req:{request_id}] 模型请求调用 {len(current_tool_calls)} 个工具 | round={round_idx}/{max_rounds}"
        )
        metrics_obj.tool_calls_total += len(current_tool_calls)

        messages.append(current_assistant_message)
        trace_messages.append(dict(current_assistant_message))

        for tool_call in current_tool_calls:
            function_name = str(tool_call["function"]["name"] or "")
            effective_function_name = resolve_tool_name_alias(
                function_name,
                tool_handlers=tool_handlers,
                allowlist=allowlist,
            )
            function_args = tool_call["function"].get("arguments", "{}")
            tool_call_id = tool_call.get("id", str(uuid.uuid4())[:8])
            tool_started_at = time.monotonic()

            if effective_function_name != function_name:
                log_obj.info(
                    f"[req:{request_id}] 工具名映射: {function_name} -> {effective_function_name}"
                )

            log_obj.debug(f"[req:{request_id}] 执行工具: {function_name} | args={function_args}")
            await emit_agent_hook_fn(
                "on_tool_start",
                {
                    "request_id": request_id,
                    "group_id": str(group_id or ""),
                    "session_key": raw_session_key,
                    "round_index": round_idx,
                    "tool_call_id": str(tool_call_id),
                    "tool_name": str(function_name or ""),
                    "raw_arguments": function_args if isinstance(function_args, str) else json.dumps(function_args, ensure_ascii=False),
                },
            )

            try:
                args = json.loads(function_args) if isinstance(function_args, str) else function_args
            except json.JSONDecodeError:
                args = {"query": function_args}
                schema_mismatch_suspected = True

            tool_result = ""
            tool_ok = False
            tool_error = ""
            cache_hit = False
            inflight_deduped = False
            if allowlist and function_name not in allowlist and effective_function_name not in allowlist:
                tool_result = f"工具调用被拒绝: {function_name}"
                log_obj.warning(f"[req:{request_id}] 工具未在白名单中: {function_name}")
                metrics_obj.tool_blocked_total += 1
                tool_error = "blocked_by_allowlist"
            elif effective_function_name == "web_search" and search_state is not None:
                from ...utils.search_engine import normalize_search_query

                raw_query = str((args or {}).get("query") or "")
                normalized_query = normalize_search_query(raw_query)
                base_query = str(getattr(search_state, "normalized_query", "") or "")
                presearch_hit = bool(getattr(search_state, "presearch_hit", False))
                allow_refine = bool(getattr(search_state, "allow_tool_refine", False))
                refine_used = int(getattr(search_state, "refine_rounds_used", 0) or 0)

                blocked_reason = ""
                if presearch_hit and (not search_refine_enabled or not allow_refine):
                    blocked_reason = "policy_block"
                elif presearch_hit and refine_used >= search_refine_max_rounds:
                    blocked_reason = "max_rounds_reached"
                elif presearch_hit and is_duplicate_search_query_fn(base_query, normalized_query):
                    blocked_reason = "duplicate_query"

                if blocked_reason:
                    tool_result = (
                        "本轮已存在预搜索结果，重复外搜已跳过。请基于现有结果回答；"
                        "若仍不足，请要求用户补充更具体关键词。"
                    )
                    metrics_obj.tool_blocked_total += 1
                    if blocked_reason == "duplicate_query":
                        setattr(
                            search_state,
                            "blocked_duplicate_total",
                            int(getattr(search_state, "blocked_duplicate_total", 0) or 0) + 1,
                        )
                    log_obj.info(
                        f"[req:{request_id}] search_decision phase=tool_loop blocked={blocked_reason} "
                        f"query='{normalized_query or raw_query}' prequery='{base_query}' "
                        f"refine_used={refine_used}/{search_refine_max_rounds}"
                    )
                    tool_error = f"search_refine_{blocked_reason}"
                elif effective_function_name in tool_handlers:
                    try:
                        handler = tool_handlers[effective_function_name]
                        async def _run() -> str:
                            if tool_timeout > 0:
                                out = await asyncio.wait_for(handler(args, group_id), timeout=tool_timeout)
                            else:
                                out = await handler(args, group_id)
                            out = str(out or "")
                            max_chars = max(200, int(plugin_cfg.mika_tool_result_max_chars))
                            if len(out) > max_chars:
                                out = out[:max_chars] + "..."
                            return out

                        tool_result, cache_hit, inflight_deduped = await tool_executor.execute(
                            cache_enabled=tool_cache_enabled,
                            cache_ttl_seconds=tool_cache_ttl,
                            cache_max_entries=tool_cache_max_entries,
                            cache_scope=cache_scope,
                            tool_name=effective_function_name,
                            args=args,
                            run=_run,
                        )

                        setattr(search_state, "refine_rounds_used", refine_used + 1)
                        log_obj.info(
                            f"[req:{request_id}] search_decision phase=tool_loop refine_used="
                            f"{int(getattr(search_state, 'refine_rounds_used', 0) or 0)}/{search_refine_max_rounds} "
                            f"query='{normalized_query or raw_query}'"
                        )

                        log_obj.success(
                            f"[req:{request_id}] 工具 {function_name} 执行成功 | result_len={len(tool_result)}"
                        )
                        tool_ok = True
                    except asyncio.TimeoutError:
                        tool_result = f"工具执行超时: {function_name}"
                        log_obj.error(f"[req:{request_id}] 工具 {function_name} 执行超时")
                        tool_error = "tool_timeout"
                    except Exception as exc:
                        tool_result = f"工具执行失败: {str(exc)}"
                        log_obj.error(f"[req:{request_id}] 工具 {function_name} 执行失败: {exc}")
                        tool_error = str(type(exc).__name__)
                        if type(exc).__name__ in {"TypeError", "ValueError", "KeyError"}:
                            schema_mismatch_suspected = True
                else:
                    tool_result = f"未注册的工具: {function_name}"
                    log_obj.warning(f"[req:{request_id}] 未注册的工具: {function_name}")
                    metrics_obj.tool_blocked_total += 1
                    tool_error = "tool_not_registered"
                    schema_mismatch_suspected = True
            elif effective_function_name in tool_handlers:
                try:
                    handler = tool_handlers[effective_function_name]
                    async def _run() -> str:
                        if tool_timeout > 0:
                            out = await asyncio.wait_for(handler(args, group_id), timeout=tool_timeout)
                        else:
                            out = await handler(args, group_id)
                        out = str(out or "")
                        max_chars = max(200, int(plugin_cfg.mika_tool_result_max_chars))
                        if len(out) > max_chars:
                            out = out[:max_chars] + "..."
                        return out

                    tool_result, cache_hit, inflight_deduped = await tool_executor.execute(
                        cache_enabled=tool_cache_enabled,
                        cache_ttl_seconds=tool_cache_ttl,
                        cache_max_entries=tool_cache_max_entries,
                        cache_scope=cache_scope,
                        tool_name=effective_function_name,
                        args=args,
                        run=_run,
                    )

                    log_obj.success(
                        f"[req:{request_id}] 工具 {function_name} 执行成功 | result_len={len(tool_result)}"
                    )
                    tool_ok = True
                except asyncio.TimeoutError:
                    tool_result = f"工具执行超时: {function_name}"
                    log_obj.error(f"[req:{request_id}] 工具 {function_name} 执行超时")
                    tool_error = "tool_timeout"
                except Exception as exc:
                    tool_result = f"工具执行失败: {str(exc)}"
                    log_obj.error(f"[req:{request_id}] 工具 {function_name} 执行失败: {exc}")
                    tool_error = str(type(exc).__name__)
                    if type(exc).__name__ in {"TypeError", "ValueError", "KeyError"}:
                        schema_mismatch_suspected = True
            else:
                tool_result = f"未注册的工具: {function_name}"
                log_obj.warning(f"[req:{request_id}] 未注册的工具: {function_name}")
                metrics_obj.tool_blocked_total += 1
                tool_error = "tool_not_registered"
                schema_mismatch_suspected = True

            await emit_agent_hook_fn(
                "on_tool_end",
                {
                    "request_id": request_id,
                    "group_id": str(group_id or ""),
                    "session_key": raw_session_key,
                    "round_index": round_idx,
                    "tool_call_id": str(tool_call_id),
                    "tool_name": str(function_name or ""),
                    "ok": bool(tool_ok),
                    "error": str(tool_error or ""),
                    "result_length": len(str(tool_result or "")),
                    "duration_ms": int(max(0.0, time.monotonic() - tool_started_at) * 1000),
                    "cache_hit": bool(cache_hit),
                    "inflight_deduped": bool(inflight_deduped),
                },
            )

            tool_message = {
                "role": "tool",
                "name": function_name,
                "tool_call_id": tool_call_id,
                "content": tool_result,
            }
            messages.append(tool_message)
            trace_messages.append(tool_message)

        if react_enabled:
            reflect_prompt = {
                "role": "user",
                "content": (
                    "请先内部完成 Observe/Reflect："
                    "判断工具结果是否足够回答用户；不足则继续调用工具，足够则直接给出最终答案。"
                ),
            }
            messages.append(reflect_prompt)
            trace_messages.append(reflect_prompt)

        log_obj.debug(f"[req:{request_id}] 发送工具结果，获取下一步回复")
        next_request_body: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "temperature": getattr(plugin_cfg, "mika_temperature", 1.0),
        }
        if tools is not None:
            next_request_body["tools"] = tools

        from ..transport.facade import send_api_request

        next_message, next_tool_calls, _ = await send_api_request(
            http_client=http_client,
            request_body=next_request_body,
            request_id=request_id,
            retry_count=0,
            api_key=api_key,
            base_url=base_url,
            model=model,
        )
        choice = {"message": next_message, "finish_reason": "unknown"}
        next_tool_calls = next_tool_calls or []

        log_obj.debug(
            f"[req:{request_id}] tool-loop 响应 | "
            f"content_len={len(next_message.get('content') or '')} | "
            f"has_tool_calls={bool(next_tool_calls)} | finish_reason={choice.get('finish_reason')}"
        )

        if next_tool_calls:
            if round_idx >= max_rounds:
                if not force_final:
                    log_obj.warning(
                        f"[req:{request_id}] 工具调用达到上限({max_rounds})，且未启用强制最终答复，直接返回当前 content"
                    )
                    reply_text = next_message.get("content") or ""
                    if return_trace:
                        return {
                            "reply": reply_text,
                            "trace_messages": trace_messages,
                            "schema_mismatch_suspected": schema_mismatch_suspected,
                        }
                    return reply_text

                log_obj.warning(
                    f"[req:{request_id}] 工具调用达到上限({max_rounds})，强制模型停止使用工具并给出最终答复"
                )
                messages.append(
                    {
                        "role": "user",
                        "content": "工具调用次数已达到上限，请停止使用工具，并根据已经收集到的信息，对你的任务和发现进行总结，然后直接回复用户。",
                    }
                )
                final_request_body: Dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "stream": False,
                    "temperature": getattr(plugin_cfg, "mika_temperature", 1.0),
                }
                from ..transport.facade import send_api_request

                final_message, _, _ = await send_api_request(
                    http_client=http_client,
                    request_body=final_request_body,
                    request_id=request_id,
                    retry_count=0,
                    api_key=api_key,
                    base_url=base_url,
                    model=model,
                )
                final_reply = final_message.get("content") or ""
                trace_messages.append(dict(final_message))
                if return_trace:
                    return {
                        "reply": final_reply,
                        "trace_messages": trace_messages,
                        "schema_mismatch_suspected": schema_mismatch_suspected,
                    }
                return final_reply

            current_assistant_message = next_message
            current_tool_calls = list(next_tool_calls)
            continue

        reply_text = next_message.get("content") or ""
        trace_messages.append(dict(next_message))
        if return_trace:
            return {
                "reply": reply_text,
                "trace_messages": trace_messages,
                "schema_mismatch_suspected": schema_mismatch_suspected,
            }
        return reply_text

    fallback = current_assistant_message.get("content") or ""
    if return_trace:
        return {
            "reply": fallback,
            "trace_messages": trace_messages,
            "schema_mismatch_suspected": schema_mismatch_suspected,
        }
    return fallback
