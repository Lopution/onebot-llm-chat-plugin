"""传输层自愈（transport self-heal）测试。

重点验证：
- 空回复触发自愈后，能通过降级（drop_tools 等）恢复出有效 content。
- 413 / request too large 触发自愈后，能通过 drop_images 恢复请求。
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import patch

import httpx
import pytest


def _has_image_parts(body: Dict[str, Any]) -> bool:
    msgs = body.get("messages") or []
    for msg in msgs:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and str(part.get("type") or "").lower() == "image_url":
                    return True
    return False


def _make_parsed(content: Any):
    from mika_chat_core.mika_api_layers.transport.completion import ParsedCompletionResponse

    assistant_message = {"role": "assistant", "content": content}
    choice = {"message": assistant_message, "finish_reason": "stop"}
    data = {"id": "resp-1", "choices": [choice], "usage": {}}
    return ParsedCompletionResponse(
        assistant_message=assistant_message,
        tool_calls=None,
        content=content,
        finish_reason="stop",
        reasoning_content=None,
        choice=choice,
        data=data,
    )


@pytest.mark.asyncio
async def test_transport_self_heal_drop_tools_recovers_from_empty_reply():
    from mika_chat_core.config import plugin_config
    from mika_chat_core.mika_api_layers.transport.completion import send_api_request_flow
    from mika_chat_core.utils.transcript_builder import TRANSCRIPT_HEADER, TRANSCRIPT_FOOTER

    request_body = {
        "model": "gpt-test",
        "messages": [
            {"role": "system", "content": "sys"},
            {
                "role": "system",
                "content": f"{TRANSCRIPT_HEADER}\nU: hi\n{TRANSCRIPT_FOOTER}",
            },
            {"role": "user", "content": "hello"},
        ],
        "tools": [{"type": "function", "function": {"name": "t", "description": "x", "parameters": {}}}],
        "stream": False,
    }

    calls: list[dict[str, Any]] = []

    async def fake_post_and_parse(*, body: Dict[str, Any], phase: str, **kwargs):
        calls.append({"phase": phase, "tools_len": len(body.get("tools") or [])})
        if body.get("tools"):
            return _make_parsed(None)
        return _make_parsed("ok")

    old_local_retries = plugin_config.mika_empty_reply_local_retries
    old_enabled = plugin_config.mika_transport_self_heal_enabled
    old_max = plugin_config.mika_transport_self_heal_max_attempts
    try:
        plugin_config.mika_empty_reply_local_retries = 0
        plugin_config.mika_transport_self_heal_enabled = True
        plugin_config.mika_transport_self_heal_max_attempts = 3

        with patch(
            "mika_chat_core.mika_api_layers.transport.completion._post_and_parse",
            new=fake_post_and_parse,
        ):
            async with httpx.AsyncClient() as client:
                assistant_message, tool_calls, _ = await send_api_request_flow(
                    http_client=client,
                    request_body=request_body,
                    request_id="req-1",
                    retry_count=0,
                    api_key="A" * 32,
                    base_url="https://example.invalid",
                    model="gpt-test",
                )
    finally:
        plugin_config.mika_empty_reply_local_retries = old_local_retries
        plugin_config.mika_transport_self_heal_enabled = old_enabled
        plugin_config.mika_transport_self_heal_max_attempts = old_max

    assert tool_calls is None
    assert assistant_message.get("content") == "ok"
    assert any("自愈" in str(c["phase"]) for c in calls)
    assert any(c["tools_len"] == 0 for c in calls), calls


@pytest.mark.asyncio
async def test_transport_self_heal_drop_images_recovers_from_413():
    from mika_chat_core.config import plugin_config
    from mika_chat_core.mika_api_layers.transport.completion import send_api_request_flow

    request_body = {
        "model": "gpt-test",
        "messages": [
            {"role": "system", "content": "sys"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "look"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,AAAA"},
                        "mika_media": {"kind": "pic", "picid": "p1"},
                    },
                ],
            },
        ],
        "tools": [],
        "stream": False,
    }

    async def fake_post_and_parse(*, body: Dict[str, Any], phase: str, **kwargs):
        if _has_image_parts(body):
            resp = httpx.Response(status_code=413, text="payload too large")
            raise httpx.HTTPStatusError("Payload Too Large", request=None, response=resp)
        return _make_parsed("ok")

    old_enabled = plugin_config.mika_transport_self_heal_enabled
    old_max = plugin_config.mika_transport_self_heal_max_attempts
    try:
        plugin_config.mika_transport_self_heal_enabled = True
        plugin_config.mika_transport_self_heal_max_attempts = 3

        with patch(
            "mika_chat_core.mika_api_layers.transport.completion._post_and_parse",
            new=fake_post_and_parse,
        ):
            async with httpx.AsyncClient() as client:
                assistant_message, tool_calls, _ = await send_api_request_flow(
                    http_client=client,
                    request_body=request_body,
                    request_id="req-2",
                    retry_count=0,
                    api_key="A" * 32,
                    base_url="https://example.invalid",
                    model="gpt-test",
                )
    finally:
        plugin_config.mika_transport_self_heal_enabled = old_enabled
        plugin_config.mika_transport_self_heal_max_attempts = old_max

    assert tool_calls is None
    assert assistant_message.get("content") == "ok"
