import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_search_group_history_uses_local_context_store():
    from gemini_chat.tools import handle_search_group_history

    fake_store = AsyncMock()
    fake_store.get_context = AsyncMock(
        return_value=[
            {"role": "user", "content": "[Alice(1)]: hello"},
            {"role": "assistant", "content": "hi there"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "see this"},
                    {"type": "image_url", "image_url": {"url": "https://example.com/img.jpg"}},
                ],
            },
        ]
    )

    with patch("gemini_chat.utils.context_store.get_context_store", return_value=fake_store):
        out = await handle_search_group_history({"count": 2}, group_id="987654321")

    assert "以下是查找到的历史消息" in out
    assert "hi there" in out
    assert "[图片]" in out


@pytest.mark.asyncio
async def test_search_group_history_requires_group_id():
    from gemini_chat.tools import handle_search_group_history

    out = await handle_search_group_history({"count": 5}, group_id="")
    assert "仅在群聊可用" in out

