import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_resolve_image_urls_v12_file_id_best_effort():
    from mika_chat_core.utils.image_processor import resolve_image_urls

    bot = MagicMock()

    async def _call_api(api: str, **data):
        if api == "get_file" and data.get("file_id") == "f1":
            return {"url": "https://example.com/img.jpg"}
        return None

    bot.call_api = AsyncMock(side_effect=_call_api)

    seg = MagicMock()
    seg.type = "image"
    seg.data = {"file_id": "f1"}

    urls = await resolve_image_urls(bot, [seg], 5)
    assert urls == ["https://example.com/img.jpg"]

