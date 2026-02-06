# Gemini Chat 插件
"""
NoneBot2 Gemini Chat 插件

一个基于 OpenAI 兼容格式 API 调用 Gemini 模型的智能聊天插件，支持：
- 私聊和群聊对话
- 多轮上下文记忆
- 图片识别
- 搜索引擎集成
- 群聊历史查询
"""

"""Gemini Chat 插件包入口。

生产环境下会在 import 时注册生命周期钩子并加载 matcher。
但在精简测试环境（缺少完整 NoneBot/依赖）下，不能因为副作用导致 import 失败。

因此这里采用“尽力初始化”：
- 始终暴露 plugin_config
- lifecycle/matchers 等可选模块若因依赖缺失导入失败，则跳过副作用初始化
"""

import os

from nonebot import get_plugin_config
from nonebot import logger as log

from .config import Config

STRICT_STARTUP = os.getenv("MIKA_STRICT_STARTUP", "0").strip().lower() in {"1", "true", "yes", "on"}


def _is_missing_dependency_error(exc: Exception) -> bool:
    if isinstance(exc, ModuleNotFoundError):
        return True
    text = str(exc)
    if "No module named" in text:
        return True
    return False

try:
    from nonebot.plugin import PluginMetadata
except Exception:
    PluginMetadata = None  # type: ignore[assignment]

if PluginMetadata is not None:
    __plugin_meta__ = PluginMetadata(
        name="gemini_chat",
        description="基于 OneBot 协议的 Gemini 聊天插件（v11/v12 best-effort 兼容）",
        usage="配置 GEMINI_API_KEY 和 GEMINI_MASTER_ID 后启动；群聊通过 @ 触发回复。",
        type="application",
        homepage="https://github.com/Lopution/onebot-llm-chat-plugin",
        config=Config,
        supported_adapters={"~onebot.v11", "~onebot.v12"},
    )


# 获取并设置插件配置（tests 也会依赖这个符号存在）
plugin_config = get_plugin_config(Config)


# 尝试注册生命周期钩子（测试环境可降级跳过）
try:
    from nonebot import get_driver

    from .lifecycle import close_gemini, get_gemini_client, init_gemini, set_plugin_config

    set_plugin_config(plugin_config)

    driver = get_driver()
    driver.on_startup(init_gemini)
    driver.on_shutdown(close_gemini)

    # 导入匹配器以注册事件处理（测试环境可能不存在完整 adapter）
    try:
        from . import matchers  # noqa: F401, E402
    except Exception as exc:
        if STRICT_STARTUP or not _is_missing_dependency_error(exc):
            raise
        log.warning(f"gemini_chat: matcher 注册失败，已跳过（可设置 MIKA_STRICT_STARTUP=1 强制失败）| error={exc}")
except Exception as exc:
    if STRICT_STARTUP or not _is_missing_dependency_error(exc):
        raise
    log.warning(f"gemini_chat: 生命周期注册失败，已降级到最小模式（可设置 MIKA_STRICT_STARTUP=1 强制失败）| error={exc}")

    # 测试环境降级：提供最小占位符，避免 import 失败
    async def init_gemini():  # type: ignore[no-redef]
        return None

    async def close_gemini():  # type: ignore[no-redef]
        return None

    def set_plugin_config(_config: Config):  # type: ignore[no-redef]
        return None

    def get_gemini_client():  # type: ignore[no-redef]
        raise RuntimeError("gemini_chat: get_gemini_client unavailable in minimal test environment")

__all__ = ["plugin_config", "get_gemini_client"]
