"""数据库连接与初始化模块。

管理 SQLite 数据库的连接生命周期和表结构初始化：
- 全局单例连接（异步锁保护）
- 自动创建数据目录和表结构
- 支持环境变量覆盖数据库路径

环境变量：
- GEMINI_CONTEXT_DB_PATH: 直接指定数据库文件路径
- GEMINI_DATA_DIR: 指定数据根目录（数据库位于 <dir>/gemini_chat/contexts.db）
（可选）宿主路径端口：若未配置上述环境变量，则优先使用宿主注入的数据目录

相关模块：
- [`context_store`](context_store.py:1): 上下文存储，使用本模块的数据库连接
- [`user_profile`](user_profile.py:1): 用户档案，共用同一数据库
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Optional

import aiosqlite
from ..infra.logging import logger as log
from ..infra.paths import get_data_root


def _get_db_path() -> Path:
    """获取上下文数据库路径。

    支持通过环境变量覆盖（默认行为不变）：

    - GEMINI_CONTEXT_DB_PATH: 直接指定数据库文件路径（若为目录，则使用该目录下 contexts.db）
    - GEMINI_DATA_DIR: 指定运行时数据根目录（数据库将位于 <data_dir>/gemini_chat/contexts.db）
    """

    env_db_path = os.getenv("GEMINI_CONTEXT_DB_PATH")
    if env_db_path:
        p = Path(env_db_path)
        # 兼容把目录当作路径传入
        if p.exists() and p.is_dir():
            return p / "contexts.db"
        # 即使目录不存在，也按“文件路径”处理，后续会创建 parent
        return p

    env_data_dir = os.getenv("GEMINI_DATA_DIR")
    if env_data_dir:
        return Path(env_data_dir) / "gemini_chat" / "contexts.db"

    # 未配置环境变量时：优先使用宿主注入的路径端口；无宿主时回退到项目路径
    return get_data_root("gemini_chat") / "contexts.db"


# 数据库文件路径（可通过环境变量覆盖）
DB_PATH: Path = _get_db_path()

# 全局数据库连接
_db_connection: Optional[aiosqlite.Connection] = None

# 数据库连接锁（防止并发创建多个连接）
_db_lock: asyncio.Lock = asyncio.Lock()


async def get_db() -> aiosqlite.Connection:
    """获取或创建数据库连接（线程安全）"""
    global _db_connection
    log.debug("context_db.get_db: acquire lock")
    async with _db_lock:
        if _db_connection is None:
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            log.debug("context_db.get_db: create new connection")
            _db_connection = await aiosqlite.connect(str(DB_PATH))
            await _db_connection.execute("PRAGMA journal_mode=WAL")
            await _db_connection.execute("PRAGMA synchronous=NORMAL")
            await _db_connection.execute("PRAGMA busy_timeout=5000")
    return _db_connection


async def init_database() -> None:
    """初始化数据库表结构"""
    log.debug(f"初始化数据库: {DB_PATH}")
    db = await get_db()

    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS contexts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            context_key TEXT NOT NULL UNIQUE,
            messages TEXT NOT NULL DEFAULT '[]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    await db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_context_key ON contexts(context_key)
        """
    )

    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS message_archive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            context_key TEXT NOT NULL,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            message_id TEXT,
            timestamp REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    await db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_archive_key_time ON message_archive(context_key, timestamp)
        """
    )
    await db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_archive_key_msgid ON message_archive(context_key, message_id)
        """
    )

    await db.commit()
    log.success("数据库初始化完成")


async def close_database() -> None:
    """关闭数据库连接"""
    global _db_connection
    if _db_connection is not None:
        await _db_connection.close()
        _db_connection = None
        log.info("数据库连接已关闭")
