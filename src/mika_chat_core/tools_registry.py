"""Tool registry for builtin/mcp/plugin tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional


ToolHandler = Callable[[dict[str, Any], str], Awaitable[str]]


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: Dict[str, Any]
    handler: ToolHandler
    source: str = "builtin"  # builtin | mcp | plugin
    enabled: bool = True
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_openai_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": dict(self.parameters or {"type": "object", "properties": {}}),
            },
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition, *, replace: bool = True) -> None:
        name = str(definition.name or "").strip()
        if not name:
            raise ValueError("tool name is required")
        if not callable(definition.handler):
            raise ValueError(f"tool `{name}` handler is not callable")

        normalized = ToolDefinition(
            name=name,
            description=str(definition.description or "").strip(),
            parameters=dict(definition.parameters or {"type": "object", "properties": {}}),
            handler=definition.handler,
            source=str(definition.source or "builtin").strip().lower() or "builtin",
            enabled=bool(definition.enabled),
            meta=dict(definition.meta or {}),
        )
        if not replace and name in self._tools:
            raise ValueError(f"tool `{name}` already exists")
        self._tools[name] = normalized

    def unregister(self, name: str) -> None:
        self._tools.pop(str(name or "").strip(), None)

    def get(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(str(name or "").strip())

    def get_handler(self, name: str) -> Optional[ToolHandler]:
        definition = self.get(name)
        if definition is None or not definition.enabled:
            return None
        return definition.handler

    def get_all_handlers(self, *, include_disabled: bool = False) -> Dict[str, ToolHandler]:
        result: Dict[str, ToolHandler] = {}
        for name, definition in self._tools.items():
            if not include_disabled and not definition.enabled:
                continue
            result[name] = definition.handler
        return result

    def list_tools(
        self,
        *,
        source: Optional[str] = None,
        include_disabled: bool = False,
    ) -> List[ToolDefinition]:
        source_name = str(source or "").strip().lower()
        definitions: List[ToolDefinition] = []
        for definition in self._tools.values():
            if source_name and definition.source != source_name:
                continue
            if not include_disabled and not definition.enabled:
                continue
            definitions.append(definition)
        definitions.sort(key=lambda item: item.name)
        return definitions

    def get_openai_schemas(self) -> List[Dict[str, Any]]:
        return [definition.to_openai_schema() for definition in self.list_tools()]

    def clear_sources(self, sources: set[str]) -> int:
        source_names = {str(item or "").strip().lower() for item in sources if str(item or "").strip()}
        if not source_names:
            return 0
        removed = 0
        for name in list(self._tools.keys()):
            definition = self._tools.get(name)
            if definition is None:
                continue
            if definition.source in source_names:
                removed += 1
                self._tools.pop(name, None)
        return removed

    def names(self, *, source: Optional[str] = None, include_disabled: bool = False) -> set[str]:
        return {item.name for item in self.list_tools(source=source, include_disabled=include_disabled)}

    def set_enabled(self, name: str, enabled: bool) -> bool:
        tool_name = str(name or "").strip()
        definition = self._tools.get(tool_name)
        if definition is None:
            return False
        definition.enabled = bool(enabled)
        return True

    def get_enabled_state(self) -> dict[str, bool]:
        return {name: bool(definition.enabled) for name, definition in self._tools.items()}


_global_registry = ToolRegistry()


def get_tool_registry() -> ToolRegistry:
    return _global_registry


def build_effective_allowlist(
    configured_allowlist: Optional[List[str]],
    *,
    include_dynamic_sources: bool = True,
) -> set[str]:
    allowlist = {str(item or "").strip() for item in list(configured_allowlist or []) if str(item or "").strip()}
    if not allowlist:
        return set()
    if include_dynamic_sources:
        dynamic_names = get_tool_registry().names(source="mcp") | get_tool_registry().names(source="plugin")
        allowlist.update(dynamic_names)
    return allowlist
