from __future__ import annotations

import pytest

from mika_chat_core.tools_registry import (
    ToolDefinition,
    ToolRegistry,
    build_effective_allowlist,
    get_tool_registry,
)


async def _dummy_handler(args: dict, group_id: str) -> str:
    return f"{group_id}:{args.get('x', '')}"


def test_tool_registry_register_and_openai_schema_generation():
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="dummy_tool",
            description="dummy desc",
            parameters={"type": "object", "properties": {"x": {"type": "string"}}},
            handler=_dummy_handler,
            source="builtin",
        )
    )

    handlers = registry.get_all_handlers()
    schemas = registry.get_openai_schemas()
    assert "dummy_tool" in handlers
    assert len(schemas) == 1
    assert schemas[0]["type"] == "function"
    assert schemas[0]["function"]["name"] == "dummy_tool"


def test_tool_registry_unregister():
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="dummy_tool",
            description="dummy desc",
            parameters={"type": "object", "properties": {}},
            handler=_dummy_handler,
            source="builtin",
        )
    )
    registry.unregister("dummy_tool")
    assert registry.get("dummy_tool") is None


def test_build_effective_allowlist_includes_dynamic_tools_when_enabled():
    registry = get_tool_registry()
    registry.clear_sources({"mcp", "plugin"})
    registry.register(
        ToolDefinition(
            name="mcp_weather",
            description="weather tool",
            parameters={"type": "object", "properties": {}},
            handler=_dummy_handler,
            source="mcp",
        )
    )
    try:
        allowlist = build_effective_allowlist(["web_search"], include_dynamic_sources=True)
        assert "web_search" in allowlist
        assert "mcp_weather" in allowlist
    finally:
        registry.clear_sources({"mcp", "plugin"})


def test_build_effective_allowlist_preserves_empty_semantics():
    allowlist = build_effective_allowlist([], include_dynamic_sources=True)
    assert allowlist == set()
