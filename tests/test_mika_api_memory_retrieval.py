from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_inject_memory_retrieval_disabled_returns_base():
    from mika_chat_core.mika_api import MikaClient

    cfg = SimpleNamespace(
        mika_memory_retrieval_enabled=False,
        mika_memory_retrieval_max_iterations=3,
        mika_memory_retrieval_timeout=15.0,
        mika_memory_min_similarity=0.5,
        mika_knowledge_default_corpus="default",
        get_llm_config=lambda: {
            "provider": "openai_compat",
            "base_url": "https://api.example.com/v1",
            "api_keys": ["test-key"],
            "model": "main-model",
            "fast_model": "fast-model",
            "extra_headers": {},
        },
    )

    with patch("mika_chat_core.mika_api.HAS_SQLITE_STORE", False):
        client = MikaClient(api_key="test-key")

    with patch("mika_chat_core.mika_api.plugin_config", cfg):
        output = await client._inject_memory_retrieval_context(
            message="测试消息",
            user_id="u1",
            group_id="g1",
            request_id="req-disabled",
            system_injection="BASE",
        )
    assert output == "BASE"


@pytest.mark.asyncio
async def test_inject_memory_retrieval_appends_context():
    from mika_chat_core.mika_api import MikaClient

    cfg = SimpleNamespace(
        mika_memory_retrieval_enabled=True,
        mika_memory_retrieval_max_iterations=3,
        mika_memory_retrieval_timeout=15.0,
        mika_memory_min_similarity=0.5,
        mika_knowledge_default_corpus="default",
        get_llm_config=lambda: {
            "provider": "openai_compat",
            "base_url": "https://api.example.com/v1",
            "api_keys": ["test-key"],
            "model": "main-model",
            "fast_model": "fast-model",
            "extra_headers": {},
        },
    )

    fake_agent = SimpleNamespace(
        retrieve=AsyncMock(return_value="检索结论：用户偏好甜食，近期讨论周末计划。")
    )

    with patch("mika_chat_core.mika_api.HAS_SQLITE_STORE", False):
        client = MikaClient(api_key="test-key")

    with patch("mika_chat_core.mika_api.plugin_config", cfg):
        with patch(
            "mika_chat_core.mika_api.get_memory_retrieval_agent",
            return_value=fake_agent,
        ):
            output = await client._inject_memory_retrieval_context(
                message="她最近说了什么？",
                user_id="u1",
                group_id="g1",
                request_id="req-enabled",
                system_injection="BASE",
            )

    assert output is not None
    assert "BASE" in output
    assert "[多源记忆检索结果]" in output
    assert "检索结论" in output
    fake_agent.retrieve.assert_awaited_once()

