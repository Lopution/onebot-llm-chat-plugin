"""数据库连接与初始化模块。

管理 SQLite 数据库的连接生命周期和表结构初始化：
- 全局单例连接（异步锁保护）
- 自动创建数据目录和表结构
- 支持环境变量覆盖数据库路径

环境变量：
- MIKA_CONTEXT_DB_PATH: 直接指定数据库文件路径
- MIKA_DATA_DIR: 指定数据根目录（数据库位于 <dir>/mika_chat/contexts.db）
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

    - MIKA_CONTEXT_DB_PATH: 直接指定数据库文件路径（若为目录，则使用该目录下 contexts.db）
    - MIKA_DATA_DIR: 指定运行时数据根目录（数据库将位于 <data_dir>/mika_chat/contexts.db）
    """

    env_db_path = str(os.getenv("MIKA_CONTEXT_DB_PATH", "") or "").strip()
    if env_db_path:
        p = Path(env_db_path)
        # 兼容把目录当作路径传入
        if p.exists() and p.is_dir():
            return p / "contexts.db"
        # 即使目录不存在，也按“文件路径”处理，后续会创建 parent
        return p

    env_data_dir = str(os.getenv("MIKA_DATA_DIR", "") or "").strip()
    if env_data_dir:
        return Path(env_data_dir) / "mika_chat" / "contexts.db"

    # 未配置环境变量时：优先使用宿主注入的路径端口；无宿主时回退到项目路径
    return get_data_root("mika_chat") / "contexts.db"


# 数据库文件路径覆盖（可通过测试 patch 或 set_db_path 注入）
# 默认 None，运行时按环境变量/路径端口动态解析。
DB_PATH: Optional[Path] = None

# 全局数据库连接
_db_connection: Optional[aiosqlite.Connection] = None
_db_connection_path: Optional[Path] = None

# 数据库连接锁（防止并发创建多个连接）
_db_lock: asyncio.Lock = asyncio.Lock()


def set_db_path(path: Optional[Path]) -> None:
    """设置数据库路径覆盖（None 表示使用动态解析路径）。"""
    global DB_PATH
    DB_PATH = path


def get_db_path() -> Path:
    """获取当前数据库路径（支持动态解析与覆盖）。"""
    if DB_PATH is not None:
        return Path(DB_PATH)
    return _get_db_path()


async def get_db() -> aiosqlite.Connection:
    """获取或创建数据库连接（线程安全）"""
    global _db_connection, _db_connection_path
    log.debug("context_db.get_db: acquire lock")
    async with _db_lock:
        path = get_db_path()
        if _db_connection is not None and _db_connection_path != path:
            await _db_connection.close()
            _db_connection = None
            _db_connection_path = None

        if _db_connection is None:
            path.parent.mkdir(parents=True, exist_ok=True)
            log.debug("context_db.get_db: create new connection")
            _db_connection = await aiosqlite.connect(str(path))
            await _db_connection.execute("PRAGMA journal_mode=WAL")
            await _db_connection.execute("PRAGMA synchronous=NORMAL")
            await _db_connection.execute("PRAGMA busy_timeout=5000")
            _db_connection_path = path
    return _db_connection


async def init_database() -> None:
    """初始化数据库表结构"""
    log.debug(f"初始化数据库: {get_db_path()}")
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

    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS context_summaries (
            context_key TEXT PRIMARY KEY,
            summary TEXT NOT NULL DEFAULT '',
            source_message_count INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS topic_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_key TEXT NOT NULL,
            topic TEXT NOT NULL,
            keywords TEXT NOT NULL DEFAULT '[]',
            summary TEXT NOT NULL DEFAULT '',
            key_points TEXT NOT NULL DEFAULT '[]',
            participants TEXT NOT NULL DEFAULT '[]',
            timestamp_start REAL NOT NULL DEFAULT 0,
            timestamp_end REAL NOT NULL DEFAULT 0,
            source_message_count INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            UNIQUE(session_key, topic)
        )
        """
    )
    await db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_topic_summaries_session
        ON topic_summaries(session_key)
        """
    )
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS topic_summary_state (
            session_key TEXT PRIMARY KEY,
            processed_message_count INTEGER NOT NULL DEFAULT 0,
            updated_at REAL NOT NULL
        )
        """
    )

    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_embeddings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_key TEXT NOT NULL,
            user_id TEXT NOT NULL DEFAULT '',
            fact TEXT NOT NULL,
            embedding BLOB NOT NULL,
            created_at REAL NOT NULL,
            last_recalled_at REAL NOT NULL,
            recall_count INTEGER NOT NULL DEFAULT 0,
            source TEXT NOT NULL DEFAULT 'extract',
            UNIQUE(session_key, fact)
        )
        """
    )
    await db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_memory_session ON memory_embeddings(session_key)
        """
    )
    await db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_memory_user ON memory_embeddings(user_id)
        """
    )

    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_embeddings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            corpus_id TEXT NOT NULL,
            doc_id TEXT NOT NULL,
            chunk_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            embedding BLOB NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT '',
            tags TEXT NOT NULL DEFAULT '',
            session_key TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            last_recalled_at REAL NOT NULL DEFAULT 0,
            recall_count INTEGER NOT NULL DEFAULT 0,
            UNIQUE(corpus_id, doc_id, chunk_id)
        )
        """
    )
    await db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_knowledge_corpus ON knowledge_embeddings(corpus_id)
        """
    )
    await db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_knowledge_session ON knowledge_embeddings(session_key)
        """
    )
    await db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_knowledge_doc ON knowledge_embeddings(corpus_id, doc_id)
        """
    )

    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS personas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            character_prompt TEXT NOT NULL,
            dialogue_examples TEXT NOT NULL DEFAULT '[]',
            error_messages TEXT NOT NULL DEFAULT '{}',
            is_active INTEGER NOT NULL DEFAULT 0,
            temperature_override REAL,
            model_override TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    await db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_personas_active ON personas(is_active)
        """
    )

    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS tool_states (
            tool_name TEXT PRIMARY KEY,
            enabled INTEGER NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    await db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_tool_states_updated_at
        ON tool_states(updated_at)
        """
    )

    # -------------------- Observability (agent traces) --------------------
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_traces (
            request_id TEXT PRIMARY KEY,
            session_key TEXT NOT NULL,
            user_id TEXT NOT NULL DEFAULT '',
            group_id TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            plan_json TEXT NOT NULL DEFAULT '',
            events_json TEXT NOT NULL DEFAULT '[]'
        )
        """
    )
    await db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_agent_traces_session_created
        ON agent_traces(session_key, created_at)
        """
    )
    await db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_agent_traces_created
        ON agent_traces(created_at)
        """
    )

    await db.commit()
    log.success("数据库初始化完成")


async def close_database() -> None:
    """关闭数据库连接"""
    global _db_connection, _db_connection_path
    if _db_connection is not None:
        await _db_connection.close()
        _db_connection = None
        _db_connection_path = None
        log.info("数据库连接已关闭")
