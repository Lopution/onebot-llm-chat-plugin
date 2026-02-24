from __future__ import annotations

from mika_chat_core.llm.providers import get_provider_capabilities


def test_openai_compat_capabilities_enable_json_mode():
    capabilities = get_provider_capabilities(
        configured_provider="openai_compat",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
    )
    assert capabilities.provider == "openai_compat"
    assert capabilities.supports_tools is True
    assert capabilities.supports_images is True
    assert capabilities.supports_json_object_response is True


def test_anthropic_capabilities_disable_json_mode():
    capabilities = get_provider_capabilities(
        configured_provider="anthropic",
        base_url="https://api.anthropic.com/v1",
        model="claude-sonnet-4-20250514",
    )
    assert capabilities.provider == "anthropic"
    assert capabilities.supports_tools is True
    assert capabilities.supports_images is True
    assert capabilities.supports_json_object_response is False


def test_google_genai_capabilities_disable_json_mode():
    capabilities = get_provider_capabilities(
        configured_provider="google_genai",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        model="gemini-2.5-flash",
    )
    assert capabilities.provider == "google_genai"
    assert capabilities.supports_tools is True
    assert capabilities.supports_images is True
    assert capabilities.supports_json_object_response is False


def test_embedding_like_model_disables_tools_and_images():
    capabilities = get_provider_capabilities(
        configured_provider="openai_compat",
        base_url="https://api.openai.com/v1",
        model="text-embedding-3-small",
    )
    assert capabilities.supports_tools is False
    assert capabilities.supports_images is False
    assert capabilities.supports_json_object_response is False
