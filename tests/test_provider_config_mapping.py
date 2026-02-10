from __future__ import annotations

import pytest

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


def test_mika_llm_env_aliases_are_applied(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MIKA_LLM_PROVIDER", "openai_compat")
    monkeypatch.setenv("MIKA_LLM_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("MIKA_LLM_API_KEY", "B" * 32)
    monkeypatch.setenv("MIKA_LLM_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("MIKA_LLM_FAST_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("MIKA_SEARCH_PROVIDER", "tavily")
    monkeypatch.setenv("MIKA_SEARCH_API_KEY", "tavily-key")

    config = Config(gemini_master_id=123456789)
    llm_cfg = config.get_llm_config()
    search_cfg = config.get_search_provider_config()

    assert llm_cfg["provider"] == "openai_compat"
    assert llm_cfg["base_url"] == "https://api.openai.com/v1"
    assert llm_cfg["model"] == "gpt-4o-mini"
    assert llm_cfg["fast_model"] == "gpt-4o-mini"
    assert llm_cfg["api_keys"][0] == "B" * 32
    assert search_cfg["provider"] == "tavily"
    assert search_cfg["api_key"] == "tavily-key"


def test_legacy_env_emits_deprecation_warning(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GEMINI_API_KEY", "A" * 32)
    monkeypatch.delenv("MIKA_LLM_API_KEY", raising=False)

    with pytest.warns(UserWarning, match="GEMINI_API_KEY"):
        Config(gemini_master_id=123456789, gemini_api_key="A" * 32)


def test_mika_master_env_aliases_are_applied(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MIKA_MASTER_ID", "987654321")
    monkeypatch.setenv("MIKA_MASTER_NAME", "Sensei")
    monkeypatch.setenv("MIKA_BOT_DISPLAY_NAME", "Mika")
    monkeypatch.setenv("MIKA_GROUP_WHITELIST", "[123456789, \"987654321\"]")

    config = Config(gemini_api_key="A" * 32)

    assert config.gemini_master_id == 987654321
    assert config.gemini_master_name == "Sensei"
    assert config.gemini_bot_display_name == "Mika"
    assert config.gemini_group_whitelist == [123456789, 987654321]


def test_legacy_master_env_emits_deprecation_warning(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GEMINI_MASTER_ID", "123456789")
    monkeypatch.delenv("MIKA_MASTER_ID", raising=False)

    with pytest.warns(UserWarning, match="GEMINI_MASTER_ID"):
        Config(gemini_master_id=123456789, gemini_api_key="A" * 32)
