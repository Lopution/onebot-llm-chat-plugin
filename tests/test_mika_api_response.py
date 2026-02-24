import types
from unittest.mock import AsyncMock

import httpx
import pytest

from mika_chat_core.errors import MikaAPIError
from mika_chat_core.mika_api_layers.core.response import (
    handle_empty_reply_retry,
    handle_error,
    process_response,
)


def test_process_response_cleans_markdown_and_tags():
    reply = "**你好**\n[Mika]: `代码`\n[搜索中]"
    cleaned = process_response(
        reply=reply,
        request_id="req-1",
        clean_thinking_markers=lambda s: s,
    )
    assert "**" not in cleaned
    assert "[Mika]" not in cleaned
    assert "[搜索中]" not in cleaned
    assert "你好" in cleaned
    assert "代码" in cleaned


def test_handle_error_maps_timeout_and_content_filter():
    get_error_message = lambda key: f"err:{key}"

    timeout_text = handle_error(
        error=httpx.TimeoutException("timeout"),
        request_id="req-timeout",
        start_time=0.0,
        get_error_message=get_error_message,
        error_response_body_preview_chars=50,
    )
    assert timeout_text == "err:timeout"

    content_filter_text = handle_error(
        error=MikaAPIError("content filtered by policy", status_code=400),
        request_id="req-filter",
        start_time=0.0,
        get_error_message=get_error_message,
        error_response_body_preview_chars=50,
    )
    assert content_filter_text == "err:content_filter"


@pytest.mark.asyncio
async def test_handle_empty_reply_retry_disabled():
    plugin_cfg = types.SimpleNamespace(mika_empty_reply_context_degrade_enabled=False)
    metrics_obj = types.SimpleNamespace(api_empty_reply_reason_total={})
    chat_caller = AsyncMock(return_value="ok")

    result = await handle_empty_reply_retry(
        request_id="req-disable",
        start_time=0.0,
        message="hello",
        user_id="u1",
        group_id="g1",
        image_urls=None,
        enable_tools=True,
        retry_count=1,
        message_id="m1",
        system_injection=None,
        context_level=0,
        history_override=None,
        search_result="",
        plugin_cfg=plugin_cfg,
        metrics_obj=metrics_obj,
        max_context_degradation_level=2,
        empty_reply_retry_delay_seconds=0.0,
        chat_caller=chat_caller,
    )

    assert result is None
    chat_caller.assert_not_called()


@pytest.mark.asyncio
async def test_handle_empty_reply_retry_enabled_calls_chat():
    plugin_cfg = types.SimpleNamespace(
        mika_empty_reply_context_degrade_enabled=True,
        mika_empty_reply_context_degrade_max_level=2,
    )
    metrics_obj = types.SimpleNamespace(api_empty_reply_reason_total={})
    chat_caller = AsyncMock(return_value="retry-ok")

    result = await handle_empty_reply_retry(
        request_id="req-enable",
        start_time=0.0,
        message="hello",
        user_id="u1",
        group_id="g1",
        image_urls=None,
        enable_tools=True,
        retry_count=1,
        message_id="m1",
        system_injection="sys",
        context_level=0,
        history_override=[{"role": "user", "content": "old"}],
        search_result="cached-search",
        plugin_cfg=plugin_cfg,
        metrics_obj=metrics_obj,
        max_context_degradation_level=2,
        empty_reply_retry_delay_seconds=0.0,
        chat_caller=chat_caller,
    )

    assert result == "retry-ok"
    assert metrics_obj.api_empty_reply_reason_total["context_degrade"] == 1
    chat_caller.assert_awaited_once()
    call = chat_caller.await_args.kwargs
    assert call["context_level"] == 1
    assert call["search_result_override"] == "cached-search"
