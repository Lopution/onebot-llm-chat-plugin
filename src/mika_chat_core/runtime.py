"""Runtime state for host adapters.

Core modules read configuration/client state from here, while host adapters
populate runtime state during startup.
"""

from __future__ import annotations

from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Config
    from .gemini_api import GeminiClient
    from .ports.logging import LoggerPort
    from .ports.paths import PathsPort


_config: Optional[Any] = None
_client: Optional[Any] = None
_paths_port: Optional[Any] = None
_logger_port: Optional[Any] = None
_deps_hooks: dict[str, Any] = {}
_tool_overrides: dict[str, Any] = {}


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
        # Backward-compatible fallback: core modules/tests may access plugin_config
        # before host adapter startup injects runtime config.
        # Use a minimal valid config so legacy unit tests can patch attributes
        # on plugin_config without bootstrapping the host adapter.
        from .config import Config

        _config = Config(gemini_master_id=1, gemini_api_key="A" * 32)
    return _config


def has_config() -> bool:
    return _config is not None


def set_client(client: Optional["GeminiClient"]) -> None:
    global _client
    _client = client


def get_client() -> "GeminiClient":
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
