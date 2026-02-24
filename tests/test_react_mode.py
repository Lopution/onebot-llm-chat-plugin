from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mika_chat_core.mika_api_layers.core.messages import build_messages
from mika_chat_core.mika_api_layers.tools.tools import handle_tool_calls


async def _empty_context(*_args, **_kwargs):
    return []


@pytest.mark.asyncio
async def test_build_messages_appends_react_system_suffix_when_enabled():
    with patch(
        "mika_chat_core.mika_api_layers.core.messages.plugin_config.mika_react_enabled",
        True,
    ), patch(
        "mika_chat_core.mika_api_layers.core.messages.load_react_prompt",
        return_value={"react_system_suffix": "REACT_SUFFIX_FOR_TEST"},
    ):
        result = await build_messages(
            "hello",
            user_id="u1",
            group_id=None,
            image_urls=None,
            search_result="",
            model="mika-test",
            system_prompt="你是助手",
            available_tools=[],
            system_injection=None,
            context_level=0,
            get_context_async=_empty_context,
            use_persistent=False,
            context_store=None,
            has_image_processor=False,
            get_image_processor=None,
            has_user_profile=False,
            get_user_profile_store=None,
            enable_tools=False,
        )

    system_message = result.messages[0]
    assert system_message["role"] == "system"
    assert "REACT_SUFFIX_FOR_TEST" in str(system_message.get("content") or "")


@pytest.mark.asyncio
async def test_handle_tool_calls_injects_reflect_prompt_when_react_enabled():
    tool_calls = [
        {
            "id": "tool-1",
            "type": "function",
            "function": {"name": "web_search", "arguments": "{\"query\":\"天气\"}"},
        }
    ]
    messages = [{"role": "user", "content": "北京天气"}]
    assistant_message = {"role": "assistant", "content": "", "tool_calls": tool_calls}
    tool_handler = AsyncMock(return_value="天气结果")

    with patch(
        "mika_chat_core.mika_api_layers.tools.tools.plugin_config.mika_tool_allowlist",
        ["web_search"],
    ), patch(
        "mika_chat_core.mika_api_layers.tools.tools.plugin_config.mika_react_enabled",
        True,
    ), patch(
        "mika_chat_core.mika_api_layers.tools.tools.plugin_config.mika_react_max_rounds",
        8,
    ), patch(
        "mika_chat_core.mika_api_layers.transport.facade.send_api_request",
        AsyncMock(return_value=({"role": "assistant", "content": "最终答复"}, [], "stop")),
    ) as mock_send:
        reply = await handle_tool_calls(
            messages=messages,
            assistant_message=assistant_message,
            tool_calls=tool_calls,
            api_key="k",
            group_id="g1",
            request_id="req-react",
            tool_handlers={"web_search": tool_handler},
            model="mika-test",
            base_url="https://api.example.com",
            http_client=AsyncMock(),
            tools=[],
            search_state=None,
        )

    assert reply == "最终答复"
    sent_messages = mock_send.await_args.kwargs["request_body"]["messages"]
    assert any(
        str(item.get("role") or "") == "user"
        and "Observe/Reflect" in str(item.get("content") or "")
        for item in sent_messages
    )
