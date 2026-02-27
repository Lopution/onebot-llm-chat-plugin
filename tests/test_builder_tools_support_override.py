from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_builder_forced_supports_tools_false_omits_tools_from_request_body():
    from mika_chat_core import runtime as runtime_module
    from mika_chat_core.config import Config
    from mika_chat_core.mika_api_layers.core.messages import build_messages

    runtime_module.set_config(
        Config(
            llm_api_key="test-api-key-12345678901234567890",
            llm_api_key_list=[],
            llm_base_url="https://test.api.example.com/v1",
            llm_model="mika-test",
            llm_fast_model="mika-test-fast",
            mika_validate_on_startup=False,
            mika_master_id=123456789,
            mika_master_name="TestSensei",
            mika_prompt_file="",
            mika_system_prompt="测试助手",
            mika_max_context=40,
            mika_history_count=50,
            mika_reply_private=True,
            mika_reply_at=True,
            mika_max_images=10,
            mika_forward_threshold=300,
            mika_group_whitelist=[],
            mika_llm_supports_tools=False,
        )
    )

    result = await build_messages(
        "你好",
        user_id="u1",
        group_id=None,
        image_urls=[],
        search_result="",
        model="mika-test",
        system_prompt="系统提示",
        available_tools=[{"type": "function", "function": {"name": "web_search"}}],
        system_injection=None,
        context_level=0,
        get_context_async=AsyncMock(return_value=[]),
        enable_tools=True,
        use_persistent=False,
    )

    assert "tools" not in (result.request_body or {})
    assert "tool_choice" not in (result.request_body or {})

