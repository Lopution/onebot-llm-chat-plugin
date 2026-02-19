"""handlers 核心流程测试（EventEnvelope 驱动）。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from mika_chat_core.contracts import Author, ContentPart, EventEnvelope
from mika_chat_core.planning.filter_types import FilterResult


def _private_envelope(*, text: str = "你好", user_id: str = "123456789", message_id: str = "m-1") -> EventEnvelope:
    return EventEnvelope(
        schema_version=1,
        session_id=f"private:{user_id}",
        platform="test",
        protocol="test",
        message_id=message_id,
        timestamp=0.0,
        author=Author(id=user_id, nickname="私聊用户"),
        bot_self_id="bot-1",
        content_parts=[ContentPart(kind="text", text=text)],
        meta={"group_id": "", "user_id": user_id, "is_group": False, "is_tome": False},
    )


def _group_envelope(
    *,
    text: str = "Mika 你好",
    user_id: str = "123456789",
    group_id: str = "987654321",
    message_id: str = "g-1",
    nickname: str = "测试群友",
) -> EventEnvelope:
    return EventEnvelope(
        schema_version=1,
        session_id=f"group:{group_id}",
        platform="test",
        protocol="test",
        message_id=message_id,
        timestamp=0.0,
        author=Author(id=user_id, nickname=nickname),
        bot_self_id="3932370959",
        content_parts=[ContentPart(kind="text", text=text)],
        meta={"group_id": group_id, "user_id": user_id, "is_group": True, "is_tome": True},
    )


@pytest.mark.asyncio
async def test_handle_private_normal_message():
    from mika_chat_core.handlers import handle_private

    envelope = _private_envelope(text="你好，Mika！")
    config = SimpleNamespace(
        mika_reply_private=True,
        mika_max_images=10,
        mika_master_id="999999999",
        mika_master_name="Sensei",
        mika_forward_threshold=300,
        mika_long_reply_image_fallback_enabled=True,
    )

    mika_client = AsyncMock()
    mika_client.chat = AsyncMock(return_value="你好呀~")
    message_port = AsyncMock()
    message_port.send_message = AsyncMock(return_value={"ok": True})

    profile_extract_service = SimpleNamespace(ingest_message=lambda **_kwargs: None)

    with patch("mika_chat_core.handlers.get_runtime_message_port", return_value=message_port), patch(
        "mika_chat_core.utils.user_profile_extract_service.get_user_profile_extract_service",
        return_value=profile_extract_service,
    ):
        await handle_private(envelope, config, mika_client)

    mika_client.chat.assert_awaited_once()
    call_args = mika_client.chat.await_args
    first_message = call_args.args[0]
    assert "[私聊用户]:" in first_message
    message_port.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_private_master_tag():
    from mika_chat_core.handlers import handle_private

    envelope = _private_envelope(text="Mika，在吗？", user_id="123456789")
    config = SimpleNamespace(
        mika_reply_private=True,
        mika_max_images=10,
        mika_master_id="123456789",
        mika_master_name="Sensei",
        mika_forward_threshold=300,
        mika_long_reply_image_fallback_enabled=True,
    )

    mika_client = AsyncMock()
    mika_client.chat = AsyncMock(return_value="Sensei！你来啦~")
    message_port = AsyncMock()
    message_port.send_message = AsyncMock(return_value={"ok": True})

    profile_extract_service = SimpleNamespace(ingest_message=lambda **_kwargs: None)

    with patch("mika_chat_core.handlers.get_runtime_message_port", return_value=message_port), patch(
        "mika_chat_core.utils.user_profile_extract_service.get_user_profile_extract_service",
        return_value=profile_extract_service,
    ):
        await handle_private(envelope, config, mika_client)

    first_message = mika_client.chat.await_args.args[0]
    assert "[⭐Sensei]:" in first_message


@pytest.mark.asyncio
async def test_handle_private_disabled():
    from mika_chat_core.handlers import handle_private

    envelope = _private_envelope(text="你好")
    config = SimpleNamespace(mika_reply_private=False)
    mika_client = AsyncMock()
    await handle_private(envelope, config, mika_client)
    mika_client.chat.assert_not_called()


@pytest.mark.asyncio
async def test_handle_group_normal_message_updates_profile_and_reply():
    from mika_chat_core.handlers import handle_group

    envelope = _group_envelope()
    config = SimpleNamespace(
        mika_reply_at=True,
        mika_group_whitelist=[],
        mika_max_images=10,
        mika_master_id="999999999",
        mika_forward_threshold=300,
        mika_long_reply_image_fallback_enabled=True,
    )

    mika_client = AsyncMock()
    mika_client.get_context = AsyncMock(return_value=[])
    mika_client.chat = AsyncMock(return_value="你好呀~")

    profile_store = AsyncMock()
    profile_store.update_from_message = AsyncMock(return_value=False)
    profile_extract_service = SimpleNamespace(ingest_message=lambda **_kwargs: None)
    message_port = AsyncMock()
    message_port.send_message = AsyncMock(return_value={"ok": True})

    with patch("mika_chat_core.handlers.get_user_profile_store", return_value=profile_store), patch(
        "mika_chat_core.handlers.get_runtime_message_port", return_value=message_port
    ), patch("mika_chat_core.handlers.get_runtime_platform_api_port", return_value=None), patch(
        "mika_chat_core.utils.user_profile_extract_service.get_user_profile_extract_service",
        return_value=profile_extract_service,
    ):
        await handle_group(envelope, config, mika_client)

    mika_client.chat.assert_awaited_once()
    profile_store.update_from_message.assert_awaited_once()
    message_port.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_group_non_whitelist():
    from mika_chat_core.handlers import handle_group

    envelope = _group_envelope(group_id="999888777")
    config = SimpleNamespace(
        mika_reply_at=True,
        mika_group_whitelist=["111222333", "444555666"],
    )
    mika_client = AsyncMock()
    await handle_group(envelope, config, mika_client)
    mika_client.chat.assert_not_called()


@pytest.mark.asyncio
async def test_handle_group_relevance_filter_skip_reply():
    from mika_chat_core.handlers import handle_group

    envelope = _group_envelope(text="😂")
    config = SimpleNamespace(
        mika_reply_at=True,
        mika_group_whitelist=[],
        mika_max_images=10,
        mika_master_id="999999999",
        mika_forward_threshold=300,
        mika_long_reply_image_fallback_enabled=True,
        mika_relevance_filter_enabled=True,
        mika_relevance_filter_model="",
        llm_fast_model="fake-fast",
        mika_search_classify_temperature=0.0,
        mika_proactive_chatroom_enabled=False,
    )

    mika_client = AsyncMock()
    mika_client.get_context = AsyncMock(return_value=[])
    mika_client.chat = AsyncMock(return_value="这条不应被发送")

    profile_store = AsyncMock()
    profile_store.update_from_message = AsyncMock(return_value=False)
    profile_extract_service = SimpleNamespace(ingest_message=lambda **_kwargs: None)
    message_port = AsyncMock()
    message_port.send_message = AsyncMock(return_value={"ok": True})
    relevance_filter = SimpleNamespace(
        evaluate=AsyncMock(
            return_value=FilterResult(
                should_reply=False,
                reasoning="emoji-only",
                confidence=0.95,
            )
        )
    )

    with patch("mika_chat_core.handlers.get_user_profile_store", return_value=profile_store), patch(
        "mika_chat_core.handlers.get_runtime_message_port", return_value=message_port
    ), patch("mika_chat_core.handlers.get_runtime_platform_api_port", return_value=None), patch(
        "mika_chat_core.handlers.get_relevance_filter", return_value=relevance_filter
    ), patch(
        "mika_chat_core.utils.user_profile_extract_service.get_user_profile_extract_service",
        return_value=profile_extract_service,
    ):
        await handle_group(envelope, config, mika_client)

    relevance_filter.evaluate.assert_awaited_once()
    mika_client.chat.assert_not_called()
    message_port.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_handle_group_relevance_filter_bypassed_for_master():
    from mika_chat_core.handlers import handle_group

    envelope = _group_envelope(text="😂", user_id="123456789")
    config = SimpleNamespace(
        mika_reply_at=True,
        mika_group_whitelist=[],
        mika_max_images=10,
        mika_master_id="123456789",
        mika_forward_threshold=300,
        mika_long_reply_image_fallback_enabled=True,
        mika_relevance_filter_enabled=True,
        mika_relevance_filter_model="",
        llm_fast_model="fake-fast",
        mika_search_classify_temperature=0.0,
        mika_proactive_chatroom_enabled=False,
    )

    mika_client = AsyncMock()
    mika_client.get_context = AsyncMock(return_value=[])
    mika_client.chat = AsyncMock(return_value="master 消息必须回复")

    profile_store = AsyncMock()
    profile_store.update_from_message = AsyncMock(return_value=False)
    profile_extract_service = SimpleNamespace(ingest_message=lambda **_kwargs: None)
    message_port = AsyncMock()
    message_port.send_message = AsyncMock(return_value={"ok": True})
    relevance_filter = SimpleNamespace(
        evaluate=AsyncMock(
            return_value=FilterResult(
                should_reply=False,
                reasoning="should not be called",
                confidence=1.0,
            )
        )
    )

    with patch("mika_chat_core.handlers.get_user_profile_store", return_value=profile_store), patch(
        "mika_chat_core.handlers.get_runtime_message_port", return_value=message_port
    ), patch("mika_chat_core.handlers.get_runtime_platform_api_port", return_value=None), patch(
        "mika_chat_core.handlers.get_relevance_filter", return_value=relevance_filter
    ), patch(
        "mika_chat_core.utils.user_profile_extract_service.get_user_profile_extract_service",
        return_value=profile_extract_service,
    ):
        await handle_group(envelope, config, mika_client)

    relevance_filter.evaluate.assert_not_called()
    mika_client.chat.assert_awaited_once()
    message_port.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_reset_private():
    from mika_chat_core.handlers import handle_reset

    envelope = _private_envelope(user_id="123456789")
    config = SimpleNamespace(
        mika_forward_threshold=300,
        mika_long_reply_image_fallback_enabled=True,
    )
    mika_client = AsyncMock()
    mika_client.clear_context_async = AsyncMock()
    message_port = AsyncMock()
    message_port.send_message = AsyncMock(return_value={"ok": True})

    with patch("mika_chat_core.handlers.get_runtime_message_port", return_value=message_port):
        await handle_reset(envelope, config, mika_client)

    mika_client.clear_context_async.assert_awaited_once_with("123456789", None)
    message_port.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_reset_group():
    from mika_chat_core.handlers import handle_reset

    envelope = _group_envelope(user_id="123456789", group_id="111222333")
    config = SimpleNamespace(
        mika_forward_threshold=300,
        mika_long_reply_image_fallback_enabled=True,
    )
    mika_client = AsyncMock()
    mika_client.clear_context_async = AsyncMock()
    message_port = AsyncMock()
    message_port.send_message = AsyncMock(return_value={"ok": True})

    with patch("mika_chat_core.handlers.get_runtime_message_port", return_value=message_port):
        await handle_reset(envelope, config, mika_client)

    mika_client.clear_context_async.assert_awaited_once_with("123456789", "111222333")


@pytest.mark.asyncio
async def test_send_forward_msg_uses_message_port():
    from mika_chat_core.handlers import send_forward_msg

    envelope = _group_envelope(group_id="111222333")
    config = SimpleNamespace(mika_bot_display_name="Mika")
    message_port = AsyncMock()
    message_port.send_forward = AsyncMock(return_value={"ok": True})

    with patch("mika_chat_core.handlers.get_runtime_message_port", return_value=message_port):
        ok = await send_forward_msg(envelope, "长消息内容", config)

    assert ok is True
    message_port.send_forward.assert_awaited_once()
    _session_id, nodes = message_port.send_forward.await_args.args
    assert _session_id == "group:111222333"
    assert nodes[0]["data"]["uin"] == "3932370959"


@pytest.mark.asyncio
async def test_send_rendered_image_uses_message_port_first():
    from mika_chat_core.handlers import send_rendered_image_with_quote

    envelope = _private_envelope(message_id="9001")
    config = SimpleNamespace(
        mika_long_reply_image_max_width=960,
        mika_long_reply_image_font_size=24,
        mika_long_reply_image_max_chars=12000,
    )
    message_port = AsyncMock()
    message_port.send_message = AsyncMock(return_value={"ok": True})

    with patch("mika_chat_core.handlers.render_text_to_png_bytes", return_value=b"fake_png"), patch(
        "mika_chat_core.handlers.get_runtime_message_port", return_value=message_port
    ):
        ok = await send_rendered_image_with_quote(envelope, "hello", plugin_config=config)

    assert ok is True
    message_port.send_message.assert_awaited_once()
