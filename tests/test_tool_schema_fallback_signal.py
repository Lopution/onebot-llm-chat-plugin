"""Tool schema fallback signal tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mika_chat_core.mika_api_layers.tools.tools import ToolLoopResult, handle_tool_calls


@pytest.mark.asyncio
async def test_tool_loop_marks_schema_mismatch_when_arguments_json_invalid():
    async def _dummy_handler(args: dict, group_id: str | None) -> str:
        del group_id
        return f"ok:{args.get('query', '')}"

    tool_calls = [
        {
            "id": "tool-1",
            "type": "function",
            "function": {
                "name": "web_search",
                "arguments": '{"query": "hello"',  # invalid JSON
            },
        }
    ]
    assistant_message = {"role": "assistant", "content": "", "tool_calls": tool_calls}

    with patch(
        "mika_chat_core.mika_api_layers.transport.facade.send_api_request",
        AsyncMock(return_value=({"role": "assistant", "content": "done"}, [], "test-key")),
    ):
        result = await handle_tool_calls(
            messages=[{"role": "user", "content": "hi"}],
            assistant_message=assistant_message,
            tool_calls=tool_calls,
            api_key="test-key",
            group_id=None,
            request_id="req-fallback",
            tool_handlers={"web_search": _dummy_handler},
            model="mika-test",
            base_url="https://api.example.com/v1",
            http_client=AsyncMock(),
            return_trace=True,
        )

    assert isinstance(result, ToolLoopResult)
    assert result.reply == "done"
    assert result.schema_mismatch_suspected is True
