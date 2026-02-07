"""发送策略阶段管线测试。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_send_policy_short_message_prefers_quote_text():
    from mika_chat_core.handlers import SendStageResult, send_reply_with_policy

    bot = MagicMock()
    event = MagicMock()
    plugin_config = SimpleNamespace(
        gemini_forward_threshold=300,
        gemini_long_reply_image_fallback_enabled=True,
    )
    ctx = SimpleNamespace(session_key="private:10001")

    with patch("mika_chat_core.handlers.build_event_context", return_value=ctx), \
         patch(
             "mika_chat_core.handlers._stage_short_quote_text",
             new=AsyncMock(return_value=SendStageResult(ok=True, method="quote_text")),
         ) as short_stage, \
         patch("mika_chat_core.handlers._stage_long_forward", new=AsyncMock()) as long_stage, \
         patch("mika_chat_core.handlers._stage_render_image", new=AsyncMock()) as image_stage, \
         patch("mika_chat_core.handlers._stage_text_fallback", new=AsyncMock()) as fallback_stage:
        await send_reply_with_policy(
            bot,
            event,
            "短消息",
            is_proactive=False,
            plugin_config=plugin_config,
        )

    short_stage.assert_awaited_once()
    long_stage.assert_not_awaited()
    image_stage.assert_not_awaited()
    fallback_stage.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_policy_long_message_falls_back_to_text_when_forward_and_image_fail():
    from mika_chat_core.handlers import SendStageResult, send_reply_with_policy

    bot = MagicMock()
    event = MagicMock()
    plugin_config = SimpleNamespace(
        gemini_forward_threshold=10,
        gemini_long_reply_image_fallback_enabled=True,
    )
    ctx = SimpleNamespace(session_key="group:20002")

    with patch("mika_chat_core.handlers.build_event_context", return_value=ctx), \
         patch(
             "mika_chat_core.handlers._stage_long_forward",
             new=AsyncMock(return_value=SendStageResult(ok=False, method="forward", error="forward_failed")),
         ) as long_stage, \
         patch(
             "mika_chat_core.handlers._stage_render_image",
             new=AsyncMock(return_value=SendStageResult(ok=False, method="quote_image", error="render_failed")),
         ) as image_stage, \
         patch(
             "mika_chat_core.handlers._stage_text_fallback",
             new=AsyncMock(
                 return_value=SendStageResult(ok=True, method="quote_text_fallback")
             ),
         ) as fallback_stage:
        await send_reply_with_policy(
            bot,
            event,
            "这是一条足够长的消息，会先走 forward，再走图片和文本兜底",
            is_proactive=True,
            plugin_config=plugin_config,
        )

    long_stage.assert_awaited_once()
    image_stage.assert_awaited_once()
    fallback_stage.assert_awaited_once()
