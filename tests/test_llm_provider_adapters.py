from __future__ import annotations

import json

from mika_chat_core.llm.providers import build_provider_request, parse_provider_response


def _request_body() -> dict:
    return {
        "model": "test-model",
        "messages": [
            {"role": "system", "content": "system prompt"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "hello"},
                    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,ZmFrZQ=="}},
                ],
            },
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "search tool",
                    "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
                },
            }
        ],
    }


def test_openai_compat_non_google_does_not_inject_safety_settings():
    prepared = build_provider_request(
        provider="openai_compat",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
        api_key="k",
        request_body=_request_body(),
        extra_headers=None,
        default_temperature=0.1,
    )
    assert prepared.url.endswith("/chat/completions")
    assert "safetySettings" not in prepared.json_body


def test_openai_compat_google_injects_safety_settings():
    prepared = build_provider_request(
        provider="openai_compat",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        model="gemini-2.5-flash",
        api_key="k",
        request_body=_request_body(),
        extra_headers=None,
        default_temperature=0.1,
    )
    assert prepared.url.endswith("/chat/completions")
    assert "safetySettings" in prepared.json_body
    assert isinstance(prepared.json_body["safetySettings"], list)


def test_anthropic_request_contains_system_tools_and_blocks():
    prepared = build_provider_request(
        provider="anthropic",
        base_url="https://api.anthropic.com/v1",
        model="claude-sonnet-4-20250514",
        api_key="k",
        request_body=_request_body(),
        extra_headers={"x-test": "1"},
        default_temperature=0.1,
    )
    assert prepared.url.endswith("/messages")
    assert prepared.headers["x-api-key"] == "k"
    assert prepared.headers["x-test"] == "1"
    assert "system" in prepared.json_body
    assert prepared.json_body["tools"][0]["name"] == "web_search"
    assert prepared.json_body["messages"][0]["role"] == "user"


def test_google_genai_parse_tool_call():
    raw = {
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {
                    "parts": [
                        {"text": "ready"},
                        {"functionCall": {"name": "web_search", "args": {"query": "ios"}}},
                    ]
                },
            }
        ]
    }
    assistant_message, tool_calls, content, finish_reason = parse_provider_response(
        provider="google_genai",
        data=raw,
    )
    assert content == "ready"
    assert finish_reason == "STOP"
    assert tool_calls and tool_calls[0]["function"]["name"] == "web_search"
    parsed_args = json.loads(tool_calls[0]["function"]["arguments"])
    assert parsed_args["query"] == "ios"
    assert assistant_message["role"] == "assistant"
