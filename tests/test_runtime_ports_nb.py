from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from mika_chat_core.contracts import Author, ContentPart, EventEnvelope
from nonebot_plugin_mika_chat import runtime_ports_nb


def _envelope(message_id: str, session_id: str) -> EventEnvelope:
    return EventEnvelope(
        schema_version=1,
        session_id=session_id,
        platform="onebot_v11",
        protocol="onebot",
        message_id=message_id,
        timestamp=1.0,
        author=Author(id="42", nickname="alice"),
        content_parts=[ContentPart(kind="text", text="hello")],
        meta={"intent": "private"},
    )


def test_runtime_port_prunes_index_by_max_entries(monkeypatch):
    monkeypatch.setattr(runtime_ports_nb, "EVENT_INDEX_MAX_ENTRIES", 2)
    monkeypatch.setattr(runtime_ports_nb, "EVENT_INDEX_TTL_SECONDS", 9999.0)

    port = runtime_ports_nb.NoneBotRuntimePort()
    port.register_event(_envelope("m1", "private:1"), bot=object(), event=object())
    port.register_event(_envelope("m2", "private:2"), bot=object(), event=object())
    port.register_event(_envelope("m3", "private:3"), bot=object(), event=object())

    assert len(port._by_message_id) == 2
    assert len(port._by_session_id) == 2
    assert "m1" not in port._by_message_id
    assert "private:1" not in port._by_session_id


def test_runtime_port_prunes_index_by_ttl(monkeypatch):
    monkeypatch.setattr(runtime_ports_nb, "EVENT_INDEX_MAX_ENTRIES", 10)
    monkeypatch.setattr(runtime_ports_nb, "EVENT_INDEX_TTL_SECONDS", 5.0)

    now = [100.0]
    monkeypatch.setattr(runtime_ports_nb.time, "monotonic", lambda: now[0])

    port = runtime_ports_nb.NoneBotRuntimePort()
    envelope = _envelope("m1", "private:1")
    port.register_event(envelope, bot=object(), event=object())

    now[0] = 106.0
    assert port.resolve_event(envelope) is None
    assert len(port._by_message_id) == 0
    assert len(port._by_session_id) == 0


def test_runtime_port_thread_safe_register_and_resolve(monkeypatch):
    monkeypatch.setattr(runtime_ports_nb, "EVENT_INDEX_MAX_ENTRIES", 1000)
    monkeypatch.setattr(runtime_ports_nb, "EVENT_INDEX_TTL_SECONDS", 9999.0)
    port = runtime_ports_nb.NoneBotRuntimePort()
    errors: list[Exception] = []

    def _worker(i: int) -> None:
        try:
            envelope = _envelope(f"m{i % 64}", f"private:{i % 64}")
            port.register_event(envelope, bot=object(), event=object())
            _ = port.resolve_event(envelope)
        except Exception as exc:  # pragma: no cover - this is the failure path
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(_worker, range(1024)))

    assert errors == []


def test_runtime_port_resolve_bot_for_session(monkeypatch):
    monkeypatch.setattr(runtime_ports_nb, "EVENT_INDEX_MAX_ENTRIES", 10)
    monkeypatch.setattr(runtime_ports_nb, "EVENT_INDEX_TTL_SECONDS", 9999.0)

    port = runtime_ports_nb.NoneBotRuntimePort()
    bot = object()
    port.register_event(_envelope("m1", "group:10001"), bot=bot, event=object())

    assert port.resolve_bot_for_session("group:10001") is bot
    assert port.resolve_bot_for_session("group:missing") is None


@pytest.mark.asyncio
async def test_runtime_port_fetch_conversation_history(monkeypatch):
    monkeypatch.setattr(runtime_ports_nb, "EVENT_INDEX_MAX_ENTRIES", 10)
    monkeypatch.setattr(runtime_ports_nb, "EVENT_INDEX_TTL_SECONDS", 9999.0)

    calls: list[tuple[str, dict[str, object]]] = []

    async def _fake_safe_call_api(bot: object, api: str, **data: object):
        calls.append((api, data))
        if api == "get_group_msg_history":
            return {"messages": [{"message_id": "m1"}]}
        return None

    monkeypatch.setattr(runtime_ports_nb, "safe_call_api", _fake_safe_call_api)

    port = runtime_ports_nb.NoneBotRuntimePort()
    bot = SimpleNamespace(self_id="42")
    port.register_event(_envelope("m1", "group:10001"), bot=bot, event=object())

    messages = await port.fetch_conversation_history("10001", limit=5)
    assert messages == [{"message_id": "m1"}]
    assert calls[0][0] == "get_group_msg_history"
    assert calls[0][1]["group_id"] == 10001
    assert calls[0][1]["message_count"] == 5


@pytest.mark.asyncio
async def test_runtime_port_fetch_conversation_history_uses_default_bot(monkeypatch):
    monkeypatch.setattr(runtime_ports_nb, "EVENT_INDEX_MAX_ENTRIES", 10)
    monkeypatch.setattr(runtime_ports_nb, "EVENT_INDEX_TTL_SECONDS", 9999.0)

    calls: list[tuple[object, str, dict[str, object]]] = []

    async def _fake_safe_call_api(bot: object, api: str, **data: object):
        calls.append((bot, api, data))
        if api == "get_group_msg_history":
            return {"messages": [{"message_id": "m-default"}]}
        return None

    monkeypatch.setattr(runtime_ports_nb, "safe_call_api", _fake_safe_call_api)

    port = runtime_ports_nb.NoneBotRuntimePort()
    default_bot = SimpleNamespace(self_id="84")
    port.set_default_platform_bot(default_bot)

    messages = await port.fetch_conversation_history("10001", limit=3)
    assert messages == [{"message_id": "m-default"}]
    assert calls[0][0] is default_bot
    assert calls[0][1] == "get_group_msg_history"
    assert calls[0][2]["group_id"] == 10001
    assert calls[0][2]["message_count"] == 3


@pytest.mark.asyncio
async def test_runtime_port_get_member_info_and_resolve_file(monkeypatch):
    monkeypatch.setattr(runtime_ports_nb, "EVENT_INDEX_MAX_ENTRIES", 10)
    monkeypatch.setattr(runtime_ports_nb, "EVENT_INDEX_TTL_SECONDS", 9999.0)

    async def _fake_safe_call_api(bot: object, api: str, **data: object):
        if api == "get_group_member_info":
            return {"nickname": "alice", "card": "Alice"}
        if api == "get_file":
            return {"url": "https://example.com/f1.jpg"}
        return None

    monkeypatch.setattr(runtime_ports_nb, "safe_call_api", _fake_safe_call_api)

    port = runtime_ports_nb.NoneBotRuntimePort()
    bot = SimpleNamespace(self_id="42")
    port.register_event(_envelope("m1", "group:10001"), bot=bot, event=object())

    member = await port.get_member_info("10001", "20002")
    assert member == {"nickname": "alice", "card": "Alice"}

    file_url = await port.resolve_file_url("f1")
    assert file_url == "https://example.com/f1.jpg"


@pytest.mark.asyncio
async def test_runtime_port_send_forward_group(monkeypatch):
    monkeypatch.setattr(runtime_ports_nb, "EVENT_INDEX_MAX_ENTRIES", 10)
    monkeypatch.setattr(runtime_ports_nb, "EVENT_INDEX_TTL_SECONDS", 9999.0)

    calls: list[tuple[str, dict[str, object]]] = []

    async def _fake_safe_call_api(bot: object, api: str, **data: object):
        calls.append((api, data))
        if api == "send_group_forward_msg":
            return {"ok": True}
        return None

    monkeypatch.setattr(runtime_ports_nb, "safe_call_api", _fake_safe_call_api)

    port = runtime_ports_nb.NoneBotRuntimePort()
    bot = SimpleNamespace(self_id="42")
    port.register_event(_envelope("m1", "group:10001"), bot=bot, event=object())

    result = await port.send_forward("group:10001", [{"type": "node", "data": {"content": "x"}}])
    assert result["ok"] is True
    assert calls[0][0] == "send_group_forward_msg"
    assert calls[0][1]["group_id"] == 10001


@pytest.mark.asyncio
async def test_runtime_port_send_forward_private_legacy_session(monkeypatch):
    monkeypatch.setattr(runtime_ports_nb, "EVENT_INDEX_MAX_ENTRIES", 10)
    monkeypatch.setattr(runtime_ports_nb, "EVENT_INDEX_TTL_SECONDS", 9999.0)

    calls: list[tuple[str, dict[str, object]]] = []

    async def _fake_safe_call_api(bot: object, api: str, **data: object):
        calls.append((api, data))
        if api == "send_private_forward_msg":
            return {"ok": True}
        return None

    monkeypatch.setattr(runtime_ports_nb, "safe_call_api", _fake_safe_call_api)

    port = runtime_ports_nb.NoneBotRuntimePort()
    bot = SimpleNamespace(self_id="42")
    port.register_event(_envelope("m1", "private:20001"), bot=bot, event=object())

    result = await port.send_forward("private:20001", [{"type": "node", "data": {"content": "x"}}])
    assert result["ok"] is True
    assert calls[0][0] == "send_private_forward_msg"
    assert calls[0][1]["user_id"] == 20001


@pytest.mark.asyncio
async def test_runtime_port_send_stream_chunked(monkeypatch):
    monkeypatch.setattr(runtime_ports_nb, "EVENT_INDEX_MAX_ENTRIES", 10)
    monkeypatch.setattr(runtime_ports_nb, "EVENT_INDEX_TTL_SECONDS", 9999.0)

    sent_payloads: list[tuple[object, dict[str, object]]] = []

    async def _fake_safe_send(bot: object, event: object, message: object, **kwargs: object):
        sent_payloads.append((message, dict(kwargs)))
        return True

    monkeypatch.setattr(runtime_ports_nb, "safe_send", _fake_safe_send)

    port = runtime_ports_nb.NoneBotRuntimePort()
    bot = SimpleNamespace(self_id="42")
    event = object()
    port.register_event(_envelope("m1", "private:20001"), bot=bot, event=event)

    async def _chunks():
        yield "abcd"
        yield "efgh"
        yield "ij"

    result = await port.send_stream(
        session_id="private:20001",
        chunks=_chunks(),
        reply_to="m1",
        meta={"stream_mode": "chunked", "chunk_chars": 4, "chunk_delay_ms": 0},
    )

    assert result["ok"] is True
    assert result["sent_count"] == 3
    assert [item[0] for item in sent_payloads] == ["abcd", "efgh", "ij"]
    assert sent_payloads[0][1] == {"reply_message": True, "at_sender": False}
    assert sent_payloads[1][1] == {}


@pytest.mark.asyncio
async def test_runtime_port_send_stream_final_only(monkeypatch):
    monkeypatch.setattr(runtime_ports_nb, "EVENT_INDEX_MAX_ENTRIES", 10)
    monkeypatch.setattr(runtime_ports_nb, "EVENT_INDEX_TTL_SECONDS", 9999.0)

    sent_payloads: list[str] = []

    async def _fake_safe_send(bot: object, event: object, message: object, **kwargs: object):
        sent_payloads.append(str(message))
        return True

    monkeypatch.setattr(runtime_ports_nb, "safe_send", _fake_safe_send)

    port = runtime_ports_nb.NoneBotRuntimePort()
    bot = SimpleNamespace(self_id="42")
    event = object()
    port.register_event(_envelope("m1", "group:10001"), bot=bot, event=event)

    async def _chunks():
        yield "hello"
        yield " "
        yield "world"

    result = await port.send_stream(
        session_id="group:10001",
        chunks=_chunks(),
        reply_to="m1",
        meta={"stream_mode": "final_only"},
    )

    assert result["ok"] is True
    assert result["sent_count"] == 1
    assert sent_payloads == ["hello world"]
