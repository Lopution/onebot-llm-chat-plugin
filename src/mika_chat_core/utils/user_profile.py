"""用户档案管理模块。

提供用户档案的持久化存储与查询功能：
- 持久化存储用户信息（姓名、身份、偏好等）
- 支持按 平台用户ID查询用户档案
- 自动从对话中提取并更新用户信息
- 生成用户档案摘要用于注入系统提示词

相关模块：
- [`user_profile_extract_service`](user_profile_extract_service.py:1): 异步抽取服务
- [`user_profile_llm_extractor`](user_profile_llm_extractor.py:1): LLM 抽取器
- [`user_profile_merge`](user_profile_merge.py:1): 档案合并逻辑
"""

import asyncio
import aiosqlite
import json
import re
import copy
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..infra.logging import logger as log

# 配置（用于限制缓存大小，避免长期运行内存增长）
from ..config import plugin_config
from .context_cache import LRUCache

# 数据库文件路径（与 context_store 共用同一数据库）
# 注意：必须与 context_db.DB_PATH 保持一致，支持通过环境变量覆盖部署路径。
from .context_db import get_db_path

SQLITE_CONNECT_TIMEOUT_SECONDS = 30.0
SQLITE_BUSY_TIMEOUT_MS = 5000


@asynccontextmanager
async def _open_db(*, row_factory: Optional[object] = None):
    """以与 context_db 一致的 SQLite 参数打开连接，降低锁冲突概率。"""
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(str(db_path), timeout=SQLITE_CONNECT_TIMEOUT_SECONDS)
    try:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=NORMAL")
        await db.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
        if row_factory is not None:
            db.row_factory = row_factory
        yield db
    finally:
        await db.close()


# 用于提取关键用户信息的正则模式
USER_INFO_PATTERNS = [
    # 姓名
    (r"我(?:的名字)?叫[「『\"']?([^\s「」『』\"'，。,\.]+)[」』\"']?", "name"),
    (r"(?:你)?可以叫我[「『\"']?([^\s「」『』\"'，。,\.]+)[」』\"']?", "name"),
    (r"我的?(?:名字|姓名)是[「『\"']?([^\s「」『』\"'，。,\.]+)[」』\"']?", "name"),
    # 身份
    (r"我是([^\s，。,\.]{2,10})", "identity"),
    # 职业
    (r"我是(?:一[个名位])?([^\s，。,\.]{2,15}?)(?:学生|工程师|程序员|老师|医生|设计师|作家|画师|公务员|商人)", "occupation"),
    (r"我(?:在|做)([^\s，。,\.]{2,15}?)(?:工作|上班)", "occupation"),
    # 偏好
    (r"我(?:最)?喜欢([^\s，。,\.]{2,20})", "preference"),
    (r"我(?:最)?爱([^\s，。,\.]{2,20})", "preference"),
    (r"我(?:特别)?讨厌([^\s，。,\.]{2,20})", "dislike"),
    # 年龄
    (r"我(\d{1,3})岁", "age"),
    (r"我今年(\d{1,3})", "age"),
    # 位置
    (r"我(?:住在|在|来自)([^\s，。,\.]{2,15})", "location"),
    # 生日
    (r"我(?:的)?生日(?:是)?(\d{1,2}月\d{1,2}[日号]?)", "birthday"),
]


class UserProfileStore:
    """用户档案存储器
    
    功能特性：
    - SQLite 持久化存储
    - 自动从消息中提取用户信息
    - 支持手动更新和查询
    - 生成用户档案摘要
    """
    
    def __init__(self):
        self._initialized = False
        # 内存缓存（LRU，避免长期运行无界增长）
        cache_size = max(
            1,
            int(getattr(plugin_config, "mika_user_profile_cache_max_size", 256) or 256),
        )
        self._cache: LRUCache = LRUCache(max_size=cache_size)
        # 写锁：避免并发写入导致 "database is locked" 或覆盖彼此的更新
        self._write_lock: asyncio.Lock = asyncio.Lock()
        self._profile_id_column = "platform_user_id"
        self._event_id_column = "platform_user_id"

    @staticmethod
    def _normalize_platform_user_id(
        platform_user_id: Optional[str] = None,
        *,
        legacy_qq_id: Optional[str] = None,
    ) -> str:
        resolved = str(platform_user_id or legacy_qq_id or "").strip()
        return resolved

    @staticmethod
    async def _read_table_columns(db: aiosqlite.Connection, table_name: str) -> set[str]:
        columns: set[str] = set()
        async with db.execute(f"PRAGMA table_info({table_name})") as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                try:
                    columns.add(str(row[1]))
                except Exception:
                    continue
        return columns

    async def _migrate_legacy_id_columns(self, db: aiosqlite.Connection) -> None:
        profile_columns = await self._read_table_columns(db, "user_profiles")
        if "platform_user_id" not in profile_columns and "qq_id" in profile_columns:
            try:
                await db.execute("ALTER TABLE user_profiles RENAME COLUMN qq_id TO platform_user_id")
                log.info("用户档案表字段迁移完成 | user_profiles.qq_id -> platform_user_id")
            except Exception as exc:
                log.warning(f"用户档案字段迁移失败，回退 legacy 列名 qq_id: {exc}")

        event_columns = await self._read_table_columns(db, "user_profile_events")
        if "platform_user_id" not in event_columns and "qq_id" in event_columns:
            try:
                await db.execute("ALTER TABLE user_profile_events RENAME COLUMN qq_id TO platform_user_id")
                log.info("用户档案审计表字段迁移完成 | user_profile_events.qq_id -> platform_user_id")
            except Exception as exc:
                log.warning(f"用户档案审计字段迁移失败，回退 legacy 列名 qq_id: {exc}")

        # 刷新列名探测（兼容迁移失败或旧 SQLite）
        profile_columns = await self._read_table_columns(db, "user_profiles")
        self._profile_id_column = (
            "platform_user_id" if "platform_user_id" in profile_columns else "qq_id"
        )
        event_columns = await self._read_table_columns(db, "user_profile_events")
        self._event_id_column = (
            "platform_user_id" if "platform_user_id" in event_columns else "qq_id"
        )
    
    async def init_table(self) -> None:
        """初始化用户档案表"""
        async with self._write_lock:
            if self._initialized:
                return

            try:
                async with _open_db() as db:
                    # 创建用户档案表
                    await db.execute("""
                        CREATE TABLE IF NOT EXISTS user_profiles (
                            platform_user_id TEXT PRIMARY KEY,
                            nickname TEXT,
                            real_name TEXT,
                            identity TEXT,
                            occupation TEXT,
                            age TEXT,
                            location TEXT,
                            birthday TEXT,
                            preferences TEXT DEFAULT '[]',
                            dislikes TEXT DEFAULT '[]',
                            extra_info TEXT DEFAULT '{}',
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)

                    # 审计表：记录每次 LLM 抽取与合并结果，便于回溯与调参
                    await db.execute("""
                        CREATE TABLE IF NOT EXISTS user_profile_events (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            platform_user_id TEXT NOT NULL,
                            group_id TEXT,
                            scene TEXT,
                            input_messages TEXT,
                            llm_output TEXT,
                            merge_result TEXT,
                            applied_fields TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)

                    await self._migrate_legacy_id_columns(db)

                    # 创建索引（按当前可用 id 列）
                    await db.execute(
                        f"CREATE INDEX IF NOT EXISTS idx_user_profile_events_id ON user_profile_events({self._event_id_column})"
                    )
                    await db.execute(
                        f"CREATE INDEX IF NOT EXISTS idx_user_profile_id ON user_profiles({self._profile_id_column})"
                    )
                    
                    await db.commit()
                self._initialized = True
                log.success("用户档案表初始化完成")
            except Exception as e:
                log.error(f"初始化用户档案表失败: {e}", exc_info=True)
    
    def extract_info_from_message(self, content: str) -> Dict[str, Any]:
        """从消息内容中提取用户信息
        
        Args:
            content: 消息内容
            
        Returns:
            提取到的信息字典
        """
        extracted: Dict[str, Any] = {}
        preferences: List[str] = []
        dislikes: List[str] = []
        
        for pattern, info_type in USER_INFO_PATTERNS:
            matches = re.findall(pattern, content)
            if matches:
                value = matches[0] if isinstance(matches[0], str) else matches[0][0]
                value = value.strip()
                
                if len(value) < 2 or len(value) > 30:
                    continue
                
                if info_type == "preference":
                    if value not in preferences:
                        preferences.append(value)
                elif info_type == "dislike":
                    if value not in dislikes:
                        dislikes.append(value)
                elif info_type == "name":
                    # 名字优先级：real_name
                    if "real_name" not in extracted:
                        extracted["real_name"] = value
                else:
                    if info_type not in extracted:
                        extracted[info_type] = value
        
        if preferences:
            extracted["preferences"] = preferences
        if dislikes:
            extracted["dislikes"] = dislikes
        
        return extracted
    
    async def update_from_message(
        self,
        platform_user_id: str = "",
        content: str = "",
        nickname: Optional[str] = None,
        qq_id: Optional[str] = None,
    ) -> bool:
        """从消息中提取信息并更新用户档案
        
        Args:
            platform_user_id: 平台用户ID
            content: 消息内容
            nickname: 用户昵称（可选）
            
        Returns:
            是否有更新
        """
        resolved_user_id = self._normalize_platform_user_id(platform_user_id, legacy_qq_id=qq_id)
        if not resolved_user_id:
            return False

        await self.init_table()
        
        # 提取信息
        info = self.extract_info_from_message(content)
        
        if not info and not nickname:
            return False
        
        if nickname:
            info["nickname"] = nickname
        
        # 更新档案
        return await self.update_profile(resolved_user_id, info)
    
    async def update_profile(
        self,
        platform_user_id: str = "",
        info: Dict[str, Any] = None,
        qq_id: Optional[str] = None,
    ) -> bool:
        """更新用户档案
        
        Args:
            platform_user_id: 平台用户ID
            info: 要更新的信息
            
        Returns:
            是否成功
        """
        resolved_user_id = self._normalize_platform_user_id(platform_user_id, legacy_qq_id=qq_id)
        if not resolved_user_id:
            return False

        await self.init_table()

        if not info:
            return False
        
        try:
            # 获取现有档案
            existing = await self.get_profile(resolved_user_id)
            
            # 合并偏好列表
            if "preferences" in info:
                existing_prefs = existing.get("preferences", [])
                if isinstance(existing_prefs, str):
                    existing_prefs = json.loads(existing_prefs) if existing_prefs else []
                new_prefs_input = info["preferences"]
                if isinstance(new_prefs_input, str):
                    try:
                        new_prefs_input = json.loads(new_prefs_input) if new_prefs_input else []
                    except json.JSONDecodeError:
                        new_prefs_input = []
                if not isinstance(new_prefs_input, list):
                    new_prefs_input = []
                new_prefs = list(set(existing_prefs + new_prefs_input))
                info["preferences"] = json.dumps(new_prefs, ensure_ascii=False)
            
            if "dislikes" in info:
                existing_dislikes = existing.get("dislikes", [])
                if isinstance(existing_dislikes, str):
                    existing_dislikes = json.loads(existing_dislikes) if existing_dislikes else []
                new_dislikes_input = info["dislikes"]
                if isinstance(new_dislikes_input, str):
                    try:
                        new_dislikes_input = json.loads(new_dislikes_input) if new_dislikes_input else []
                    except json.JSONDecodeError:
                        new_dislikes_input = []
                if not isinstance(new_dislikes_input, list):
                    new_dislikes_input = []
                new_dislikes = list(set(existing_dislikes + new_dislikes_input))
                info["dislikes"] = json.dumps(new_dislikes, ensure_ascii=False)

            # 合并 extra_info（深合并以保留溯源与 pending_overrides）
            if "extra_info" in info:
                existing_extra = existing.get("extra_info", {})
                if isinstance(existing_extra, str):
                    try:
                        existing_extra = json.loads(existing_extra) if existing_extra else {}
                    except json.JSONDecodeError:
                        existing_extra = {}
                if not isinstance(existing_extra, dict):
                    existing_extra = {}

                new_extra = info.get("extra_info")
                if isinstance(new_extra, str):
                    try:
                        new_extra = json.loads(new_extra) if new_extra else {}
                    except json.JSONDecodeError:
                        new_extra = {}
                if not isinstance(new_extra, dict):
                    new_extra = {}

                # shallow merge（对 provenance 结构已足够；如需更深可再扩展）
                merged_extra = dict(existing_extra)
                for k, v in new_extra.items():
                    if isinstance(v, dict) and isinstance(merged_extra.get(k), dict):
                        merged_extra[k] = {**merged_extra[k], **v}
                    else:
                        merged_extra[k] = v

                info["extra_info"] = json.dumps(merged_extra, ensure_ascii=False)
            
            # 构建更新 SQL
            fields = ["nickname", "real_name", "identity", "occupation", 
                     "age", "location", "birthday", "preferences", "dislikes", "extra_info"]
            
            update_parts = []
            values = []
            for field in fields:
                if field in info:
                    update_parts.append(f"{field} = ?")
                    values.append(info[field])
            
            if not update_parts:
                return False
            
            update_parts.append("updated_at = CURRENT_TIMESTAMP")
            
            async with self._write_lock:
                async with _open_db() as db:
                    # 尝试更新
                    if existing:
                        sql = (
                            f"UPDATE user_profiles SET {', '.join(update_parts)} "
                            f"WHERE {self._profile_id_column} = ?"
                        )
                        values.append(resolved_user_id)
                        await db.execute(sql, values)
                    else:
                        # 插入新记录
                        insert_fields = [self._profile_id_column] + [f for f in fields if f in info]
                        insert_values = [resolved_user_id] + [info[f] for f in fields if f in info]
                        placeholders = ", ".join(["?"] * len(insert_values))
                        sql = f"INSERT INTO user_profiles ({', '.join(insert_fields)}) VALUES ({placeholders})"
                        await db.execute(sql, insert_values)
                    
                    await db.commit()
            
            # 写后简单失效：避免 cache 中出现 JSON 字符串/解析类型混用
            self._cache.delete(resolved_user_id)

            log.info(f"用户档案已更新 | platform_user_id={resolved_user_id} | fields={list(info.keys())}")
            return True
            
        except Exception as e:
            log.error(f"更新用户档案失败: {e}", exc_info=True)
            return False
    
    async def get_profile(self, platform_user_id: str = "", qq_id: Optional[str] = None) -> Dict[str, Any]:
        """获取用户档案
        
        Args:
            platform_user_id: 平台用户ID
            
        Returns:
            用户档案字典，不存在则返回空字典
        """
        resolved_user_id = self._normalize_platform_user_id(platform_user_id, legacy_qq_id=qq_id)
        if not resolved_user_id:
            return {}

        await self.init_table()
        
        # 检查缓存
        cached = self._cache.get(resolved_user_id)
        if cached is not None:
            # 返回深拷贝，避免调用方修改嵌套对象（list/dict）污染缓存
            return copy.deepcopy(cached)
        
        try:
            async with _open_db(row_factory=aiosqlite.Row) as db:
                async with db.execute(
                    f"SELECT * FROM user_profiles WHERE {self._profile_id_column} = ?",
                    (resolved_user_id,)
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        profile = dict(row)
                        # 解析 JSON 字段
                        for field in ["preferences", "dislikes", "extra_info"]:
                            if profile.get(field):
                                try:
                                    profile[field] = json.loads(profile[field])
                                except json.JSONDecodeError:
                                    profile[field] = {} if field == "extra_info" else []
                        
                        # 缓存
                        self._cache.set(resolved_user_id, profile)
                        return copy.deepcopy(profile)
        except Exception as e:
            log.error(f"获取用户档案失败: {e}", exc_info=True)
        
        return {}

    async def list_profiles(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        query: str = "",
    ) -> Dict[str, Any]:
        await self.init_table()

        safe_page = max(1, int(page or 1))
        safe_size = max(1, min(int(page_size or 20), 100))
        offset = (safe_page - 1) * safe_size
        keyword = str(query or "").strip()

        where_sql = ""
        where_args: list[Any] = []
        if keyword:
            like_value = f"%{keyword}%"
            where_sql = (
                "WHERE "
                f"{self._profile_id_column} LIKE ? "
                "OR nickname LIKE ? "
                "OR real_name LIKE ? "
                "OR identity LIKE ? "
                "OR occupation LIKE ? "
                "OR location LIKE ?"
            )
            where_args = [like_value] * 6

        try:
            async with _open_db(row_factory=aiosqlite.Row) as db:
                count_sql = f"SELECT COUNT(*) AS total FROM user_profiles {where_sql}"
                async with db.execute(count_sql, where_args) as cursor:
                    count_row = await cursor.fetchone()
                total = int(count_row["total"] if count_row else 0)

                list_sql = f"""
                    SELECT {self._profile_id_column} AS platform_user_id,
                           nickname, real_name, identity, occupation, age, location, birthday,
                           preferences, dislikes, extra_info, created_at, updated_at
                    FROM user_profiles
                    {where_sql}
                    ORDER BY updated_at DESC
                    LIMIT ? OFFSET ?
                """
                async with db.execute(list_sql, [*where_args, safe_size, offset]) as cursor:
                    rows = await cursor.fetchall()

            items: list[Dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                for field in ["preferences", "dislikes", "extra_info"]:
                    raw_value = item.get(field)
                    if isinstance(raw_value, str) and raw_value:
                        try:
                            item[field] = json.loads(raw_value)
                        except json.JSONDecodeError:
                            item[field] = {} if field == "extra_info" else []
                    elif raw_value in (None, ""):
                        item[field] = {} if field == "extra_info" else []
                items.append(item)

            return {
                "items": items,
                "total": total,
                "page": safe_page,
                "page_size": safe_size,
                "query": keyword,
            }
        except Exception as e:
            log.error(f"列出用户档案失败: {e}", exc_info=True)
            return {
                "items": [],
                "total": 0,
                "page": safe_page,
                "page_size": safe_size,
                "query": keyword,
            }
    
    async def get_profile_summary(self, platform_user_id: str = "", qq_id: Optional[str] = None) -> str:
        """获取用户档案摘要
        
        Args:
            platform_user_id: 平台用户ID
            
        Returns:
            格式化的摘要字符串，用于注入系统提示词
        """
        resolved_user_id = self._normalize_platform_user_id(platform_user_id, legacy_qq_id=qq_id)
        if not resolved_user_id:
            return ""

        profile = await self.get_profile(resolved_user_id)
        
        if not profile:
            return ""
        
        parts = []
        
        # 基本信息
        if profile.get("real_name"):
            parts.append(f"名字是{profile['real_name']}")
        if profile.get("identity"):
            parts.append(f"是{profile['identity']}")
        if profile.get("occupation"):
            parts.append(f"职业是{profile['occupation']}")
        if profile.get("age"):
            parts.append(f"{profile['age']}岁")
        if profile.get("location"):
            parts.append(f"来自{profile['location']}")
        if profile.get("birthday"):
            parts.append(f"生日是{profile['birthday']}")
        
        # 偏好
        prefs = profile.get("preferences", [])
        if prefs:
            if len(prefs) <= 3:
                parts.append(f"喜欢{', '.join(prefs)}")
            else:
                parts.append(f"喜欢{', '.join(prefs[:3])}等")
        
        # 不喜欢
        dislikes = profile.get("dislikes", [])
        if dislikes:
            parts.append(f"不喜欢{', '.join(dislikes[:2])}")
        
        if not parts:
            return ""
        
        return f"用户({resolved_user_id}): {', '.join(parts)}"
    
    async def get_all_profiles_summary(self, platform_user_ids: List[str]) -> str:
        """获取多个用户的档案摘要
        
        Args:
            platform_user_ids: 平台用户ID列表
            
        Returns:
            合并的摘要字符串
        """
        summaries = []
        for platform_user_id in platform_user_ids:
            summary = await self.get_profile_summary(platform_user_id)
            if summary:
                summaries.append(summary)
        
        return "\n".join(summaries)
    
    async def clear_profile(self, platform_user_id: str = "", qq_id: Optional[str] = None) -> bool:
        """清除用户档案
        
        Args:
            platform_user_id: 平台用户ID
            
        Returns:
            是否成功
        """
        resolved_user_id = self._normalize_platform_user_id(platform_user_id, legacy_qq_id=qq_id)
        if not resolved_user_id:
            return False

        await self.init_table()
        
        try:
            async with self._write_lock:
                async with _open_db() as db:
                    await db.execute(
                        f"DELETE FROM user_profiles WHERE {self._profile_id_column} = ?",
                        (resolved_user_id,)
                    )
                    await db.commit()
            
            # 清除缓存
            self._cache.delete(resolved_user_id)

            log.info(f"用户档案已清除 | platform_user_id={resolved_user_id}")
            return True
        except Exception as e:
            log.error(f"清除用户档案失败: {e}", exc_info=True)
            return False

    async def add_audit_event(
        self,
        *,
        platform_user_id: str = "",
        group_id: Optional[str] = None,
        scene: str = "",
        input_messages: Optional[List[Dict[str, Any]]] = None,
        llm_output: Optional[Dict[str, Any]] = None,
        merge_result: Optional[Dict[str, Any]] = None,
        applied_fields: Optional[Dict[str, Any]] = None,
        qq_id: Optional[str] = None,
    ) -> None:
        """写入 user_profile_events 审计表（失败不抛出，避免影响主流程）。"""
        resolved_user_id = self._normalize_platform_user_id(platform_user_id, legacy_qq_id=qq_id)
        if not resolved_user_id:
            return

        await self.init_table()
        try:
            async with self._write_lock:
                async with _open_db() as db:
                    await db.execute(
                        """
                        INSERT INTO user_profile_events (
                            {id_col}, group_id, scene, input_messages, llm_output, merge_result, applied_fields
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """.format(id_col=self._event_id_column),
                        (
                            resolved_user_id,
                            group_id,
                            scene,
                            json.dumps(input_messages or [], ensure_ascii=False),
                            json.dumps(llm_output or {}, ensure_ascii=False),
                            json.dumps(merge_result or {}, ensure_ascii=False),
                            json.dumps(applied_fields or {}, ensure_ascii=False),
                        ),
                    )
                    await db.commit()
        except Exception as e:
            log.warning(f"写入 user_profile_events 失败: {e}")


# 全局实例
_user_profile_store: Optional[UserProfileStore] = None


def get_user_profile_store() -> UserProfileStore:
    """获取全局用户档案存储实例"""
    global _user_profile_store
    if _user_profile_store is None:
        _user_profile_store = UserProfileStore()
    return _user_profile_store


async def init_user_profile_store() -> None:
    """初始化用户档案存储"""
    store = get_user_profile_store()
    await store.init_table()
    log.success("用户档案存储初始化完成")
