import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class _FakeImageCache:
    def get_images_by_message_id(self, group_id, user_id, message_id):
        return [], False


@pytest.mark.asyncio
async def test_fetch_history_images_reads_archive_and_updates_metrics(
    temp_database,
):
    from mika_chat_core.metrics import metrics
    from mika_chat_core.tools import handle_fetch_history_images

    archive_content = json.dumps(
        [
            {
                "type": "image_url",
                "image_url": {"url": "https://example.com/archive.jpg"},
            }
        ],
        ensure_ascii=False,
    )
    await temp_database.execute(
        """
        INSERT INTO message_archive (context_key, user_id, role, content, message_id, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("group:g1", "u1", "user", archive_content, "m1", 1.0),
    )
    await temp_database.commit()

    before_success = metrics.history_image_fetch_tool_success_total
    before_archive = metrics.history_image_fetch_tool_source_archive_total

    fake_processor = MagicMock()
    fake_processor.download_and_encode = AsyncMock(return_value=("abc", "image/jpeg"))

    with patch("mika_chat_core.utils.context_db.get_db", return_value=temp_database), patch(
        "mika_chat_core.utils.recent_images.get_image_cache", return_value=_FakeImageCache()
    ), patch(
        "mika_chat_core.utils.image_processor.get_image_processor",
        return_value=fake_processor,
    ):
        raw = await handle_fetch_history_images(
            {"msg_ids": ["m1"], "max_images": 1},
            group_id="g1",
        )

    payload = json.loads(raw)
    assert payload.get("success") is True
    assert payload.get("count") == 1
    assert len(payload.get("images", [])) == 1
    assert payload["images"][0].startswith("data:image/jpeg;base64,")

    assert metrics.history_image_fetch_tool_success_total == before_success + 1
    assert metrics.history_image_fetch_tool_source_archive_total == before_archive + 1


@pytest.mark.asyncio
async def test_fetch_history_images_requires_group_id():
    from mika_chat_core.metrics import metrics
    from mika_chat_core.tools import handle_fetch_history_images

    before_fail = metrics.history_image_fetch_tool_fail_total
    raw = await handle_fetch_history_images({"msg_ids": ["m1"]}, group_id="")
    payload = json.loads(raw)

    assert "error" in payload
    assert metrics.history_image_fetch_tool_fail_total == before_fail + 1
