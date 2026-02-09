"""Host-agnostic lifecycle compatibility module.

核心层不直接注册宿主生命周期；宿主适配器负责调用初始化与清理。
该模块保留旧符号，避免历史导入路径失效。
"""

from __future__ import annotations

from typing import Optional

from .config import Config
from .gemini_api import GeminiClient
from .runtime import (
    get_client as get_runtime_client,
    get_config as get_runtime_config,
    set_client as set_runtime_client,
    set_config as set_runtime_config,
)


def set_plugin_config(config: Config) -> None:
    set_runtime_config(config)


def get_plugin_config() -> Config:
    return get_runtime_config()


def set_gemini_client(client: Optional[GeminiClient]) -> None:
    set_runtime_client(client)


def get_gemini_client() -> GeminiClient:
    return get_runtime_client()


async def init_gemini() -> None:
    """宿主无关占位实现。"""
    return None


async def close_gemini() -> None:
    """宿主无关占位实现。"""
    return None


__all__ = [
    "set_plugin_config",
    "get_plugin_config",
    "set_gemini_client",
    "get_gemini_client",
    "init_gemini",
    "close_gemini",
]
