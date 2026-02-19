from __future__ import annotations

import pytest

from mika_chat_core.utils.context_manager import ContextManager


def test_context_manager_drops_tool_without_assistant_tool_call():
    manager = ContextManager()
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "normal reply"},
        {"role": "tool", "name": "web_search", "content": "tool output"},
    ]

    processed = manager.process(messages)
    assert [item.get("role") for item in processed] == ["user", "assistant"]


def test_context_manager_keeps_valid_tool_block():
    manager = ContextManager()
    messages = [
        {"role": "user", "content": "search something"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "web_search", "arguments": "{\"query\":\"x\"}"},
                }
            ],
        },
        {"role": "tool", "name": "web_search", "tool_call_id": "call_1", "content": "tool output"},
    ]

    processed = manager.process(messages)
    assert [item.get("role") for item in processed] == ["user", "assistant", "tool"]


def _build_turn_messages(turns: int) -> list[dict]:
    messages: list[dict] = []
    for idx in range(turns):
        messages.append({"role": "user", "content": f"user-{idx}"})
        messages.append({"role": "assistant", "content": f"assistant-{idx}"})
    return messages


@pytest.mark.asyncio
async def test_process_with_summary_adds_summary_and_keeps_recent_turns():
    manager = ContextManager(max_turns=30, summary_enabled=True)
    messages = _build_turn_messages(21)

    async def _summary_builder(old_messages):
        assert len(old_messages) == 2
        return "这是历史摘要"

    processed = await manager.process_with_summary(
        messages,
        summary_builder=_summary_builder,
        summary_trigger_turns=20,
        summary_max_chars=500,
    )

    assert processed[0]["role"] == "system"
    assert str(processed[0].get("content", "")).startswith("[历史摘要] 这是历史摘要")
    assert processed[1]["content"] == "user-1"
    assert processed[-1]["content"] == "assistant-20"
    assert len(processed) == 41


@pytest.mark.asyncio
async def test_process_with_summary_fallbacks_to_normal_process_when_summary_empty():
    manager = ContextManager(max_turns=30, summary_enabled=True)
    messages = _build_turn_messages(21)
    expected = manager.process(messages)

    async def _summary_builder(_old_messages):
        return ""

    processed = await manager.process_with_summary(
        messages,
        summary_builder=_summary_builder,
        summary_trigger_turns=20,
        summary_max_chars=500,
    )

    assert processed == expected
    assert all(
        not (
            str(message.get("role") or "") == "system"
            and str(message.get("content") or "").startswith("[历史摘要]")
        )
        for message in processed
    )
