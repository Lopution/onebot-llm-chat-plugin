from __future__ import annotations

import pytest

from mika_chat_core.contracts import PlatformCapabilities, SessionKey
from mika_chat_core.ports.bot_api import PlatformApiPort
from mika_chat_core.ports.fake_ports import FakeOutboundMessagePort, FakePlatformApiPort
from mika_chat_core.ports.message import OutboundMessagePort, StreamMessagePort
from mika_chat_core.runtime import get_platform_api_port, set_platform_api_port


def test_platform_capabilities_defaults():
    caps = PlatformCapabilities()
    assert caps.supports_reply is True
    assert caps.supports_history_fetch is False
    assert caps.supports_forward_message is False
    assert caps.max_text_length == 0
    assert caps.platform_name == ""


def test_session_key_parse_and_round_trip():
    key = SessionKey(platform="qq", scope="group", conversation_id="123", user_id="456")
    encoded = str(key)
    assert encoded == "qq:group:123:456"
    assert SessionKey.parse(encoded) == key

    telegram_key = SessionKey.parse("telegram:private::u_abc")
    assert telegram_key.platform == "telegram"
    assert telegram_key.scope == "private"
    assert telegram_key.conversation_id == ""
    assert telegram_key.user_id == "u_abc"
    assert telegram_key.is_group is False
    assert telegram_key.conversation_key == "telegram:private:"

    legacy = SessionKey.parse("group:10001")
    assert legacy.platform == ""
    assert legacy.scope == "group"
    assert legacy.conversation_id == "10001"
    assert legacy.user_id == ""
    assert legacy.is_group is True

    with pytest.raises(ValueError):
        SessionKey.parse("invalid")


def test_fake_ports_match_protocols():
    assert isinstance(FakePlatformApiPort(), PlatformApiPort)
    assert isinstance(FakeOutboundMessagePort(), OutboundMessagePort)
    assert isinstance(FakeOutboundMessagePort(), StreamMessagePort)


@pytest.mark.asyncio
async def test_fake_platform_api_port_behavior():
    port = FakePlatformApiPort()
    port._history["conv-1"] = [{"message_id": "1"}, {"message_id": "2"}]
    port._members["conv-1:user-1"] = {"nickname": "alice"}
    port._messages["msg-1"] = {"text": "hello"}
    port._file_urls["file-1"] = "https://example.com/f1"

    history = await port.fetch_conversation_history("conv-1", limit=1)
    assert history == [{"message_id": "1"}]
    assert await port.get_member_info("conv-1", "user-1") == {"nickname": "alice"}
    assert await port.fetch_message("msg-1") == {"text": "hello"}
    assert await port.resolve_file_url("file-1") == "https://example.com/f1"
    assert await port.fetch_conversation_history("unknown") is None


@pytest.mark.asyncio
async def test_fake_outbound_message_port_send_forward():
    port = FakeOutboundMessagePort()
    payload = await port.send_forward("qq:group:123:456", [{"type": "node", "data": {"text": "hello"}}])
    assert payload["ok"] is True
    assert payload["count"] == 1
    assert port.forwarded_messages[0]["session_id"] == "qq:group:123:456"


@pytest.mark.asyncio
async def test_fake_outbound_message_port_send_stream():
    port = FakeOutboundMessagePort()

    async def _chunks():
        yield "hello"
        yield " "
        yield "world"

    payload = await port.send_stream(session_id="qq:private::u1", chunks=_chunks(), reply_to="m1")
    assert payload["ok"] is True
    assert payload["text"] == "hello world"
    assert payload["chunks"] == 3
    assert port.streamed_texts[-1] == "hello world"


def test_runtime_platform_api_port_set_get():
    original = get_platform_api_port()
    fake = FakePlatformApiPort()
    set_platform_api_port(fake)
    assert get_platform_api_port() is fake
    set_platform_api_port(None)
    assert get_platform_api_port() is None
    set_platform_api_port(original)
