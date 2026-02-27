from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mika_chat_core.mika_api_layers.core.messages import PreSearchResult, build_messages, pre_search


async def _empty_context(*_args, **_kwargs):
    return []


def _tool_names(request_body: dict) -> list[str]:
    names: list[str] = []
    for tool in request_body.get("tools") or []:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            continue
        function = tool.get("function") or {}
        name = function.get("name") if isinstance(function, dict) else None
        if isinstance(name, str):
            names.append(name)
    return names


@pytest.mark.asyncio
async def test_build_messages_hides_web_search_when_presearch_is_sufficient():
    tools = [
        {"type": "function", "function": {"name": "web_search"}},
        {"type": "function", "function": {"name": "search_group_history"}},
    ]
    rich_search_result = (
        "--- [实时事实注入] ---\n"
        "1. 【A】 摘要: " + ("x" * 220) + "\n"
        "2. 【B】 摘要: " + ("y" * 220) + "\n"
    )

    with patch(
        "mika_chat_core.mika_api_layers.core.messages.plugin_config.mika_tool_allowlist",
        ["web_search", "search_group_history"],
    ), patch(
        "mika_chat_core.mika_api_layers.core.messages.plugin_config.mika_search_allow_tool_refine",
        True,
    ):
        result = await build_messages(
            "iOS 26.3 什么时候推送",
            user_id="u1",
            group_id="g1",
            image_urls=None,
            search_result=rich_search_result,
            model="mika-test",
            system_prompt="你是助手",
            available_tools=tools,
            system_injection=None,
            context_level=0,
            get_context_async=_empty_context,
            use_persistent=False,
            context_store=None,
            has_image_processor=False,
            get_image_processor=None,
            has_user_profile=False,
            get_user_profile_store=None,
            enable_tools=True,
        )

    assert "web_search" not in _tool_names(result.request_body)
    assert "search_group_history" in _tool_names(result.request_body)


@pytest.mark.asyncio
async def test_build_messages_keeps_web_search_when_presearch_is_insufficient():
    tools = [
        {"type": "function", "function": {"name": "web_search"}},
        {"type": "function", "function": {"name": "search_group_history"}},
    ]
    weak_search_result = "1. 【A】 摘要: 简短结果"

    with patch(
        "mika_chat_core.mika_api_layers.core.messages.plugin_config.mika_tool_allowlist",
        ["web_search", "search_group_history"],
    ), patch(
        "mika_chat_core.mika_api_layers.core.messages.plugin_config.mika_search_allow_tool_refine",
        True,
    ):
        result = await build_messages(
            "iOS 26.3 什么时候推送",
            user_id="u1",
            group_id="g1",
            image_urls=None,
            search_result=weak_search_result,
            model="mika-test",
            system_prompt="你是助手",
            available_tools=tools,
            system_injection=None,
            context_level=0,
            get_context_async=_empty_context,
            use_persistent=False,
            context_store=None,
            has_image_processor=False,
            get_image_processor=None,
            has_user_profile=False,
            get_user_profile_store=None,
            enable_tools=True,
        )

    assert "web_search" in _tool_names(result.request_body)


@pytest.mark.asyncio
async def test_pre_search_return_meta_contains_refine_decision():
    tool_handlers = {"web_search": AsyncMock()}
    weak_search_result = "1. 【A】 摘要: 简短结果"

    with patch(
        "mika_chat_core.mika_api_layers.core.messages.plugin_config.mika_search_presearch_enabled",
        True,
    ), patch(
        "mika_chat_core.mika_api_layers.core.messages.plugin_config.mika_search_llm_gate_enabled",
        False,
    ), patch(
        "mika_chat_core.mika_api_layers.core.messages.plugin_config.mika_search_allow_tool_refine",
        True,
    ), patch(
        "mika_chat_core.utils.search_engine.should_search",
        return_value=True,
    ), patch(
        "mika_chat_core.utils.search_engine.serper_search",
        AsyncMock(return_value=weak_search_result),
    ):
        meta = await pre_search(
            "iOS 26.3 什么时候推送",
            enable_tools=True,
            request_id="req-meta",
            tool_handlers=tool_handlers,
            enable_smart_search=False,
            get_context_async=_empty_context,
            get_api_key=lambda: "key",
            base_url="https://api.example.com",
            user_id="u1",
            group_id="g1",
            return_meta=True,
        )

    assert isinstance(meta, PreSearchResult)
    assert meta.presearch_hit is True
    assert meta.allow_tool_refine is True
    assert meta.search_result == weak_search_result
