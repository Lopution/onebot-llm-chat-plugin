"""Tool plugin discovery/loader utilities."""

from __future__ import annotations

import importlib
import importlib.metadata as metadata
import inspect
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any, Iterable, List, Sequence

from .infra.logging import logger
from .tools_plugin import ToolPlugin
from .tools_registry import ToolDefinition, ToolRegistry, get_tool_registry


_PLUGIN_ENTRYPOINT_GROUP = "mika_chat.tools"
_MODULE_DEFAULT_ATTR = "Plugin"


@dataclass
class LoadedToolPlugin:
    """Runtime record for a loaded plugin."""

    plugin: ToolPlugin
    source: str
    registered_tools: List[str] = field(default_factory=list)
    replaced_tools: List[ToolDefinition] = field(default_factory=list)


class ToolPluginManager:
    """Discover/load/unload tool plugins and wire them into ToolRegistry."""

    def __init__(self, *, registry: ToolRegistry | None = None) -> None:
        self._registry = registry or get_tool_registry()
        self._loaded: list[LoadedToolPlugin] = []

    def loaded_plugins(self) -> list[LoadedToolPlugin]:
        return list(self._loaded)

    async def load(self, configured_plugins: Sequence[str] | None = None) -> int:
        discovered = self.discover(configured_plugins=configured_plugins)
        loaded_count = 0
        for source, plugin in discovered:
            try:
                await self._call_optional_async(plugin, "on_load")
                replaced_tools = self._capture_replaced_tools(plugin)
                tool_names = self._register_plugin_tools(plugin)
                self._loaded.append(
                    LoadedToolPlugin(
                        plugin=plugin,
                        source=source,
                        registered_tools=tool_names,
                        replaced_tools=replaced_tools,
                    )
                )
                loaded_count += 1
                logger.info(
                    f"工具插件已加载 | plugin={getattr(plugin, 'name', type(plugin).__name__)} "
                    f"| source={source} | tools={len(tool_names)}"
                )
            except Exception as exc:
                logger.warning(f"工具插件加载失败 | source={source} | error={exc}")
        return loaded_count

    async def unload(self) -> int:
        unloaded = 0
        for record in reversed(self._loaded):
            try:
                await self._call_optional_async(record.plugin, "on_unload")
            except Exception as exc:
                logger.warning(
                    f"工具插件卸载回调失败 | plugin={getattr(record.plugin, 'name', type(record.plugin).__name__)} "
                    f"| error={exc}"
                )

            for tool_name in record.registered_tools:
                self._registry.unregister(tool_name)
            for definition in record.replaced_tools:
                self._registry.register(definition, replace=True)
            unloaded += 1
        self._loaded.clear()
        return unloaded

    def discover(self, configured_plugins: Sequence[str] | None = None) -> list[tuple[str, ToolPlugin]]:
        discovered: list[tuple[str, ToolPlugin]] = []
        seen: set[tuple[str, str]] = set()

        for name, plugin in self._discover_entrypoint_plugins():
            identity = (getattr(plugin, "name", type(plugin).__name__), name)
            if identity in seen:
                continue
            seen.add(identity)
            discovered.append((f"entrypoint:{name}", plugin))

        for module_path in list(configured_plugins or []):
            path = str(module_path or "").strip()
            if not path:
                continue
            plugin = self._load_plugin_from_module_path(path)
            if plugin is None:
                continue
            identity = (getattr(plugin, "name", type(plugin).__name__), path)
            if identity in seen:
                continue
            seen.add(identity)
            discovered.append((f"module:{path}", plugin))

        return discovered

    def _discover_entrypoint_plugins(self) -> list[tuple[str, ToolPlugin]]:
        results: list[tuple[str, ToolPlugin]] = []
        try:
            entry_points = metadata.entry_points()
        except Exception as exc:
            logger.warning(f"读取工具插件 entry points 失败: {exc}")
            return results

        selected: Iterable[Any]
        if hasattr(entry_points, "select"):
            selected = entry_points.select(group=_PLUGIN_ENTRYPOINT_GROUP)
        else:
            selected = entry_points.get(_PLUGIN_ENTRYPOINT_GROUP, [])  # type: ignore[assignment]

        for ep in selected:
            ep_name = str(getattr(ep, "name", "") or "").strip()
            if not ep_name:
                continue
            try:
                target = ep.load()
                plugin = self._instantiate_plugin(target)
                if plugin is None:
                    raise TypeError("entry point did not resolve to ToolPlugin")
                results.append((ep_name, plugin))
            except Exception as exc:
                logger.warning(f"加载工具插件 entry point 失败 | entry={ep_name} | error={exc}")
        return results

    def _load_plugin_from_module_path(self, module_path: str) -> ToolPlugin | None:
        module_name, attr_name = self._split_module_path(module_path)
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            logger.warning(f"导入工具插件模块失败 | module={module_name} | error={exc}")
            return None

        target = self._resolve_module_target(module, attr_name)
        if target is None:
            logger.warning(f"工具插件模块缺少目标对象 | module={module_name} | attr={attr_name}")
            return None
        plugin = self._instantiate_plugin(target)
        if plugin is None:
            logger.warning(f"工具插件对象不符合协议 | module={module_path}")
            return None
        return plugin

    @staticmethod
    def _split_module_path(module_path: str) -> tuple[str, str]:
        if ":" in module_path:
            module_name, attr_name = module_path.split(":", 1)
            return module_name.strip(), (attr_name.strip() or _MODULE_DEFAULT_ATTR)
        return module_path.strip(), _MODULE_DEFAULT_ATTR

    @staticmethod
    def _resolve_module_target(module: ModuleType, attr_name: str) -> Any | None:
        if hasattr(module, attr_name):
            return getattr(module, attr_name)
        if attr_name != _MODULE_DEFAULT_ATTR and hasattr(module, _MODULE_DEFAULT_ATTR):
            return getattr(module, _MODULE_DEFAULT_ATTR)
        return None

    @staticmethod
    def _instantiate_plugin(target: Any) -> ToolPlugin | None:
        candidate = target
        if inspect.isclass(target):
            candidate = target()
        elif callable(target) and not isinstance(target, ToolPlugin):
            try:
                candidate = target()
            except TypeError:
                candidate = target

        if isinstance(candidate, ToolPlugin):
            return candidate

        if all(hasattr(candidate, attr) for attr in ("name", "version", "get_tools")):
            return candidate  # type: ignore[return-value]
        return None

    def _register_plugin_tools(self, plugin: ToolPlugin) -> list[str]:
        tool_defs = plugin.get_tools()
        if not isinstance(tool_defs, list):
            raise TypeError("plugin.get_tools() must return list[ToolDefinition]")

        registered: list[str] = []
        for definition in tool_defs:
            if not isinstance(definition, ToolDefinition):
                raise TypeError("plugin tools must be ToolDefinition instances")
            normalized = ToolDefinition(
                name=definition.name,
                description=definition.description,
                parameters=definition.parameters,
                handler=definition.handler,
                source="plugin",
                enabled=definition.enabled,
                meta=dict(definition.meta or {}),
            )
            self._registry.register(normalized, replace=True)
            registered.append(normalized.name)
        return registered

    def _capture_replaced_tools(self, plugin: ToolPlugin) -> list[ToolDefinition]:
        replaced: list[ToolDefinition] = []
        tool_defs = plugin.get_tools()
        if not isinstance(tool_defs, list):
            return replaced
        for definition in tool_defs:
            if not isinstance(definition, ToolDefinition):
                continue
            existing = self._registry.get(definition.name)
            if existing is not None:
                replaced.append(existing)
        return replaced

    @staticmethod
    async def _call_optional_async(plugin: ToolPlugin, method_name: str) -> None:
        callback = getattr(plugin, method_name, None)
        if callback is None:
            return
        result = callback()
        if inspect.isawaitable(result):
            await result
