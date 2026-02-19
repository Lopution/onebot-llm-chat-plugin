"""relevance_filter 单元测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mika_chat_core.planning.filter_types import FilterResult
from mika_chat_core.planning.relevance_filter import RelevanceFilter


class TestRelevanceFilterParseResult:
    def test_parse_valid_json(self):
        result = RelevanceFilter()._parse_result(
            '{"should_reply": false, "reasoning": "noise", "confidence": 0.86}'
        )
        assert result == FilterResult(should_reply=False, reasoning="noise", confidence=0.86)

    def test_parse_json_fragment(self):
        result = RelevanceFilter()._parse_result(
            '```json\n{"should_reply": true, "reasoning": "question", "confidence": 1}\n```'
        )
        assert result == FilterResult(should_reply=True, reasoning="question", confidence=1.0)

    def test_parse_invalid_json_fallback(self):
        result = RelevanceFilter()._parse_result("not-json")
        assert result == FilterResult(should_reply=True, reasoning="invalid_json", confidence=0.0)


@pytest.mark.asyncio
async def test_relevance_filter_evaluate_success():
    relevance_filter = RelevanceFilter()
    mock_response = MagicMock()
    mock_response.raise_for_status = lambda: None
    mock_response.json.return_value = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": '{"should_reply": false, "reasoning": "emoji-only", "confidence": 0.92}',
                }
            }
        ]
    }

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.is_closed = False

    with patch("mika_chat_core.planning.relevance_filter.httpx.AsyncClient", return_value=mock_client):
        result = await relevance_filter.evaluate(
            message="😂😂😂",
            context_messages=[{"role": "user", "content": "mika?"}],
            llm_cfg={
                "provider": "openai_compat",
                "base_url": "https://example.com/v1",
                "api_keys": ["test-key"],
                "extra_headers": {},
            },
            model="test-model",
        )

    assert result == FilterResult(should_reply=False, reasoning="emoji-only", confidence=0.92)
    mock_client.post.assert_awaited_once()


@pytest.mark.asyncio
async def test_relevance_filter_evaluate_missing_api_key():
    result = await RelevanceFilter().evaluate(
        message="mika 在吗",
        context_messages=[],
        llm_cfg={
            "provider": "openai_compat",
            "base_url": "https://example.com/v1",
            "api_keys": [],
            "extra_headers": {},
        },
        model="test-model",
    )
    assert result == FilterResult(should_reply=True, reasoning="missing_api_key", confidence=0.0)


@pytest.mark.asyncio
async def test_relevance_filter_reuses_http_client_between_calls():
    relevance_filter = RelevanceFilter()
    mock_response = MagicMock()
    mock_response.raise_for_status = lambda: None
    mock_response.json.return_value = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": '{"should_reply": true, "reasoning": "ok", "confidence": 0.7}',
                }
            }
        ]
    }

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.is_closed = False

    llm_cfg = {
        "provider": "openai_compat",
        "base_url": "https://example.com/v1",
        "api_keys": ["test-key"],
        "extra_headers": {},
    }

    with patch("mika_chat_core.planning.relevance_filter.httpx.AsyncClient", return_value=mock_client) as client_factory:
        first = await relevance_filter.evaluate(
            message="mika 在吗",
            context_messages=[],
            llm_cfg=llm_cfg,
            model="test-model",
        )
        second = await relevance_filter.evaluate(
            message="再问一次",
            context_messages=[],
            llm_cfg=llm_cfg,
            model="test-model",
        )

    assert first.should_reply is True
    assert second.should_reply is True
    assert client_factory.call_count == 1
