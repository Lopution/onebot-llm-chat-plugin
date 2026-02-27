"""Mika API - chat 主流程编排。"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol

from ...errors import ServerError


class ChatOrchestratorClient(Protocol):
    model: str
    _runtime_system_prompt_override: str
    _chat_history_summarizer: Any

    async def _log_context_diagnostics(self, user_id: str, group_id: Optional[str], request_id: str) -> None: ...
    async def _build_prompt_context_values(self, *, message: str, user_id: str, group_id: Optional[str]) -> Dict[str, Any]: ...
    def _coerce_pre_search_result(self, raw_result: Any, *, message: str, decision: str = "compat") -> Any: ...
    async def _pre_search(self, message: str, enable_tools: bool, request_id: str, user_id: str = None, group_id: str = None) -> Any: ...
    def _log_search_result_status(self, search_result: str, request_id: str) -> None: ...
    def _log_search_decision(self, request_id: str, search_state: Any, *, phase: str) -> None: ...
    async def _inject_memory_retrieval_context(self, *, message: str, user_id: str, group_id: Optional[str], request_id: str, system_injection: Optional[str]) -> Optional[str]: ...
    async def _inject_long_term_memory(self, *, message: str, user_id: str, group_id: Optional[str], request_id: str, system_injection: Optional[str]) -> Optional[str]: ...
    async def _inject_knowledge_context(self, *, message: str, user_id: str, group_id: Optional[str], request_id: str, system_injection: Optional[str]) -> Optional[str]: ...
    def _render_system_prompt_with_context(self) -> str: ...
    async def _build_messages(self, message: str, user_id: str, group_id: Optional[str], image_urls: Optional[List[str]], search_result: str, session_key: Optional[str] = None, enable_tools: bool = True, system_prompt_override: Optional[str] = None, system_injection: Optional[str] = None, context_level: int = 0, history_override: Optional[List[Dict[str, Any]]] = None) -> tuple: ...
    def _log_request_messages(self, messages: List[Dict[str, Any]], api_content: Any, request_id: str) -> None: ...
    async def _send_api_request(self, request_body: Dict[str, Any], request_id: str, retry_count: int, message: str, user_id: str, group_id: Optional[str], image_urls: Optional[List[str]], enable_tools: bool, stream_handler: Optional[Callable[[str], Awaitable[None]]] = None) -> tuple: ...
    async def _handle_server_error_retry(self, error: ServerError, message: str, user_id: str, group_id: Optional[str], image_urls: Optional[List[str]], enable_tools: bool, retry_count: int, message_id: Optional[str], system_injection: Optional[str], context_level: int, history_override: Optional[List[Dict[str, Any]]] = None, search_result: Optional[str] = None) -> Optional[str]: ...
    async def _resolve_reply(self, messages: List[Dict[str, Any]], assistant_message: Dict[str, Any], tool_calls: List[Dict[str, Any]], api_key: str, group_id: Optional[str], request_id: str, enable_tools: bool, tools: Optional[List[Dict[str, Any]]] = None, search_state: Optional[Any] = None, session_key: Optional[str] = None) -> tuple: ...
    def _log_raw_model_reply(self, reply: str, request_id: str) -> None: ...
    def _process_response(self, reply: str, request_id: str) -> str: ...
    async def _handle_empty_reply_retry(self, request_id: str, start_time: float, message: str, user_id: str, group_id: Optional[str], image_urls: Optional[List[str]], enable_tools: bool, retry_count: int, message_id: Optional[str], system_injection: Optional[str], context_level: int, history_override: Optional[List[Dict[str, Any]]], search_result: str) -> Optional[str]: ...
    def _get_error_message(self, error_type: str) -> str: ...
    async def _update_context(self, user_id: str, group_id: Optional[str], current_content: Any, reply: str, user_message_id: Optional[str] = None, tool_trace: Optional[List[Dict[str, Any]]] = None) -> None: ...
    def _memory_session_key(self, user_id: str, group_id: Optional[str]) -> str: ...
    def _should_extract_memory(self, session_key: str, interval: int) -> bool: ...
    async def _extract_and_store_memories(self, *, messages: List[Dict[str, Any]], user_id: str, group_id: Optional[str], request_id: str) -> None: ...
    async def _get_context_async(self, user_id: str, group_id: Optional[str] = None) -> List[Dict[str, Any]]: ...
    async def _run_topic_summary(self, *, session_key: str, messages: List[Dict[str, Any]], llm_cfg: Dict[str, Any], request_id: str) -> None: ...
    def _log_request_success(self, request_id: str, start_time: float, reply: str, tool_calls: List[Dict[str, Any]]) -> None: ...


async def run_chat_main_loop(
    *,
    client: ChatOrchestratorClient,
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
    search_result_override: Optional[str],
    stream_handler: Optional[Callable[[str], Awaitable[None]]],
    request_id: str,
    start_time: float,
    session_key: str,
    plugin_cfg: Any,
    emit_agent_hook_fn: Callable[..., Awaitable[Any]],
    update_prompt_context_fn: Callable[[Dict[str, Any]], Any],
    get_dream_scheduler_fn: Callable[[], Any],
    log_obj: Any,
) -> str:
    await client._log_context_diagnostics(user_id, group_id, request_id)
    update_prompt_context_fn(
        await client._build_prompt_context_values(
            message=message,
            user_id=user_id,
            group_id=group_id,
        )
    )

    if search_result_override is None:
        search_state = client._coerce_pre_search_result(
            await client._pre_search(
                message,
                enable_tools,
                request_id,
                user_id=user_id,
                group_id=group_id,
            ),
            message=message,
            decision="presearch",
        )
        search_result = search_state.search_result
    else:
        search_state = client._coerce_pre_search_result(
            search_result_override,
            message=message,
            decision="override",
        )
        search_result = search_state.search_result
        log_obj.info(
            f"[req:{request_id}] 复用首轮搜索判定结果，跳过重复分类/搜索 | "
            f"search_injected={'yes' if bool(search_result) else 'no'}"
        )

    client._log_search_result_status(search_result, request_id)
    client._log_search_decision(request_id, search_state, phase="pre_send")

    # -------------------- Retrieval pipeline (plan-driven) --------------------
    # Align with MaiBot/AstrBot: store full history, but inject a controlled working set.
    # The planner owns "whether to retrieve / inject knowledge"; injection is best-effort.
    try:
        from ...memory.retrieval_pipeline import apply_retrieval_pipeline
        from ...planning.planner import build_request_plan

        plan_for_injection = build_request_plan(
            plugin_cfg=plugin_cfg,
            enable_tools=bool(enable_tools),
            is_proactive=False,
            message=message,
            image_urls_count=len(list(image_urls or [])),
            system_injection=system_injection,
        )
        system_injection = await apply_retrieval_pipeline(
            client=client,
            plan=plan_for_injection,
            message=message,
            user_id=user_id,
            group_id=group_id,
            request_id=request_id,
            system_injection=system_injection,
        )
    except Exception:
        # Legacy fallback (should rarely happen).
        if bool(getattr(plugin_cfg, "mika_memory_retrieval_enabled", False)):
            system_injection = await client._inject_memory_retrieval_context(
                message=message,
                user_id=user_id,
                group_id=group_id,
                request_id=request_id,
                system_injection=system_injection,
            )
        else:
            system_injection = await client._inject_long_term_memory(
                message=message,
                user_id=user_id,
                group_id=group_id,
                request_id=request_id,
                system_injection=system_injection,
            )
            system_injection = await client._inject_knowledge_context(
                message=message,
                user_id=user_id,
                group_id=group_id,
                request_id=request_id,
                system_injection=system_injection,
            )
    update_prompt_context_fn({"system_injection": system_injection or ""})

    # -------------------- Request Plan (heuristic) --------------------
    # Best-effort: this should never block the main chat flow.
    try:
        if bool(getattr(plugin_cfg, "mika_planner_enabled", True)):
            from ...observability.trace_store import get_trace_store
            from ...planning.planner import build_request_plan

            plan = build_request_plan(
                plugin_cfg=plugin_cfg,
                enable_tools=bool(enable_tools),
                is_proactive=False,
                message=message,
                image_urls_count=len(list(image_urls or [])),
                system_injection=system_injection,
            )
            await get_trace_store().set_plan(
                request_id=request_id,
                session_key=session_key,
                user_id=str(user_id or ""),
                group_id=str(group_id or ""),
                plan=plan.to_dict(),
            )
    except Exception:
        pass

    rendered_system_prompt = client._render_system_prompt_with_context()
    client._runtime_system_prompt_override = rendered_system_prompt

    messages, original_content, api_content, request_body = await client._build_messages(
        message=message,
        user_id=user_id,
        group_id=group_id,
        image_urls=image_urls,
        search_result=search_result,
        session_key=session_key,
        enable_tools=enable_tools,
        system_injection=system_injection,
        context_level=context_level,
        history_override=history_override,
    )

    client._log_request_messages(messages, api_content, request_id)

    # Add request budget estimates into trace hooks for easier debugging.
    estimated_request_bytes = 0
    estimated_message_tokens = 0
    try:
        import json

        dumped = json.dumps(request_body, ensure_ascii=False, separators=(",", ":"))
        estimated_request_bytes = len(dumped.encode("utf-8"))
    except Exception:
        estimated_request_bytes = 0
    try:
        from ...utils.context_schema import estimate_message_tokens

        for m in messages:
            if not isinstance(m, dict):
                continue
            estimated_message_tokens += int(estimate_message_tokens(m))
    except Exception:
        estimated_message_tokens = 0

    hook_base_payload: Dict[str, Any] = {
        "request_id": request_id,
        "user_id": str(user_id or ""),
        "group_id": str(group_id or ""),
        "model": str(request_body.get("model") or client.model),
        "enable_tools": bool(enable_tools),
        "context_level": int(context_level),
        "estimated_request_bytes": int(estimated_request_bytes),
        "estimated_message_tokens": int(estimated_message_tokens),
    }
    await emit_agent_hook_fn(
        "on_before_llm",
        {
            **hook_base_payload,
            "message_count": len(messages),
            "tool_count": len(request_body.get("tools") or []),
        },
    )
    try:
        assistant_message, tool_calls, api_key = await client._send_api_request(
            request_body,
            request_id,
            retry_count,
            message,
            user_id,
            group_id,
            image_urls,
            enable_tools,
            stream_handler=stream_handler,
        )
        await emit_agent_hook_fn(
            "on_after_llm",
            {
                **hook_base_payload,
                "ok": True,
                "tool_calls_count": len(tool_calls or []),
                "content_len": len(str(assistant_message.get("content") or "")),
            },
        )
    except ServerError as e:
        await emit_agent_hook_fn(
            "on_after_llm",
            {
                **hook_base_payload,
                "ok": False,
                "error_type": type(e).__name__,
                "error_message": str(getattr(e, "message", e)),
                "status_code": int(getattr(e, "status_code", 0) or 0),
            },
        )
        retry_reply = await client._handle_server_error_retry(
            e,
            message=message,
            user_id=user_id,
            group_id=group_id,
            image_urls=image_urls,
            enable_tools=enable_tools,
            retry_count=retry_count,
            message_id=message_id,
            system_injection=system_injection,
            context_level=context_level,
            history_override=history_override,
            search_result=search_result,
        )
        if retry_reply is not None:
            return retry_reply
        raise
    except Exception as e:
        await emit_agent_hook_fn(
            "on_after_llm",
            {
                **hook_base_payload,
                "ok": False,
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
        )
        raise

    reply, tool_trace = await client._resolve_reply(
        messages=messages,
        assistant_message=assistant_message,
        tool_calls=tool_calls,
        api_key=api_key,
        group_id=group_id,
        request_id=request_id,
        enable_tools=enable_tools,
        tools=request_body.get("tools"),
        search_state=search_state,
        session_key=session_key,
    )
    client._log_search_decision(request_id, search_state, phase="post_reply")

    client._log_raw_model_reply(reply, request_id)
    reply = client._process_response(reply, request_id)

    if not reply:
        empty_meta = assistant_message.get("_empty_reply_meta") if isinstance(assistant_message, dict) else None
        if isinstance(empty_meta, dict):
            log_obj.warning(
                f"[req:{request_id}] transport_empty_meta | kind={empty_meta.get('kind', '')} | "
                f"finish={empty_meta.get('finish_reason', '') or 'unknown'} | "
                f"local_retries={empty_meta.get('local_retries', 0)} | "
                f"response_id={empty_meta.get('response_id', '') or '-'}"
            )
        retry_reply = await client._handle_empty_reply_retry(
            request_id=request_id,
            start_time=start_time,
            message=message,
            user_id=user_id,
            group_id=group_id,
            image_urls=image_urls,
            enable_tools=enable_tools,
            retry_count=retry_count,
            message_id=message_id,
            system_injection=system_injection,
            context_level=context_level,
            history_override=history_override,
            search_result=search_result,
        )
        if retry_reply is not None:
            return retry_reply
        log_obj.error(f"[req:{request_id}] 所有上下文降级层级都失败，返回错误消息")
        return client._get_error_message("empty_reply")

    await client._update_context(
        user_id,
        group_id,
        original_content,
        reply,
        message_id,
        tool_trace=tool_trace,
    )

    from ...runtime import get_task_supervisor

    if getattr(plugin_cfg, "mika_memory_enabled", False):
        session_key_for_extract = client._memory_session_key(user_id, group_id)
        extract_interval = int(getattr(plugin_cfg, "mika_memory_extract_interval", 3) or 3)
        if client._should_extract_memory(session_key_for_extract, extract_interval):
            extract_messages: List[Dict[str, Any]] = [
                {"role": "user", "content": original_content},
                {"role": "assistant", "content": reply},
            ]

            get_task_supervisor().spawn(
                client._extract_and_store_memories(
                    messages=extract_messages,
                    user_id=user_id,
                    group_id=group_id,
                    request_id=request_id,
                ),
                name="memory_extract",
                owner="chat_postprocess",
                key=f"mem:{session_key_for_extract}",
            )

    if (
        group_id
        and bool(getattr(plugin_cfg, "mika_topic_summary_enabled", False))
        and client._chat_history_summarizer is not None
    ):
        try:
            summary_messages = await client._get_context_async(user_id, group_id)
        except Exception:
            log.debug("topic_summary context fetch failed, using empty", exc_info=True)
            summary_messages = []
        if summary_messages:
            summary_llm_cfg = plugin_cfg.get_llm_config()
            summary_session_key = client._memory_session_key(user_id, group_id)
            get_task_supervisor().spawn(
                client._run_topic_summary(
                    session_key=summary_session_key,
                    messages=list(summary_messages),
                    llm_cfg=summary_llm_cfg,
                    request_id=request_id,
                ),
                name="topic_summary",
                owner="chat_postprocess",
                key=f"topic:{summary_session_key}",
            )

    if bool(getattr(plugin_cfg, "mika_dream_enabled", False)):
        session_key_for_dream = client._memory_session_key(user_id, group_id)
        await get_dream_scheduler_fn().on_session_activity(
            session_key=session_key_for_dream,
            enabled=bool(getattr(plugin_cfg, "mika_dream_enabled", False)),
            idle_minutes=int(getattr(plugin_cfg, "mika_dream_idle_minutes", 30) or 30),
            max_iterations=int(getattr(plugin_cfg, "mika_dream_max_iterations", 5) or 5),
            request_id=request_id,
        )

    if search_result:
        log_obj.debug(
            f"[req:{request_id}] 上下文已更新（已分离搜索结果）| "
            f"saved_len={len(str(original_content))} | "
            f"api_len={len(str(api_content))}"
        )

    client._log_request_success(request_id, start_time, reply, tool_calls)
    return reply
