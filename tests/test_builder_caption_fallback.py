from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_builder_caption_fallback_injects_system_block_and_disables_image_url():
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
            mika_llm_supports_images=False,
            mika_media_caption_enabled=True,
        )
    )

    with patch(
        "mika_chat_core.utils.media_captioner.caption_images",
        AsyncMock(return_value=["这是一张测试图片"]),
    ):
        result = await build_messages(
            "你好",
            user_id="u1",
            group_id=None,
            image_urls=["https://example.com/a.jpg"],
            search_result="",
            model="mika-test",
            system_prompt="系统提示",
            available_tools=[],
            system_injection=None,
            context_level=0,
            get_context_async=AsyncMock(return_value=[]),
            enable_tools=False,
            use_persistent=False,
        )

    sys_contents = [
        msg.get("content")
        for msg in (result.request_body.get("messages") or [])
        if msg.get("role") == "system"
    ]
    assert any(
        isinstance(item, str) and "[Context Media Captions | Untrusted]" in item
        for item in sys_contents
    )

    user_msg = (result.request_body.get("messages") or [])[-1]
    content = user_msg.get("content")
    assert isinstance(content, list)
    assert all(
        not (isinstance(part, dict) and part.get("type") == "image_url")
        for part in content
    )
    assert any(
        isinstance(part, dict)
        and part.get("type") == "text"
        and "[图片" in str(part.get("text") or "")
        for part in content
    )


@pytest.mark.asyncio
async def test_builder_caption_fallback_captions_history_images_when_upstream_no_images():
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
            mika_llm_supports_images=False,
            mika_media_caption_enabled=True,
        )
    )

    history = [
        {
            "role": "user",
            "message_id": "m1",
            "timestamp": 1.0,
            "content": [
                {"type": "text", "text": "看这个"},
                {
                    "type": "image_url",
                    "image_url": {"url": "https://example.com/h.jpg"},
                    "mika_media": {"kind": "image", "id": "img1", "ref": "https://example.com/h.jpg"},
                },
            ],
        }
    ]

    with patch(
        "mika_chat_core.utils.media_captioner.caption_images",
        AsyncMock(return_value=["历史图：一只猫"]),
    ):
        result = await build_messages(
            "嗯",
            user_id="u1",
            group_id=None,
            image_urls=[],
            search_result="",
            model="mika-test",
            system_prompt="系统提示",
            available_tools=[],
            system_injection=None,
            context_level=0,
            get_context_async=AsyncMock(return_value=history),
            enable_tools=False,
            use_persistent=False,
        )

    sys_contents = [
        msg.get("content")
        for msg in (result.request_body.get("messages") or [])
        if msg.get("role") == "system"
    ]
    assert any(
        isinstance(item, str) and "[Context Media Captions | Untrusted]" in item
        for item in sys_contents
    )

    # upstream doesn't support images -> request must not contain image_url parts
    for msg in (result.request_body.get("messages") or []):
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        assert all(
            not (isinstance(part, dict) and part.get("type") == "image_url")
            for part in content
        )
