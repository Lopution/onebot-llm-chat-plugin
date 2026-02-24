"""Tool plugin protocol contracts."""

from __future__ import annotations

from typing import List, Protocol, runtime_checkable

from .tools_registry import ToolDefinition


@runtime_checkable
class ToolPlugin(Protocol):
    """Tool plugin contract for external/extensions modules."""

    name: str
    version: str

    def get_tools(self) -> List[ToolDefinition]:
        """Return tool definitions to be registered."""
        ...

    async def on_load(self) -> None:
        """Optional lifecycle hook invoked before tool registration."""
        ...

    async def on_unload(self) -> None:
        """Optional lifecycle hook invoked before tool unregistration."""
        ...
