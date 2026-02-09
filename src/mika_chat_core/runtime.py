"""Runtime state for host adapters.

Core modules read configuration/client state from here, while host adapters
populate runtime state during startup.
"""

from __future__ import annotations

from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Config
    from .gemini_api import GeminiClient
    from .ports.paths import PathsPort


_config: Optional[Any] = None
_client: Optional[Any] = None
_paths_port: Optional[Any] = None


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
