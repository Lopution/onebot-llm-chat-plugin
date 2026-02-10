"""NoneBot adapter for Mika Chat Core."""

from __future__ import annotations

import os

from nonebot import get_plugin_config
from nonebot import logger as log

from mika_chat_core.runtime import (
    set_config as set_runtime_config,
    set_dep_hook as set_runtime_dep_hook,
    set_host_event_port as set_runtime_host_event_port,
    set_logger_port as set_runtime_logger_port,
    set_message_port as set_runtime_message_port,
    set_paths_port as set_runtime_paths_port,
    set_tool_override as set_runtime_tool_override,
)
from mika_chat_core.settings import Config

STRICT_STARTUP = os.getenv("MIKA_STRICT_STARTUP", "0").strip().lower() in {"1", "true", "yes", "on"}


def _is_missing_dependency_error(exc: Exception) -> bool:
    if isinstance(exc, ModuleNotFoundError):
        return True
    return "No module named" in str(exc)


try:
    from nonebot.plugin import PluginMetadata
except Exception:
    PluginMetadata = None  # type: ignore[assignment]

if PluginMetadata is not None:
    __plugin_meta__ = PluginMetadata(
        name="mika_chat",
        description="NoneBot adapter for Mika Chat Core (OneBot v11/v12)",
        usage="配置 MIKA_LLM_API_KEY（兼容 GEMINI_API_KEY）与 GEMINI_MASTER_ID 后启动；群聊通过 @ 触发回复。",
        type="application",
        homepage="https://github.com/Lopution/mika-chat-core",
        config=Config,
        supported_adapters={"~onebot.v11", "~onebot.v12"},
    )

plugin_config = get_plugin_config(Config)
set_runtime_config(plugin_config)
set_runtime_logger_port(log)

try:
    from .runtime_ports_nb import get_runtime_ports_bundle

    runtime_ports = get_runtime_ports_bundle()
    set_runtime_message_port(runtime_ports.message)
    set_runtime_host_event_port(runtime_ports.host_events)
except Exception as exc:
    log.warning(f"mika_chat: runtime ports 注入失败，使用核心回退实现 | error={exc}")

try:
    from . import deps_nb

    set_runtime_dep_hook("get_chat_history", deps_nb.get_chat_history)
    set_runtime_dep_hook("get_user_profile_data", deps_nb.get_user_profile_data)
    set_runtime_dep_hook("get_processed_images", deps_nb.get_processed_images)
    set_runtime_dep_hook("get_gemini_client_dep", deps_nb.get_gemini_client_dep)
    set_runtime_dep_hook("get_config", deps_nb.get_config)
except Exception as exc:
    log.warning(f"mika_chat: deps hook 注入失败，使用核心回退实现 | error={exc}")

try:
    from . import tools_nb

    set_runtime_tool_override("search_group_history", tools_nb.handle_search_group_history)
    set_runtime_tool_override("fetch_history_images", tools_nb.handle_fetch_history_images)
except Exception as exc:
    log.warning(f"mika_chat: tool override 注入失败，使用核心回退实现 | error={exc}")

try:
    from .paths_nb import LocalstorePathsPort

    set_runtime_paths_port(LocalstorePathsPort())
except Exception as exc:
    log.warning(f"mika_chat: localstore path port 注入失败，使用核心默认路径回退 | error={exc}")

try:
    from nonebot import get_driver

    from .lifecycle_nb import close_gemini, get_gemini_client, init_gemini, set_plugin_config

    set_plugin_config(plugin_config)

    driver = get_driver()
    driver.on_startup(init_gemini)
    driver.on_shutdown(close_gemini)

    try:
        import nonebot_plugin_mika_chat.matchers  # noqa: F401
    except Exception as exc:
        if STRICT_STARTUP or not _is_missing_dependency_error(exc):
            raise
        log.warning(
            "mika_chat: matcher 注册失败，已跳过"
            f"（可设置 MIKA_STRICT_STARTUP=1 强制失败）| error={exc}"
        )
except Exception as exc:
    if STRICT_STARTUP or not _is_missing_dependency_error(exc):
        raise
    log.warning(
        "mika_chat: 生命周期注册失败，已降级到最小模式"
        f"（可设置 MIKA_STRICT_STARTUP=1 强制失败）| error={exc}"
    )

    async def init_gemini():  # type: ignore[no-redef]
        return None

    async def close_gemini():  # type: ignore[no-redef]
        return None

    def set_plugin_config(_config: Config):  # type: ignore[no-redef]
        set_runtime_config(_config)
        return None

    def get_gemini_client():  # type: ignore[no-redef]
        raise RuntimeError("mika_chat: get_gemini_client unavailable in minimal test environment")


__all__ = ["plugin_config", "get_gemini_client"]
