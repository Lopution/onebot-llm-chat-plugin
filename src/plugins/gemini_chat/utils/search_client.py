"""搜索相关的 HTTP 客户端封装。

该模块只负责创建 `httpx.AsyncClient`（默认超时、连接池、UA 等）。
全局客户端的复用与生命周期仍由 [`utils.search_engine`](bot/src/plugins/gemini_chat/utils/search_engine.py:1)
管理，以保持对外接口与测试 patch 行为兼容。
"""

from __future__ import annotations

import httpx


# ==================== Magic-number constants ====================
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_CONNECT_TIMEOUT_SECONDS = 5.0

DEFAULT_MAX_CONNECTIONS = 10
DEFAULT_MAX_KEEPALIVE_CONNECTIONS = 5

DEFAULT_USER_AGENT = "MikaBot/1.0 SearchEngine"


def create_default_http_client() -> httpx.AsyncClient:
    """创建默认配置的 `httpx.AsyncClient`。"""

    return httpx.AsyncClient(
        timeout=httpx.Timeout(DEFAULT_TIMEOUT_SECONDS, connect=DEFAULT_CONNECT_TIMEOUT_SECONDS),
        limits=httpx.Limits(
            max_connections=DEFAULT_MAX_CONNECTIONS,
            max_keepalive_connections=DEFAULT_MAX_KEEPALIVE_CONNECTIONS,
        ),
        headers={"User-Agent": DEFAULT_USER_AGENT},
    )
