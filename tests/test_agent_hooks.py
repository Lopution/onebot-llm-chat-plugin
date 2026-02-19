"""Agent lifecycle hooks tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mika_chat_core.runtime import set_agent_run_hooks


@pytest.mark.asyncio
async def test_chat_emits_before_and_after_llm_hooks():
    from mika_chat_core.mika_api import MikaClient

    events: list[tuple[str, dict]] = []

    async def _on_before(payload: dict) -> None:
        events.append(("before", dict(payload)))

    async def _on_after(payload: dict) -> None:
        events.append(("after", dict(payload)))

    with patch("mika_chat_core.mika_api.HAS_SQLITE_STORE", False):
        client = MikaClient(api_key="test-key")

    set_agent_run_hooks(
        {
            "on_before_llm": _on_before,
            "on_after_llm": _on_after,
        }
    )
    try:
        with patch.object(client, "_pre_search", AsyncMock(return_value="")), patch.object(
            client,
            "_build_messages",
            AsyncMock(
                return_value=(
                    [{"role": "user", "content": "hi"}],
                    "hi",
                    "hi",
                    {"model": "mika-test", "messages": [{"role": "user", "content": "hi"}], "tools": []},
                )
            ),
        ), patch.object(
            client,
            "_send_api_request",
            AsyncMock(return_value=({"role": "assistant", "content": "ok"}, [], "test-key")),
        ), patch.object(
            client,
            "_resolve_reply",
            AsyncMock(return_value=("ok", [])),
        ), patch.object(
            client,
            "_update_context",
            AsyncMock(),
        ), patch.object(
            client,
            "_log_context_diagnostics",
            AsyncMock(),
        ):
            reply = await client.chat("hi", user_id="u1")

        assert reply == "ok"
        assert [event[0] for event in events] == ["before", "after"]
        assert events[0][1]["model"] == "mika-test"
        assert events[1][1]["ok"] is True
    finally:
        set_agent_run_hooks(None)


@pytest.mark.asyncio
async def test_tool_loop_emits_tool_start_and_end_hooks():
    from mika_chat_core.mika_api_layers.tools.tools import handle_tool_calls

    events: list[tuple[str, dict]] = []

    async def _on_tool_start(payload: dict) -> None:
        events.append(("start", dict(payload)))

    async def _on_tool_end(payload: dict) -> None:
        events.append(("end", dict(payload)))

    async def _web_search_handler(args: dict, group_id: str | None) -> str:
        del group_id
        return f"search:{args.get('query', '')}"

    set_agent_run_hooks(
        {
            "on_tool_start": _on_tool_start,
            "on_tool_end": _on_tool_end,
        }
    )
    try:
        tool_calls = [
            {
                "id": "tool-1",
                "type": "function",
                "function": {"name": "web_search", "arguments": '{"query":"hello"}'},
            }
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
                group_id=None,
                request_id="req-hook",
                tool_handlers={"web_search": _web_search_handler},
                model="mika-test",
                base_url="https://api.example.com/v1",
                http_client=AsyncMock(),
            )

        assert reply == "done"
        assert [event[0] for event in events] == ["start", "end"]
        assert events[0][1]["tool_name"] == "web_search"
        assert events[1][1]["ok"] is True
        assert events[1][1]["duration_ms"] >= 0
    finally:
        set_agent_run_hooks(None)
