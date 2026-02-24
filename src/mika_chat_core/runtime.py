"""Runtime state for host adapters.

Core modules read configuration/client state from here, while host adapters
populate runtime state during startup.

All state lives inside a single ``AppRuntime`` container.  The module-level
``get_*/set_*`` functions are backward-compatible proxies so that existing
call sites do not need to change.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Config
    from .mika_api import MikaClient
    from .ports.bot_api import PlatformApiPort
    from .ports.host_events import HostEventPort
    from .ports.logging import LoggerPort
    from .ports.message import MessagePort
    from .ports.paths import PathsPort
    from .task_supervisor import TaskSupervisor

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# AppRuntime container
# ---------------------------------------------------------------------------

@dataclass
class AppRuntime:
    """Centralized container for all mutable runtime state.

    Replaces scattered module-level globals.  Accessible via
    ``get_runtime()`` or through the legacy ``get_*/set_*`` helpers.
    """

    config: Optional[Any] = None
    client: Optional[Any] = None
    task_supervisor: Optional[Any] = None

    # Ports (host-adapter layer)
    paths_port: Optional[Any] = None
    logger_port: Optional[Any] = None
    message_port: Optional[Any] = None
    host_event_port: Optional[Any] = None
    platform_api_port: Optional[Any] = None

    # Extension points
    agent_run_hooks: Optional[Any] = None
    deps_hooks: dict[str, Any] = field(default_factory=dict)
    tool_overrides: dict[str, Any] = field(default_factory=dict)


_runtime = AppRuntime()


def get_runtime() -> AppRuntime:
    """Return the global ``AppRuntime`` container."""
    return _runtime


# ---------------------------------------------------------------------------
# Config proxy (lazy attribute access)
# ---------------------------------------------------------------------------

class _ConfigProxy:
    """Lazy proxy to runtime config."""

    def __getattr__(self, name: str) -> Any:
        cfg = get_config()
        return getattr(cfg, name)

    def __repr__(self) -> str:
        state = "set" if _runtime.config is not None else "unset"
        return f"<ConfigProxy {state}>"


config_proxy = _ConfigProxy()


# ---------------------------------------------------------------------------
# Backward-compatible get/set helpers
# ---------------------------------------------------------------------------

def set_config(config: "Config") -> None:
    _runtime.config = config


def get_config() -> "Config":
    if _runtime.config is None:
        raise RuntimeError("mika_chat_core runtime config is not initialized")
    return _runtime.config


def has_config() -> bool:
    return _runtime.config is not None


def set_client(client: Optional["MikaClient"]) -> None:
    _runtime.client = client


def get_client() -> "MikaClient":
    if _runtime.client is None:
        raise RuntimeError("mika_chat_core runtime client is not initialized")
    return _runtime.client


def set_paths_port(paths_port: Optional["PathsPort"]) -> None:
    _runtime.paths_port = paths_port


def get_paths_port() -> Optional["PathsPort"]:
    return _runtime.paths_port


def set_logger_port(logger_port: Optional["LoggerPort"]) -> None:
    _runtime.logger_port = logger_port


def get_logger_port() -> Optional["LoggerPort"]:
    return _runtime.logger_port


def set_message_port(message_port: Optional["MessagePort"]) -> None:
    _runtime.message_port = message_port


def get_message_port() -> Optional["MessagePort"]:
    return _runtime.message_port


def set_host_event_port(host_event_port: Optional["HostEventPort"]) -> None:
    _runtime.host_event_port = host_event_port


def get_host_event_port() -> Optional["HostEventPort"]:
    return _runtime.host_event_port


def set_platform_api_port(platform_api_port: Optional["PlatformApiPort"]) -> None:
    _runtime.platform_api_port = platform_api_port


def get_platform_api_port() -> Optional["PlatformApiPort"]:
    return _runtime.platform_api_port


def set_dep_hook(name: str, hook: Optional[Any]) -> None:
    if hook is None:
        _runtime.deps_hooks.pop(name, None)
        return
    _runtime.deps_hooks[name] = hook


def get_dep_hook(name: str) -> Optional[Any]:
    return _runtime.deps_hooks.get(name)


def set_tool_override(name: str, handler: Optional[Any]) -> None:
    if handler is None:
        _runtime.tool_overrides.pop(name, None)
        return
    _runtime.tool_overrides[name] = handler


def get_tool_override(name: str) -> Optional[Any]:
    return _runtime.tool_overrides.get(name)


def set_agent_run_hooks(hooks: Optional[Any]) -> None:
    _runtime.agent_run_hooks = hooks


def get_agent_run_hooks() -> Optional[Any]:
    return _runtime.agent_run_hooks


def set_task_supervisor(supervisor: Optional["TaskSupervisor"]) -> None:
    _runtime.task_supervisor = supervisor


def get_task_supervisor() -> "TaskSupervisor":
    if _runtime.task_supervisor is None:
        from .task_supervisor import TaskSupervisor

        _runtime.task_supervisor = TaskSupervisor()
    return _runtime.task_supervisor


def reset_runtime_state() -> None:
    """Reset all runtime singletons/hooks.

    主要用于测试隔离；宿主正常运行无需调用。
    """
    global _runtime
    _runtime = AppRuntime()
