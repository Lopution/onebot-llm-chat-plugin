from __future__ import annotations

from mika_chat_core.config import Config


def test_llm_config_backfills_from_legacy_gemini_fields():
    config = Config(
        gemini_master_id=123456789,
        gemini_api_key="A" * 32,
        gemini_base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        gemini_model="gemini-2.5-flash",
        gemini_fast_model="gemini-2.5-flash-lite",
    )
    llm_cfg = config.get_llm_config()
    assert llm_cfg["provider"] == "openai_compat"
    assert llm_cfg["base_url"] == "https://generativelanguage.googleapis.com/v1beta/openai"
    assert llm_cfg["model"] == "gemini-2.5-flash"
    assert llm_cfg["fast_model"] == "gemini-2.5-flash-lite"
    assert llm_cfg["api_keys"][0] == "A" * 32


def test_search_provider_config_supports_tavily():
    config = Config(
        gemini_master_id=123456789,
        gemini_api_key="A" * 32,
        search_provider="tavily",
        search_api_key="tavily-key",
    )
    search_cfg = config.get_search_provider_config()
    assert search_cfg["provider"] == "tavily"
    assert search_cfg["api_key"] == "tavily-key"
