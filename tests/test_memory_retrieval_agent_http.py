"""memory_retrieval_agent HTTP client reuse tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mika_chat_core.memory.retrieval_agent import MemoryRetrievalAgent


@pytest.mark.asyncio
async def test_call_llm_reuses_http_client_without_numpy_dependency():
    agent = MemoryRetrievalAgent()
    mock_response = MagicMock()
    mock_response.raise_for_status = lambda: None
    mock_response.json.return_value = {
        "choices": [{"message": {"role": "assistant", "content": "ok"}}]
    }
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.is_closed = False

    llm_cfg = {
        "provider": "openai_compat",
        "base_url": "https://api.example.com/v1",
        "api_keys": ["test-key"],
        "extra_headers": {},
    }

    with patch(
        "mika_chat_core.memory.retrieval_agent.httpx.AsyncClient",
        return_value=mock_client,
    ) as client_factory:
        first = await agent._call_llm(
            system_prompt="sys",
            user_prompt="user",
            llm_cfg=llm_cfg,
            model="mika-test",
        )
        second = await agent._call_llm(
            system_prompt="sys2",
            user_prompt="user2",
            llm_cfg=llm_cfg,
            model="mika-test",
        )

    assert first == "ok"
    assert second == "ok"
    assert client_factory.call_count == 1
    await agent.close()
