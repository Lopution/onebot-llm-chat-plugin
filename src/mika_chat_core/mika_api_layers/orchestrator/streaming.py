"""Mika API - 流式聊天编排。"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional


async def chat_stream_flow(
    *,
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
    chat_caller: Callable[..., Awaitable[str]],
    log_obj: Any,
) -> AsyncIterator[str]:
    """流式聊天入口。"""
    if enable_tools:
        log_obj.warning("chat_stream 在 enable_tools=True 时回退为非流式响应")
        reply = await chat_caller(
            message=message,
            user_id=user_id,
            group_id=group_id,
            image_urls=image_urls,
            enable_tools=True,
            retry_count=retry_count,
            message_id=message_id,
            system_injection=system_injection,
            context_level=context_level,
            history_override=history_override,
            search_result_override=search_result_override,
        )
        if reply:
            yield reply
        return

    queue: asyncio.Queue[Any] = asyncio.Queue()
    sentinel = object()
    stream_error: Dict[str, Exception] = {}
    emitted_any = False

    async def _on_delta(delta: str) -> None:
        nonlocal emitted_any
        emitted_any = True
        await queue.put(str(delta))

    async def _run_chat() -> None:
        try:
            final_reply = await chat_caller(
                message=message,
                user_id=user_id,
                group_id=group_id,
                image_urls=image_urls,
                enable_tools=False,
                retry_count=retry_count,
                message_id=message_id,
                system_injection=system_injection,
                context_level=context_level,
                history_override=history_override,
                search_result_override=search_result_override,
                _stream_handler=_on_delta,
            )
            if (not emitted_any) and str(final_reply or "").strip():
                await queue.put(str(final_reply))
        except Exception as exc:
            stream_error["error"] = exc
        finally:
            await queue.put(sentinel)

    worker = asyncio.create_task(_run_chat())
    try:
        while True:
            item = await queue.get()
            if item is sentinel:
                break
            if item is None:
                continue
            yield str(item)
        if "error" in stream_error:
            raise stream_error["error"]
    finally:
        await worker
