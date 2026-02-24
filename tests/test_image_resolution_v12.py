"""OneBot v12 图片 file_id 解析测试。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


class _FakePlatformApiPort:
    def __init__(self, mapping: dict[str, str]) -> None:
        self.mapping = mapping

    def capabilities(self) -> SimpleNamespace:
        return SimpleNamespace(supports_file_resolve=True)

    async def resolve_file_url(self, file_id: str) -> str | None:
        return self.mapping.get(file_id)


@pytest.mark.asyncio
async def test_resolve_image_urls_v12_file_id_best_effort():
    from mika_chat_core.utils.image_processor import resolve_image_urls

    seg = MagicMock()
    seg.type = "image"
    seg.data = {"file_id": "f1"}

    urls = await resolve_image_urls(
        [seg],
        5,
        platform_api=_FakePlatformApiPort({"f1": "https://example.com/img.jpg"}),
    )
    assert urls == ["https://example.com/img.jpg"]


@pytest.mark.asyncio
async def test_resolve_image_urls_prefers_runtime_platform_api_port(monkeypatch):
    from mika_chat_core.utils.image_processor import resolve_image_urls

    monkeypatch.setattr(
        "mika_chat_core.runtime.get_platform_api_port",
        lambda: _FakePlatformApiPort({"f1": "https://example.com/from-platform-port.jpg"}),
    )

    seg = MagicMock()
    seg.type = "image"
    seg.data = {"file_id": "f1"}

    urls = await resolve_image_urls(message=[seg], max_images=5)
    assert urls == ["https://example.com/from-platform-port.jpg"]
