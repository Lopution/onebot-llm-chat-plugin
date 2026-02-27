from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mika_chat_core.runtime import set_agent_run_hooks


@pytest.mark.asyncio
async def test_tool_executor_ttl_cache_hits_when_session_key_available():
    from mika_chat_core.mika_api_layers.tools.tools import handle_tool_calls

    tool_end_events: list[dict] = []
    call_count = 0

    async def _on_tool_end(payload: dict) -> None:
        tool_end_events.append(dict(payload))

    async def _web_search_handler(args: dict, group_id: str | None) -> str:
        nonlocal call_count
        del group_id
        call_count += 1
        return f"search:{args.get('query', '')}"

    set_agent_run_hooks({"on_tool_end": _on_tool_end})
    try:
        tool_calls = [
            {
                "id": "tool-1",
                "type": "function",
                "function": {"name": "web_search", "arguments": '{"query":"hello"}'},
            },
            {
                "id": "tool-2",
                "type": "function",
                "function": {"name": "web_search", "arguments": '{"query":"hello"}'},
            },
        ]
        assistant_message = {"role": "assistant", "content": "", "tool_calls": tool_calls}

        with patch(
            "mika_chat_core.mika_api_layers.transport.facade.send_api_request",
            AsyncMock(return_value=({"role": "assistant", "content": "done"}, [], "test-key")),
        ):
            reply = await handle_tool_calls(
                messages=[{"role": "user", "content": "hi"}],
                assistant_message=assistant_message,
                tool_calls=tool_calls,
                api_key="test-key",
                group_id="g1",
                request_id="req-cache",
                session_key="group:g1",
                tool_handlers={"web_search": _web_search_handler},
                model="mika-test",
                base_url="https://api.example.com/v1",
                http_client=AsyncMock(),
            )

        assert reply == "done"
        assert call_count == 1
        assert len(tool_end_events) == 2
        assert tool_end_events[0].get("cache_hit") is False
        assert tool_end_events[1].get("cache_hit") is True
    finally:
        set_agent_run_hooks(None)

