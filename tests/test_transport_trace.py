"""传输与上下文 trace 测试。"""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_context_trace_disabled_no_info_log():
    from gemini_chat.gemini_api import GeminiClient, plugin_config

    client = GeminiClient(api_key="A" * 32, use_persistent_storage=False)
    client._get_context_async = AsyncMock(return_value=[])  # type: ignore[method-assign]

    old_enabled = getattr(plugin_config, "gemini_context_trace_enabled", False)
    old_rate = getattr(plugin_config, "gemini_context_trace_sample_rate", 1.0)
    plugin_config.gemini_context_trace_enabled = False
    plugin_config.gemini_context_trace_sample_rate = 1.0
    try:
        with patch("gemini_chat.gemini_api.log.info") as mock_info:
            await client._log_context_diagnostics("10001", None, "req-1")
            mock_info.assert_not_called()
    finally:
        plugin_config.gemini_context_trace_enabled = old_enabled
        plugin_config.gemini_context_trace_sample_rate = old_rate


@pytest.mark.asyncio
async def test_context_trace_enabled_logs_info():
    from gemini_chat.gemini_api import GeminiClient, plugin_config

    client = GeminiClient(api_key="A" * 32, use_persistent_storage=False)
    client._get_context_async = AsyncMock(  # type: ignore[method-assign]
        return_value=[
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ]
    )

    old_enabled = getattr(plugin_config, "gemini_context_trace_enabled", False)
    old_rate = getattr(plugin_config, "gemini_context_trace_sample_rate", 1.0)
    plugin_config.gemini_context_trace_enabled = True
    plugin_config.gemini_context_trace_sample_rate = 1.0
    try:
        with patch("gemini_chat.gemini_api.log.info") as mock_info:
            await client._log_context_diagnostics("10001", "20002", "req-2")
            assert mock_info.call_count >= 1
            assert "context_trace" in mock_info.call_args_list[0].args[0]
    finally:
        plugin_config.gemini_context_trace_enabled = old_enabled
        plugin_config.gemini_context_trace_sample_rate = old_rate
