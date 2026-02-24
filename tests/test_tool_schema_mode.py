"""Tool schema mode tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def _sample_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "search web",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "keyword",
                            "title": "Query",
                            "examples": ["today weather"],
                        }
                    },
                    "required": ["query"],
                },
            },
        }
    ]


def test_tool_schema_full_mode_keeps_original_schema():
    from mika_chat_core.mika_api import MikaClient

    with patch("mika_chat_core.mika_api.HAS_SQLITE_STORE", False):
        client = MikaClient(api_key="test-key")
    client._tool_registry = MagicMock()
    client._tool_registry.get_openai_schemas.return_value = _sample_tools()

    with patch("mika_chat_core.mika_api.plugin_config.mika_tool_schema_mode", "full"):
        tools = client._get_available_tools()

    query_schema = tools[0]["function"]["parameters"]["properties"]["query"]
    assert query_schema["description"] == "keyword"
    assert query_schema["title"] == "Query"


def test_tool_schema_light_mode_compacts_parameters():
    from mika_chat_core.mika_api import MikaClient

    with patch("mika_chat_core.mika_api.HAS_SQLITE_STORE", False):
        client = MikaClient(api_key="test-key")
    client._tool_registry = MagicMock()
    client._tool_registry.get_openai_schemas.return_value = _sample_tools()

    with patch("mika_chat_core.mika_api.plugin_config.mika_tool_schema_mode", "light"):
        tools = client._get_available_tools()

    query_schema = tools[0]["function"]["parameters"]["properties"]["query"]
    assert query_schema["type"] == "string"
    assert "description" not in query_schema
    assert "title" not in query_schema


def test_tool_schema_light_mode_can_keep_param_description():
    from mika_chat_core.mika_api import MikaClient

    with patch("mika_chat_core.mika_api.HAS_SQLITE_STORE", False):
        client = MikaClient(api_key="test-key")
    client._tool_registry = MagicMock()
    client._tool_registry.get_openai_schemas.return_value = _sample_tools()

    with patch("mika_chat_core.mika_api.plugin_config.mika_tool_schema_mode", "light"), patch(
        "mika_chat_core.mika_api.plugin_config.mika_tool_schema_light_keep_param_description",
        True,
    ):
        tools = client._get_available_tools()

    query_schema = tools[0]["function"]["parameters"]["properties"]["query"]
    assert query_schema["description"] == "keyword"
    assert "title" not in query_schema


def test_tool_schema_auto_mode_respects_threshold():
    from mika_chat_core.mika_api import MikaClient

    with patch("mika_chat_core.mika_api.HAS_SQLITE_STORE", False):
        client = MikaClient(api_key="test-key")
    client._tool_registry = MagicMock()
    client._tool_registry.get_openai_schemas.return_value = _sample_tools()

    with patch("mika_chat_core.mika_api.plugin_config.mika_tool_schema_mode", "auto"), patch(
        "mika_chat_core.mika_api.plugin_config.mika_tool_schema_auto_threshold",
        2,
    ):
        tools = client._get_available_tools()
    assert "description" in tools[0]["function"]["parameters"]["properties"]["query"]

    two_tools = _sample_tools() + [
        {
            "type": "function",
            "function": {
                "name": "search_group_history",
                "description": "search history",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    client._tool_registry.get_openai_schemas.return_value = two_tools
    with patch("mika_chat_core.mika_api.plugin_config.mika_tool_schema_mode", "auto"), patch(
        "mika_chat_core.mika_api.plugin_config.mika_tool_schema_auto_threshold",
        2,
    ):
        tools = client._get_available_tools()
    assert "description" not in tools[0]["function"]["parameters"]["properties"]["query"]


def test_tool_schema_session_fallback_forces_full_mode_temporarily():
    from mika_chat_core.mika_api import MikaClient

    with patch("mika_chat_core.mika_api.HAS_SQLITE_STORE", False):
        client = MikaClient(api_key="test-key")

    with patch("mika_chat_core.mika_api.plugin_config.mika_tool_schema_mode", "light"), patch(
        "mika_chat_core.mika_api.plugin_config.mika_tool_schema_auto_fallback_full",
        True,
    ), patch(
        "mika_chat_core.mika_api.plugin_config.mika_tool_schema_fallback_ttl_seconds",
        30,
    ):
        client._activate_tool_schema_full_fallback(
            session_key="group:1001",
            request_id="req-1",
            reason="test",
        )
        assert client._resolve_tool_schema_mode(3, session_key="group:1001") == "full"
        assert client._resolve_tool_schema_mode(3, session_key="group:2002") == "light"
