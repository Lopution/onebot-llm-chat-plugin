from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from nonebot_plugin_mika_chat import tools_nb


class _DummyCursor:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def fetchone(self):
        return None


class _DummyDB:
    def execute(self, *args, **kwargs):
        return _DummyCursor()


class _DummyProcessor:
    async def download_and_encode(self, image_url: str):
        return "ZmFrZQ==", "image/jpeg"


@pytest.mark.asyncio
async def test_fetch_history_images_respects_max_images(monkeypatch):
    async def _fake_get_db():
        return _DummyDB()

    class _Cache:
        def get_images_by_message_id(self, *, group_id, user_id, message_id):
            return [SimpleNamespace(sender_name="tester", url=f"https://example.com/{message_id}.jpg")], True

    monkeypatch.setattr(tools_nb, "get_config", lambda: SimpleNamespace(mika_history_image_two_stage_max=5))
    monkeypatch.setattr("mika_chat_core.utils.context_db.get_db", _fake_get_db)
    monkeypatch.setattr("mika_chat_core.utils.recent_images.get_image_cache", lambda: _Cache())
    monkeypatch.setattr("mika_chat_core.utils.image_processor.get_image_processor", lambda: _DummyProcessor())

    raw = await tools_nb.handle_fetch_history_images(
        {"msg_ids": ["1", "2", "3"], "max_images": 1},
        group_id="10001",
    )
    payload = json.loads(raw)
    assert payload["success"] is True
    assert payload["count"] == 1
    assert len(payload["images"]) == 1
    assert "<msg_id:1>" in payload["mapping"][0]


@pytest.mark.asyncio
async def test_fetch_history_images_skips_invalid_message_id(monkeypatch):
    async def _fake_get_db():
        return _DummyDB()

    class _Cache:
        def get_images_by_message_id(self, *, group_id, user_id, message_id):
            return [], False

    monkeypatch.setattr(tools_nb, "get_config", lambda: SimpleNamespace(mika_history_image_two_stage_max=5))
    monkeypatch.setattr("mika_chat_core.utils.context_db.get_db", _fake_get_db)
    monkeypatch.setattr("mika_chat_core.utils.recent_images.get_image_cache", lambda: _Cache())
    monkeypatch.setattr("mika_chat_core.utils.image_processor.get_image_processor", lambda: _DummyProcessor())

    raw = await tools_nb.handle_fetch_history_images(
        {"msg_ids": ["invalid-id"], "max_images": 2},
        group_id="10001",
    )
    payload = json.loads(raw)
    assert payload["error"] == "No images found for the requested msg_ids"


@pytest.mark.asyncio
async def test_fetch_history_images_skips_get_msg_when_bot_not_resolved(monkeypatch):
    async def _fake_get_db():
        return _DummyDB()

    class _Cache:
        def get_images_by_message_id(self, *, group_id, user_id, message_id):
            return [], False

    class _RuntimePort:
        def resolve_bot_for_session(self, session_id: str):
            return None

    class _RuntimeBundle:
        host_events = _RuntimePort()

    monkeypatch.setattr(tools_nb, "get_config", lambda: SimpleNamespace(mika_history_image_two_stage_max=5))
    monkeypatch.setattr("mika_chat_core.utils.context_db.get_db", _fake_get_db)
    monkeypatch.setattr("mika_chat_core.utils.recent_images.get_image_cache", lambda: _Cache())
    monkeypatch.setattr("mika_chat_core.utils.image_processor.get_image_processor", lambda: _DummyProcessor())
    monkeypatch.setattr(tools_nb, "get_runtime_ports_bundle", lambda: _RuntimeBundle())
    monkeypatch.setattr(tools_nb, "get_bots", lambda: {"a": object(), "b": object()})

    raw = await tools_nb.handle_fetch_history_images(
        {"msg_ids": ["123"], "max_images": 1},
        group_id="10001",
    )
    payload = json.loads(raw)
    assert payload["error"] == "No images found for the requested msg_ids"
