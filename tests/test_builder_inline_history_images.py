from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest


class _DummyImageProcessor:
    async def download_and_encode(self, _url: str):
        return "abc", "image/png"


@pytest.mark.asyncio
async def test_builder_inlines_history_image_urls_to_data_urls_when_supported():
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
            mika_llm_supports_images=True,
            mika_media_caption_enabled=False,
        )
    )

    now = time.time()
    history = [
        {
            "role": "user",
            "timestamp": now - 120,
            "content": [
                {"type": "text", "text": "上一条带图"},
                {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}},
            ],
        }
    ]

    result = await build_messages(
        "继续",
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
        has_image_processor=True,
        get_image_processor=lambda _c: _DummyImageProcessor(),
    )

    urls: list[str] = []
    for msg in (result.request_body.get("messages") or []):
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, dict) and part.get("type") == "image_url":
                image_url = part.get("image_url") or {}
                if isinstance(image_url, dict):
                    urls.append(str(image_url.get("url") or ""))
                else:
                    urls.append(str(image_url))

    assert urls == ["data:image/png;base64,abc"]

