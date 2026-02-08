from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mika_chat_core.gemini_api_messages import PreSearchResult
from mika_chat_core.gemini_api_tools import handle_tool_calls


def _mock_final_response(text: str) -> MagicMock:
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {
        "choices": [{"message": {"content": text}, "finish_reason": "stop"}]
    }
    return response


@pytest.mark.asyncio
async def test_handle_tool_calls_blocks_duplicate_web_search_after_presearch():
    tool_calls = [
        {
            "id": "tool-1",
            "type": "function",
            "function": {"name": "web_search", "arguments": "{\"query\": \"iOS 26.3 推送时间\"}"},
        }
    ]
    assistant_message = {"role": "assistant", "content": "", "tool_calls": tool_calls}
    http_client = AsyncMock()
    http_client.post = AsyncMock(return_value=_mock_final_response("DONE"))
    tool_handler = AsyncMock(return_value="SHOULD_NOT_RUN")
    search_state = PreSearchResult(
        search_result="已有预搜索",
        normalized_query="ios 26.3 推送时间",
        presearch_hit=True,
        allow_tool_refine=True,
        result_count=3,
    )

    with patch("mika_chat_core.gemini_api_tools.plugin_config.gemini_tool_allowlist", ["web_search"]), patch(
        "mika_chat_core.gemini_api_tools.plugin_config.gemini_search_allow_tool_refine",
        True,
    ), patch(
        "mika_chat_core.gemini_api_tools.plugin_config.gemini_search_tool_refine_max_rounds",
        1,
    ):
        reply = await handle_tool_calls(
            messages=[{"role": "user", "content": "hi"}],
            assistant_message=assistant_message,
            tool_calls=tool_calls,
            api_key="test-key",
            group_id=None,
            request_id="req-dedup",
            tool_handlers={"web_search": tool_handler},
            model="gemini-test",
            base_url="https://api.example.com",
            http_client=http_client,
            search_state=search_state,
        )

    assert reply == "DONE"
    assert tool_handler.await_count == 0
    assert search_state.blocked_duplicate_total == 1


@pytest.mark.asyncio
async def test_handle_tool_calls_refine_only_once_when_max_rounds_is_one():
    tool_calls = [
        {
            "id": "tool-1",
            "type": "function",
            "function": {
                "name": "web_search",
                "arguments": "{\"query\": \"iOS 26.3 beta features release timeline\"}",
            },
        },
        {
            "id": "tool-2",
            "type": "function",
            "function": {
                "name": "web_search",
                "arguments": "{\"query\": \"iOS 26.3 beta features release timeline latest\"}",
            },
        },
    ]
    assistant_message = {"role": "assistant", "content": "", "tool_calls": tool_calls}
    http_client = AsyncMock()
    http_client.post = AsyncMock(return_value=_mock_final_response("DONE"))
    tool_handler = AsyncMock(return_value="REFINE_RESULT")
    search_state = PreSearchResult(
        search_result="已有预搜索",
        normalized_query="ios 26.3 什么时候推送 内测功能",
        presearch_hit=True,
        allow_tool_refine=True,
        result_count=2,
    )

    with patch("mika_chat_core.gemini_api_tools.plugin_config.gemini_tool_allowlist", ["web_search"]), patch(
        "mika_chat_core.gemini_api_tools.plugin_config.gemini_search_allow_tool_refine",
        True,
    ), patch(
        "mika_chat_core.gemini_api_tools.plugin_config.gemini_search_tool_refine_max_rounds",
        1,
    ):
        reply = await handle_tool_calls(
            messages=[{"role": "user", "content": "hi"}],
            assistant_message=assistant_message,
            tool_calls=tool_calls,
            api_key="test-key",
            group_id=None,
            request_id="req-refine-once",
            tool_handlers={"web_search": tool_handler},
            model="gemini-test",
            base_url="https://api.example.com",
            http_client=http_client,
            search_state=search_state,
        )

    assert reply == "DONE"
    assert tool_handler.await_count == 1
    assert search_state.refine_rounds_used == 1
