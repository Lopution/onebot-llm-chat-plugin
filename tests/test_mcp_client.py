from __future__ import annotations

import json

import pytest

from mika_chat_core.mcp_client import McpServerConfig, McpToolClient, parse_mcp_server_configs
from mika_chat_core.tools_registry import ToolRegistry


class _FakeBackend:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    async def list_tools(self, server: McpServerConfig):
        return [
            {
                "name": "get_weather",
                "description": f"weather from {server.name}",
                "input_schema": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            }
        ]

    async def call_tool(self, *, server: McpServerConfig, tool_name: str, arguments: dict):
        self.calls.append((server.name, tool_name, dict(arguments or {})))
        return {"server": server.name, "tool": tool_name, "args": dict(arguments or {})}

    async def close(self) -> None:
        return None


def test_parse_mcp_server_configs_filters_invalid_items():
    configs = parse_mcp_server_configs(
        [
            {"name": "weather", "command": "npx", "args": ["-y", "tool"]},
            {"name": "", "command": "python"},
            "bad-item",
        ]
    )
    assert len(configs) == 1
    assert configs[0].name == "weather"
    assert configs[0].command == "npx"


@pytest.mark.asyncio
async def test_mcp_tool_client_registers_and_calls_proxy_handler():
    registry = ToolRegistry()
    backend = _FakeBackend()
    client = McpToolClient(registry=registry, backend=backend)
    server = McpServerConfig(name="weather", command="npx", args=["-y", "tool"])

    count = await client.connect(server)
    assert count == 1

    definition = registry.get("get_weather")
    assert definition is not None
    assert definition.source == "mcp"

    handler = registry.get_handler("get_weather")
    assert handler is not None
    result = await handler({"city": "beijing"}, "group:1")
    payload = json.loads(result)
    assert payload["server"] == "weather"
    assert payload["tool"] == "get_weather"
    assert payload["args"]["city"] == "beijing"

    assert backend.calls == [("weather", "get_weather", {"city": "beijing"})]


@pytest.mark.asyncio
async def test_mcp_tool_client_connect_all_aggregates_count():
    registry = ToolRegistry()
    backend = _FakeBackend()
    client = McpToolClient(registry=registry, backend=backend)
    servers = [
        McpServerConfig(name="s1", command="cmd1"),
        McpServerConfig(name="s2", command="cmd2"),
    ]

    count = await client.connect_all(servers)
    assert count == 2
    assert registry.get("get_weather") is not None


@pytest.mark.asyncio
async def test_mcp_tool_client_namespaces_duplicate_tool_names():
    registry = ToolRegistry()
    backend = _FakeBackend()
    client = McpToolClient(registry=registry, backend=backend)

    count1 = await client.connect(McpServerConfig(name="s1", command="cmd1"))
    count2 = await client.connect(McpServerConfig(name="s2", command="cmd2"))
    assert count1 == 1
    assert count2 == 1

    assert registry.get("get_weather") is not None
    assert registry.get("s2:get_weather") is not None

    handler = registry.get_handler("s2:get_weather")
    assert handler is not None
    result = await handler({"city": "shanghai"}, "group:1")
    payload = json.loads(result)
    assert payload["server"] == "s2"
    assert payload["tool"] == "get_weather"
