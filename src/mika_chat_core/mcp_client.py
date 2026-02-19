"""MCP tool client and dynamic registry integration."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

from .infra.logging import logger as log
from .runtime import get_dep_hook
from .tools_registry import ToolDefinition, ToolRegistry, get_tool_registry


@dataclass
class McpServerConfig:
    name: str
    command: str = ""
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    transport: str = "stdio"
    endpoint: str = ""
    timeout_seconds: float = 20.0


class McpBackend(Protocol):
    async def list_tools(self, server: McpServerConfig) -> List[Dict[str, Any]]:
        ...

    async def call_tool(
        self,
        *,
        server: McpServerConfig,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> Any:
        ...

    async def close(self) -> None:
        ...


class DisabledMcpBackend:
    async def list_tools(self, server: McpServerConfig) -> List[Dict[str, Any]]:
        log.warning(
            f"MCP backend 不可用，跳过服务器 `{server.name}`（可通过 runtime dep hook `mcp_backend` 注入实现）"
        )
        return []

    async def call_tool(
        self,
        *,
        server: McpServerConfig,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> Any:
        raise RuntimeError(f"MCP backend is disabled, cannot call {server.name}.{tool_name}")

    async def close(self) -> None:
        return None


class SdkMcpBackend:
    """Best-effort MCP backend via official `mcp` Python SDK."""

    def __init__(self) -> None:
        from mcp import ClientSession, StdioServerParameters  # type: ignore
        from mcp.client.stdio import stdio_client  # type: ignore

        self._ClientSession = ClientSession
        self._StdioServerParameters = StdioServerParameters
        self._stdio_client = stdio_client

    async def list_tools(self, server: McpServerConfig) -> List[Dict[str, Any]]:
        session_result = await self._run_session_method(server, "list_tools")
        tools = getattr(session_result, "tools", session_result)
        if not isinstance(tools, list):
            return []
        parsed: List[Dict[str, Any]] = []
        for item in tools:
            if isinstance(item, dict):
                parsed.append(item)
                continue
            parsed.append(
                {
                    "name": str(getattr(item, "name", "") or "").strip(),
                    "description": str(getattr(item, "description", "") or "").strip(),
                    "input_schema": getattr(item, "inputSchema", None)
                    or getattr(item, "input_schema", None)
                    or {"type": "object", "properties": {}},
                }
            )
        return parsed

    async def call_tool(
        self,
        *,
        server: McpServerConfig,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> Any:
        return await self._run_session_method(
            server,
            "call_tool",
            tool_name,
            dict(arguments or {}),
        )

    async def close(self) -> None:
        return None

    async def _run_session_method(self, server: McpServerConfig, method: str, *args: Any) -> Any:
        if server.transport != "stdio":
            raise RuntimeError(f"unsupported mcp transport: {server.transport}")
        params = self._StdioServerParameters(
            command=server.command,
            args=list(server.args or []),
            env=dict(server.env or {}) or None,
        )
        async with self._stdio_client(params) as stdio:
            try:
                read_stream, write_stream = stdio
            except Exception:
                read_stream = getattr(stdio, "read", None)
                write_stream = getattr(stdio, "write", None)
            async with self._ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                operation = getattr(session, method)
                return await operation(*args)


def parse_mcp_server_configs(raw_servers: Any) -> List[McpServerConfig]:
    if not isinstance(raw_servers, list):
        return []

    parsed: List[McpServerConfig] = []
    for item in raw_servers:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        args_raw = item.get("args")
        args = [str(arg) for arg in args_raw] if isinstance(args_raw, list) else []
        env_raw = item.get("env")
        env = (
            {str(key): str(value) for key, value in env_raw.items()}
            if isinstance(env_raw, dict)
            else {}
        )
        parsed.append(
            McpServerConfig(
                name=name,
                command=str(item.get("command") or "").strip(),
                args=args,
                env=env,
                transport=str(item.get("transport") or "stdio").strip().lower() or "stdio",
                endpoint=str(item.get("endpoint") or "").strip(),
                timeout_seconds=float(item.get("timeout_seconds") or 20.0),
            )
        )
    return parsed


class McpToolClient:
    """Connect MCP servers and register discovered tools into ToolRegistry."""

    def __init__(
        self,
        *,
        registry: Optional[ToolRegistry] = None,
        backend: Optional[McpBackend] = None,
    ) -> None:
        self._registry = registry or get_tool_registry()
        self._backend = backend or self._resolve_backend()
        self._tool_server_map: Dict[str, McpServerConfig] = {}
        self._tool_actual_name_map: Dict[str, str] = {}

    def _resolve_backend(self) -> McpBackend:
        hook = get_dep_hook("mcp_backend")
        if hook is not None:
            candidate = hook() if callable(hook) else hook
            if all(
                hasattr(candidate, attr)
                for attr in ("list_tools", "call_tool", "close")
            ):
                return candidate  # type: ignore[return-value]
            log.warning("runtime dep hook `mcp_backend` 不符合接口要求，使用 DisabledMcpBackend")
        try:
            return SdkMcpBackend()
        except Exception:
            pass
        return DisabledMcpBackend()

    def _resolve_registry_tool_name(self, *, server_name: str, tool_name: str) -> str:
        existing_server = self._tool_server_map.get(tool_name)
        if existing_server is None or existing_server.name == server_name:
            return tool_name

        base = f"{server_name}:{tool_name}"
        candidate = base
        suffix = 2
        while True:
            mapped_server = self._tool_server_map.get(candidate)
            if mapped_server is None or mapped_server.name == server_name:
                break
            candidate = f"{base}#{suffix}"
            suffix += 1

        log.warning(
            f"MCP 工具名冲突 | tool={tool_name} | existing_server={existing_server.name} | "
            f"new_server={server_name} | renamed={candidate}"
        )
        return candidate

    async def connect(self, server: McpServerConfig) -> int:
        discovered = await self._backend.list_tools(server)
        registered = 0
        for raw_tool in discovered:
            if not isinstance(raw_tool, dict):
                continue
            tool_name = str(raw_tool.get("name") or "").strip()
            if not tool_name:
                continue
            registry_name = self._resolve_registry_tool_name(
                server_name=server.name,
                tool_name=tool_name,
            )

            description = str(raw_tool.get("description") or f"MCP tool from {server.name}")
            parameters = raw_tool.get("input_schema") or raw_tool.get("parameters") or {
                "type": "object",
                "properties": {},
            }
            if not isinstance(parameters, dict):
                parameters = {"type": "object", "properties": {}}

            async def _proxy_handler(
                args: dict[str, Any],
                group_id: str,
                *,
                _server_name: str = server.name,
                _registry_tool_name: str = registry_name,
            ) -> str:
                del group_id
                result = await self.call_tool(
                    server_name=_server_name,
                    tool_name=_registry_tool_name,
                    arguments=dict(args or {}),
                )
                return self._stringify_tool_result(result)

            self._registry.register(
                ToolDefinition(
                    name=registry_name,
                    description=description,
                    parameters=dict(parameters),
                    handler=_proxy_handler,
                    source="mcp",
                    enabled=True,
                    meta={
                        "mcp_server": server.name,
                        "mcp_tool_name": tool_name,
                    },
                ),
                replace=True,
            )
            self._tool_server_map[registry_name] = server
            self._tool_actual_name_map[registry_name] = tool_name
            registered += 1

        if registered > 0:
            log.info(f"MCP 工具注册完成 | server={server.name} | tools={registered}")
        else:
            log.info(f"MCP 服务器无可注册工具 | server={server.name}")
        return registered

    async def connect_all(self, servers: List[McpServerConfig]) -> int:
        total = 0
        for server in servers:
            try:
                total += await self.connect(server)
            except Exception as exc:
                log.warning(f"MCP 服务器连接失败 | server={server.name} | error={exc}")
        return total

    async def call_tool(
        self,
        *,
        server_name: str,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> Any:
        server = self._tool_server_map.get(tool_name)
        if server is None:
            raise RuntimeError(f"unknown mcp tool: {tool_name}")
        if server.name != server_name:
            raise RuntimeError(
                f"mcp tool server mismatch: {tool_name} is bound to {server.name}, got {server_name}"
            )
        actual_tool_name = str(self._tool_actual_name_map.get(tool_name) or tool_name)
        return await self._backend.call_tool(
            server=server,
            tool_name=actual_tool_name,
            arguments=dict(arguments or {}),
        )

    async def close(self) -> None:
        await self._backend.close()

    @staticmethod
    def _stringify_tool_result(result: Any) -> str:
        if result is None:
            return ""
        if isinstance(result, str):
            return result
        if isinstance(result, (dict, list)):
            return json.dumps(result, ensure_ascii=False)
        return str(result)
