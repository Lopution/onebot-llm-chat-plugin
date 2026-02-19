"""Runtime state for host adapters.

Core modules read configuration/client state from here, while host adapters
populate runtime state during startup.
"""

from __future__ import annotations

import logging
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Config
    from .mika_api import MikaClient
    from .ports.bot_api import PlatformApiPort
    from .ports.host_events import HostEventPort
    from .ports.logging import LoggerPort
    from .ports.message import MessagePort
    from .ports.paths import PathsPort


_config: Optional[Any] = None
_client: Optional[Any] = None
_paths_port: Optional[Any] = None
_logger_port: Optional[Any] = None
_message_port: Optional[Any] = None
_host_event_port: Optional[Any] = None
_platform_api_port: Optional[Any] = None
_deps_hooks: dict[str, Any] = {}
_tool_overrides: dict[str, Any] = {}
_agent_run_hooks: Optional[Any] = None

log = logging.getLogger(__name__)


class _ConfigProxy:
    """Lazy proxy to runtime config."""

    def __getattr__(self, name: str) -> Any:
        cfg = get_config()
        return getattr(cfg, name)

    def __repr__(self) -> str:
        state = "set" if _config is not None else "unset"
        return f"<ConfigProxy {state}>"


config_proxy = _ConfigProxy()


def set_config(config: "Config") -> None:
    global _config
    _config = config


def get_config() -> "Config":
    global _config
    if _config is None:
        raise RuntimeError("mika_chat_core runtime config is not initialized")
    return _config


def has_config() -> bool:
    return _config is not None


def set_client(client: Optional["MikaClient"]) -> None:
    global _client
    _client = client


def get_client() -> "MikaClient":
    if _client is None:
        raise RuntimeError("mika_chat_core runtime client is not initialized")
    return _client


def set_paths_port(paths_port: Optional["PathsPort"]) -> None:
    global _paths_port
    _paths_port = paths_port


def get_paths_port() -> Optional["PathsPort"]:
    return _paths_port


def set_logger_port(logger_port: Optional["LoggerPort"]) -> None:
    global _logger_port
    _logger_port = logger_port


def get_logger_port() -> Optional["LoggerPort"]:
    return _logger_port


def set_message_port(message_port: Optional["MessagePort"]) -> None:
    global _message_port
    _message_port = message_port


def get_message_port() -> Optional["MessagePort"]:
    return _message_port


def set_host_event_port(host_event_port: Optional["HostEventPort"]) -> None:
    global _host_event_port
    _host_event_port = host_event_port


def get_host_event_port() -> Optional["HostEventPort"]:
    return _host_event_port


def set_platform_api_port(platform_api_port: Optional["PlatformApiPort"]) -> None:
    global _platform_api_port
    _platform_api_port = platform_api_port


def get_platform_api_port() -> Optional["PlatformApiPort"]:
    return _platform_api_port


def set_dep_hook(name: str, hook: Optional[Any]) -> None:
    if hook is None:
        _deps_hooks.pop(name, None)
        return
    _deps_hooks[name] = hook


def get_dep_hook(name: str) -> Optional[Any]:
    return _deps_hooks.get(name)


def set_tool_override(name: str, handler: Optional[Any]) -> None:
    if handler is None:
        _tool_overrides.pop(name, None)
        return
    _tool_overrides[name] = handler


def get_tool_override(name: str) -> Optional[Any]:
    return _tool_overrides.get(name)


def set_agent_run_hooks(hooks: Optional[Any]) -> None:
    global _agent_run_hooks
    _agent_run_hooks = hooks


def get_agent_run_hooks() -> Optional[Any]:
    return _agent_run_hooks


def reset_runtime_state() -> None:
    """Reset all runtime singletons/hooks.

    主要用于测试隔离；宿主正常运行无需调用。
    """
    global _config, _client, _paths_port, _logger_port, _message_port
    global _host_event_port, _platform_api_port, _agent_run_hooks

    _config = None
    _client = None
    _paths_port = None
    _logger_port = None
    _message_port = None
    _host_event_port = None
    _platform_api_port = None
    _agent_run_hooks = None
    _deps_hooks.clear()
    _tool_overrides.clear()
