from __future__ import annotations

import sys
import types

import pytest

from mika_chat_core.tools_loader import ToolPluginManager
from mika_chat_core.tools_registry import ToolDefinition, ToolRegistry


async def _builtin_echo_handler(args: dict, group_id: str) -> str:
    return f"builtin:{group_id}:{args.get('x', '')}"


async def _plugin_echo_handler(args: dict, group_id: str) -> str:
    return f"plugin:{group_id}:{args.get('x', '')}"


class _DemoPlugin:
    name = "demo_plugin"
    version = "0.1.0"

    def __init__(self) -> None:
        self.loaded = False
        self.unloaded = False

    def get_tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="echo_tool",
                description="echo",
                parameters={"type": "object", "properties": {"x": {"type": "string"}}},
                handler=_plugin_echo_handler,
                source="plugin",
            )
        ]

    async def on_load(self) -> None:
        self.loaded = True

    async def on_unload(self) -> None:
        self.unloaded = True


@pytest.mark.asyncio
async def test_tool_plugin_manager_load_and_unload_module_plugin():
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="echo_tool",
            description="builtin",
            parameters={"type": "object", "properties": {}},
            handler=_builtin_echo_handler,
            source="builtin",
        )
    )
    manager = ToolPluginManager(registry=registry)

    module_name = "tests._plugin_demo_module"
    module = types.ModuleType(module_name)
    module.Plugin = _DemoPlugin
    sys.modules[module_name] = module

    try:
        loaded = await manager.load(configured_plugins=[module_name])
        assert loaded == 1

        definition = registry.get("echo_tool")
        assert definition is not None
        assert definition.source == "plugin"
        handler = registry.get_handler("echo_tool")
        assert handler is not None
        assert await handler({"x": "ok"}, "group:1") == "plugin:group:1:ok"

        unloaded = await manager.unload()
        assert unloaded == 1
        restored = registry.get("echo_tool")
        assert restored is not None
        assert restored.source == "builtin"
        restored_handler = registry.get_handler("echo_tool")
        assert restored_handler is not None
        assert await restored_handler({"x": "ok"}, "group:1") == "builtin:group:1:ok"
    finally:
        sys.modules.pop(module_name, None)


class _FakeEntryPoint:
    def __init__(self, name: str, target):
        self.name = name
        self._target = target

    def load(self):
        return self._target


class _FakeEntryPoints:
    def __init__(self, items):
        self._items = items

    def select(self, *, group: str):
        if group == "mika_chat.tools":
            return list(self._items)
        return []


@pytest.mark.asyncio
async def test_tool_plugin_manager_discovers_entrypoint_plugins(monkeypatch):
    registry = ToolRegistry()
    manager = ToolPluginManager(registry=registry)
    fake_eps = _FakeEntryPoints([_FakeEntryPoint("demo", _DemoPlugin)])
    monkeypatch.setattr("mika_chat_core.tools_loader.metadata.entry_points", lambda: fake_eps)

    loaded = await manager.load(configured_plugins=[])
    assert loaded == 1
    definition = registry.get("echo_tool")
    assert definition is not None
    assert definition.source == "plugin"


@pytest.mark.asyncio
async def test_tool_plugin_manager_handles_bad_module_gracefully(monkeypatch):
    registry = ToolRegistry()
    manager = ToolPluginManager(registry=registry)
    monkeypatch.setattr("mika_chat_core.tools_loader.metadata.entry_points", lambda: _FakeEntryPoints([]))

    loaded = await manager.load(configured_plugins=["module.that.does.not.exist"])
    assert loaded == 0
    assert registry.list_tools() == []
