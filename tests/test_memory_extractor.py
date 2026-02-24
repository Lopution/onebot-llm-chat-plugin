"""memory_extractor 单元测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mika_chat_core.utils.memory_extractor import MemoryExtractor


class TestParseFactsUnit:
    def test_parses_valid_output(self):
        extractor = MemoryExtractor()
        facts = extractor._parse_facts("u1: 喜欢猫\nu2: 是程序员\n")
        assert facts == [("u1", "喜欢猫"), ("u2", "是程序员")]

    def test_returns_empty_on_none(self):
        extractor = MemoryExtractor()
        assert extractor._parse_facts("NONE") == []
        assert extractor._parse_facts("") == []

    def test_respects_max_facts(self):
        extractor = MemoryExtractor()
        raw = "\n".join(f"u1: fact{i}" for i in range(10))
        facts = extractor._parse_facts(raw, max_facts=3)
        assert len(facts) == 3

    def test_skips_short_facts(self):
        extractor = MemoryExtractor()
        facts = extractor._parse_facts("u1: ab\nu2: 这是一个完整事实")
        assert len(facts) == 1
        assert facts[0][1] == "这是一个完整事实"


@pytest.mark.asyncio
async def test_extract_calls_llm_and_parses():
    extractor = MemoryExtractor()
    mock_response = AsyncMock()
    mock_response.raise_for_status = lambda: None
    mock_response.json.return_value = {
        "choices": [{"message": {"role": "assistant", "content": "u1: 喜欢旅游\nu1: 是北京人"}}]
    }

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.is_closed = False
    mock_client.aclose = AsyncMock()

    with patch("mika_chat_core.utils.memory_extractor.httpx.AsyncClient", return_value=mock_client):
        facts = await extractor.extract(
            [{"role": "user", "content": "我上周去北京旅游了，很喜欢"}],
            api_key="k",
            base_url="https://api.example.com/v1",
            model="fast-model",
        )

    assert len(facts) == 2
    assert facts[0] == ("u1", "喜欢旅游")
