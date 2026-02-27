from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_inject_memory_retrieval_truncates_injection_block_by_max_chars():
    from mika_chat_core.mika_api import MikaClient

    cfg = SimpleNamespace(
        mika_memory_retrieval_enabled=True,
        mika_memory_retrieval_max_iterations=3,
        mika_memory_retrieval_timeout=15.0,
        mika_memory_min_similarity=0.5,
        mika_knowledge_default_corpus="default",
        mika_retrieval_injection_max_chars=80,
        get_llm_config=lambda: {
            "provider": "openai_compat",
            "base_url": "https://api.example.com/v1",
            "api_keys": ["test-key"],
            "model": "main-model",
            "fast_model": "fast-model",
            "extra_headers": {},
        },
    )

    fake_agent = SimpleNamespace(retrieve=AsyncMock(return_value="X" * 500))

    with patch("mika_chat_core.mika_api.HAS_SQLITE_STORE", False):
        client = MikaClient(api_key="test-key")

    with patch("mika_chat_core.mika_api.plugin_config", cfg), patch(
        "mika_chat_core.observability.trace_store.plugin_config",
        SimpleNamespace(mika_trace_enabled=False),
    ), patch(
        "mika_chat_core.mika_api.get_memory_retrieval_agent",
        return_value=fake_agent,
    ):
        output = await client._inject_memory_retrieval_context(
            message="她最近说了什么？",
            user_id="u1",
            group_id="g1",
            request_id="req-budget",
            system_injection=None,
        )

    assert isinstance(output, str)
    assert output.startswith("[多源记忆检索结果]")
    assert len(output) == 80
    assert output.endswith("...")

