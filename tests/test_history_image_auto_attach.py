from __future__ import annotations

import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


class _FakeImageCache:
    def __init__(self, candidates):
        self._candidates = list(candidates)

    def cache_images(self, *args, **kwargs):  # pragma: no cover - not used in this test
        return 0

    def peek_recent_images(self, *, group_id, user_id, limit: int = 4):
        return list(self._candidates)[:limit]

    def get_images_by_message_id(self, *, group_id, user_id, message_id):
        # Force archive lookup path so we exercise message_archive -> data: URL conversion.
        return [], False


class _DummyProcessor:
    async def download_and_encode(self, image_url: str):
        return "abc", "image/jpeg"


@pytest.mark.asyncio
async def test_two_stage_caption_first_injects_caption_and_hint(temp_database, monkeypatch):
    from mika_chat_core.handlers_history_image import apply_history_image_strategy_flow
    from mika_chat_core.utils.history_image_policy import (
        HistoryImageAction,
        build_candidate_hint,
        build_image_mapping_hint,
        determine_history_image_action,
    )
    from mika_chat_core.utils.image_cache_core import CachedImage

    archive_content = json.dumps(
        [{"type": "image_url", "image_url": {"url": "https://example.com/archive.jpg"}}],
        ensure_ascii=False,
    )
    await temp_database.execute(
        """
        INSERT INTO message_archive (context_key, user_id, role, content, message_id, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("group:g1", "u1", "user", archive_content, "m1", time.time()),
    )
    await temp_database.commit()

    candidates = [
        CachedImage(
            url="https://example.com/cached.jpg",
            sender_id="u1",
            sender_name="Tester",
            message_id="m1",
            timestamp=time.time(),
        )
    ]
    image_cache = _FakeImageCache(candidates)

    ctx = SimpleNamespace(is_group=True, group_id="g1", user_id="u1", message_id="m-current")
    plugin_config = SimpleNamespace(
        mika_history_image_mode="hybrid",
        mika_history_image_inline_max=1,
        mika_history_image_two_stage_max=2,
        mika_history_image_collage_max=4,
        mika_history_collage_enabled=False,
        mika_history_inline_threshold=0.85,
        mika_history_two_stage_threshold=0.5,
        mika_history_image_trigger_keywords=[],
        mika_media_policy_default="caption",
        mika_media_caption_enabled=True,
    )

    metrics = SimpleNamespace(
        history_image_inline_used_total=0,
        history_image_two_stage_triggered_total=0,
        history_image_collage_used_total=0,
        history_image_fetch_tool_success_total=0,
        history_image_fetch_tool_fail_total=0,
        history_image_fetch_tool_source_cache_total=0,
        history_image_fetch_tool_source_archive_total=0,
        history_image_fetch_tool_source_get_msg_total=0,
        history_image_images_injected_total=0,
    )

    mika_client = AsyncMock()
    mika_client.get_context = AsyncMock(return_value=[])

    monkeypatch.setattr(
        "mika_chat_core.utils.media_captioner.caption_images",
        AsyncMock(return_value=["cap-1"]),
    )

    final_urls, hint = await apply_history_image_strategy_flow(
        ctx=ctx,
        message_text="帮我看看这张图",
        image_urls=[],
        sender_name="Tester",
        plugin_config=plugin_config,
        mika_client=mika_client,
        log_obj=Mock(),
        metrics_obj=metrics,
        get_image_cache_fn=lambda: image_cache,
        determine_history_image_action_fn=determine_history_image_action,
        build_image_mapping_hint_fn=build_image_mapping_hint,
        build_candidate_hint_fn=build_candidate_hint,
        history_image_action_cls=HistoryImageAction,
        create_collage_from_urls_fn=AsyncMock(return_value=None),
        is_collage_available_fn=lambda: False,
    )

    assert final_urls == []
    assert hint is not None
    assert "<msg_id:m1>" in hint
    assert "[Context Media Captions | Untrusted]" in hint
    assert "cap-1" in hint
