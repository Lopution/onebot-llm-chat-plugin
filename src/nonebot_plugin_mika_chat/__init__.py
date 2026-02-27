"""NoneBot adapter for Mika Chat Core."""

from __future__ import annotations

from nonebot import get_plugin_config
from nonebot import logger as log

from mika_chat_core.runtime import (
    set_config as set_runtime_config,
    set_host_event_port as set_runtime_host_event_port,
    set_agent_run_hooks as set_runtime_agent_run_hooks,
    set_logger_port as set_runtime_logger_port,
    set_message_port as set_runtime_message_port,
    set_paths_port as set_runtime_paths_port,
    set_platform_api_port as set_runtime_platform_api_port,
    set_tool_override as set_runtime_tool_override,
)
from mika_chat_core.config import Config

try:
    from nonebot.plugin import PluginMetadata
except Exception:
    PluginMetadata = None  # type: ignore[assignment]

if PluginMetadata is not None:
    __plugin_meta__ = PluginMetadata(
        name="mika_chat",
        description="NoneBot adapter for Mika Chat Core (OneBot v11/v12)",
        usage="配置 LLM_API_KEY 和 MIKA_MASTER_ID 后启动；群聊通过 @ 触发回复。",
        type="application",
        homepage="https://github.com/Lopution/mika-chat-core",
        config=Config,
        supported_adapters={"~onebot.v11", "~onebot.v12"},
    )

plugin_config = get_plugin_config(Config)
set_runtime_config(plugin_config)
set_runtime_logger_port(log)
try:
    from mika_chat_core.observability.trace_store import TraceAgentHooks

    set_runtime_agent_run_hooks(TraceAgentHooks())
except Exception as exc:  # pragma: no cover - optional
    log.warning("Trace hooks init failed (ignored): %s", exc)

from .runtime_ports_nb import get_runtime_ports_bundle

runtime_ports = get_runtime_ports_bundle()
set_runtime_message_port(runtime_ports.message)
set_runtime_host_event_port(runtime_ports.host_events)
set_runtime_platform_api_port(runtime_ports.platform_api)

from . import tools_nb

set_runtime_tool_override("search_group_history", tools_nb.handle_search_group_history)
set_runtime_tool_override("fetch_history_images", tools_nb.handle_fetch_history_images)

from .paths_nb import LocalstorePathsPort

set_runtime_paths_port(LocalstorePathsPort())

from nonebot import get_driver

_lifecycle_import_error: Exception | None = None
_lifecycle_close = None
_lifecycle_get_client = None
_lifecycle_init = None
_lifecycle_set_config = None
_matchers_import_error: Exception | None = None
try:
    from .lifecycle_nb import (
        close_mika as _lifecycle_close,
        get_mika_client as _lifecycle_get_client,
        init_mika as _lifecycle_init,
        set_plugin_config as _lifecycle_set_config,
    )
except Exception as exc:  # pragma: no cover - runtime dependency gate
    _lifecycle_import_error = exc


def _raise_lifecycle_import_error() -> None:
    assert _lifecycle_import_error is not None
    raise RuntimeError(
        "nonebot_plugin_mika_chat lifecycle unavailable; "
        "please install optional dependencies (e.g. fastapi)."
    ) from _lifecycle_import_error


async def init_mika() -> None:
    if _lifecycle_import_error is not None or _lifecycle_init is None:
        _raise_lifecycle_import_error()
    if _matchers_import_error is not None:
        raise RuntimeError(
            "nonebot_plugin_mika_chat matchers unavailable; "
            "please install compatible nonebot adapters."
        ) from _matchers_import_error
    await _lifecycle_init()


async def close_mika() -> None:
    if _lifecycle_import_error is not None or _lifecycle_close is None:
        return
    await _lifecycle_close()


def get_mika_client():
    if _lifecycle_import_error is not None or _lifecycle_get_client is None:
        _raise_lifecycle_import_error()
    return _lifecycle_get_client()


def set_plugin_config(config):
    if _lifecycle_import_error is not None or _lifecycle_set_config is None:
        _raise_lifecycle_import_error()
    _lifecycle_set_config(config)


if _lifecycle_import_error is None:
    set_plugin_config(plugin_config)
else:
    log.error(
        "lifecycle_nb import failed; plugin will fail fast on startup: %s",
        _lifecycle_import_error,
    )

driver = get_driver()
driver.on_startup(init_mika)
driver.on_shutdown(close_mika)

try:
    import nonebot_plugin_mika_chat.matchers  # noqa: F401
except Exception as exc:  # pragma: no cover - runtime dependency gate
    _matchers_import_error = exc
    log.error(
        "matchers import failed; plugin will fail fast on startup: %s",
        _matchers_import_error,
    )


__all__ = ["plugin_config", "get_mika_client"]
