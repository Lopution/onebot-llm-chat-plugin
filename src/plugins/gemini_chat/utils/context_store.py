"""上下文持久化存储（SQLite）。

提供基于 SQLite 的聊天上下文存储与管理功能：
- SQLite 持久化存储
- LRU 内存缓存（限制最大条目防止内存溢出）
- 智能上下文压缩（保留关键信息，降低 Token 消耗）
- 用户身份信息提取（姓名、职业、偏好等）

相关模块：
- [`context_cache`](context_cache.py:1): LRU 缓存实现
- [`context_compress`](context_compress.py:1): 上下文压缩算法
- [`context_db`](context_db.py:1): 数据库连接管理
"""
import asyncio
import json
import re
from typing import List, Dict, Any, Optional, Tuple, TypedDict, Union

from nonebot import logger as log

from .context_cache import LRUCache
from .context_compress import compress_context_for_safety as _compress_context_for_safety
from .context_compress import compress_message_content as _compress_message_content
from .context_compress import sanitize_text_for_safety as _sanitize_text_for_safety
from .context_db import DB_PATH, get_db, init_database, close_database

# 内存缓存最大条目数（越小越省内存）
MAX_CACHE_SIZE: int = 200

# ==================== Magic-number constants ====================
NICKNAME_MAX_LENGTH = 12

# KEY_INFO_PATTERNS 的长度限制
KEY_INFO_IDENTITY_MIN_CHARS = 2
KEY_INFO_IDENTITY_MAX_CHARS = 10
KEY_INFO_OCCUPATION_MIN_CHARS = 2
KEY_INFO_OCCUPATION_MAX_CHARS = 15
KEY_INFO_PREFERENCE_MIN_CHARS = 2
KEY_INFO_PREFERENCE_MAX_CHARS = 20
KEY_INFO_EXTRACTED_VALUE_MIN_CHARS = 2
KEY_INFO_EXTRACTED_VALUE_MAX_CHARS = 20

# 上下文压缩：保留最近 max_context * 2 条（与原逻辑一致）
CONTEXT_MESSAGE_MULTIPLIER = 2


class MessageDict(TypedDict, total=False):
    """消息字典类型定义"""
    role: str
    content: Union[str, List[Dict[str, Any]]]  # 字符串或多模态列表
    message_id: str
    timestamp: float  # 消息时间戳


class SQLiteContextStore:
    """SQLite 上下文存储器
    
    功能特性：
    - SQLite 持久化存储
    - LRU 内存缓存
    - 智能上下文压缩（保留关键信息）
    - 用户身份信息提取
    """
    
    # 用于提取关键用户信息的正则模式
    KEY_INFO_PATTERNS = [
        # 自我介绍模式
        (r"我(?:的名字)?叫[「『\"']?([^\s「」『』\"'，。,\.]+)[」』\"']?", "name"),
        (rf"我是([^\s，。,\.]{{{KEY_INFO_IDENTITY_MIN_CHARS},{KEY_INFO_IDENTITY_MAX_CHARS}}})", "identity"),
        (r"(?:你)?可以叫我[「『\"']?([^\s「」『』\"'，。,\.]+)[」』\"']?", "name"),
        (r"我的?(?:名字|姓名)是[「『\"']?([^\s「」『』\"'，。,\.]+)[」』\"']?", "name"),
        # 职业/身份
        (
            rf"我是(?:一[个名位])?([^\s，。,\.]{{{KEY_INFO_OCCUPATION_MIN_CHARS},{KEY_INFO_OCCUPATION_MAX_CHARS}}}?)(?:学生|工程师|程序员|老师|医生|设计师|作家|画师)",
            "occupation",
        ),
        # 偏好
        (rf"我(?:最)?喜欢([^\s，。,\.]{{{KEY_INFO_PREFERENCE_MIN_CHARS},{KEY_INFO_PREFERENCE_MAX_CHARS}}})", "preference"),
        (rf"我(?:最)?爱([^\s，。,\.]{{{KEY_INFO_PREFERENCE_MIN_CHARS},{KEY_INFO_PREFERENCE_MAX_CHARS}}})", "preference"),
        # 年龄
        (r"我(\d{1,3})岁", "age"),
        (r"我今年(\d{1,3})", "age"),
    ]
    
    def __init__(self, max_context: int = 40, max_cache_size: int = MAX_CACHE_SIZE):
        self.max_context = max_context
        # 使用 LRU 缓存替代普通字典，限制缓存大小防止内存溢出
        self._cache: LRUCache = LRUCache(max_size=max_cache_size)
        self._max_cache_size = max_cache_size
        # 关键信息缓存（用户 QQ 号 -> 提取的信息）
        self._key_info_cache: Dict[str, Dict[str, str]] = {}
        # 写锁（防止并发 Read-Modify-Write 导致数据丢失）
        self._write_lock: asyncio.Lock = asyncio.Lock()
    
    def _make_key(self, user_id: str, group_id: Optional[str] = None) -> str:
        """生成上下文键
        
        - 群聊：group:{group_id} （群内共享，所有成员看到相同上下文）
        - 私聊：private:{user_id}
        
        注意：群聊共享上下文依赖消息中的用户标签 [nickname(user_id)] 来区分不同用户
        """
        if group_id:
            # 群聊：所有成员共享上下文，模型通过用户标签区分
            return f"group:{group_id}"
        # 私聊：按 user_id 隔离
        return f"private:{user_id}"
    
    def _sanitize_nickname(self, nickname: str) -> str:
        """清洗昵称，使其更像正常的同学名字
        
        策略：
        1. 去除 Emoji 和特殊符号（只保留中英文、数字、下划线、连字符、空格）
        2. 去除首尾空白
        3. 如果清洗后为空，使用默认称呼 "同学"
        4. 限制长度
        """
        if not nickname:
            return "同学"
            
        # 移除干扰性前缀（如 “群主”、“管理员”），支持 - 和 _ 作为分隔符
        nickname = re.sub(r'^(?:群主|管理员|admin)[-_]?', '', nickname, flags=re.IGNORECASE)
        
        # 只保留中文、英文、数字、常见连接符
        # 严格使用字符范围，排除部分 Unicode 符号 (如希腊字母)
        cleaned = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9\-_ ]', '', nickname)
        
        cleaned = cleaned.strip()
        
        if not cleaned:
            # 如果全是符号，尝试保留前几个原始字符（作为标识），或者直接叫“神秘同学”
            return "神秘同学"
            
        # 限制长度（太长不像名字）
        if len(cleaned) > NICKNAME_MAX_LENGTH:
            cleaned = cleaned[:NICKNAME_MAX_LENGTH]
            
        return cleaned

    def _extract_user_identity_from_message(self, content: str) -> Tuple[Optional[str], Optional[str]]:
        """从消息内容中提取用户身份 (QQ号, 昵称)
        
        消息格式：[昵称(QQ号)]: 内容
        Returns:
            (user_id, nickname) 元组
        """
        match = re.match(r'\[(.*?)\((\d+)\)\]:', content)
        if match:
            raw_nickname = match.group(1)
            user_id = match.group(2)
            # 清洗昵称
            nickname = self._sanitize_nickname(raw_nickname)
            return user_id, nickname
        
        # Sensei 特殊标记
        if content.startswith("[⭐Sensei]") or content.startswith("[★Sensei]"):
            return "MASTER", "Sensei"
            
        return None, None
    
    def _extract_key_info_from_message(self, content: str) -> Dict[str, str]:
        """从单条消息中提取关键信息
        
        Returns:
            提取到的信息字典，如 {"name": "张三", "occupation": "程序员"}
        """
        extracted = {}
        
        # 获取消息正文（去除用户标签）
        text = re.sub(r'^\[.*?\]:\s*', '', content)
        
        for pattern, info_type in self.KEY_INFO_PATTERNS:
            matches = re.findall(pattern, text)
            if matches:
                # 取第一个匹配
                value = matches[0] if isinstance(matches[0], str) else matches[0][0]
                # 清理值
                value = value.strip()
                if KEY_INFO_EXTRACTED_VALUE_MIN_CHARS <= len(value) <= KEY_INFO_EXTRACTED_VALUE_MAX_CHARS:
                    if info_type not in extracted:  # 不覆盖已提取的同类信息
                        extracted[info_type] = value
        
        return extracted
    
    def _extract_key_info_from_history(
        self,
        messages: List[MessageDict]
    ) -> Dict[str, Dict[str, str]]:
        """从历史消息中提取所有用户的关键信息
        
        Returns:
            用户 QQ 号 -> 信息字典 的映射
        """
        user_info: Dict[str, Dict[str, str]] = {}
        
        for msg in messages:
            if msg.get("role") != "user":
                continue
                
            content = msg.get("content", "")
            if isinstance(content, list):
                # 多模态消息，取第一个文本
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        content = item.get("text", "")
                        break
                else:
                    continue
            
            if not isinstance(content, str):
                continue
            
            # 提取用户 ID 和 昵称
            user_id, nickname = self._extract_user_identity_from_message(content)
            if not user_id:
                continue
            
            # 初始化用户信息字典
            if user_id not in user_info:
                user_info[user_id] = {}
            
            # 更新最新昵称
            if nickname:
                user_info[user_id]["__nickname__"] = nickname
            
            # 提取关键信息
            info = self._extract_key_info_from_message(content)
            if info:
                user_info[user_id].update(info)
        
        return user_info
    
    def _build_key_info_summary(self, user_info: Dict[str, Dict[str, str]]) -> str:
        """构建关键信息摘要
        
        Args:
            user_info: 用户信息字典
            
        Returns:
            格式化的摘要字符串
        """
        if not user_info:
            return ""
        
        summary_parts = []
        for user_id, info in user_info.items():
            # 过滤掉内部字段，检查是否有实际内容
            public_info = {k: v for k, v in info.items() if not k.startswith("__")}
            if not public_info:
                continue
            
            user_desc = []
            if "name" in info:
                user_desc.append(f"自称{info['name']}")
            if "identity" in info:
                user_desc.append(f"是{info['identity']}")
            if "occupation" in info:
                user_desc.append(f"职业是{info['occupation']}")
            if "age" in info:
                user_desc.append(f"{info['age']}岁")
            if "preference" in info:
                user_desc.append(f"喜欢{info['preference']}")
            
            nickname = info.get("__nickname__", "未知")
            
            if user_desc:
                if user_id == "MASTER":
                    summary_parts.append(f"Sensei: {', '.join(user_desc)}")
                else:
                    # 使用 [昵称(ID)] 格式，与对话格式保持一致，减少模型认知负担
                    summary_parts.append(f"用户 [{nickname}({user_id})]: {', '.join(user_desc)}")
        
        return "; ".join(summary_parts)
    
    async def _compress_context(
        self,
        messages: List[MessageDict],
        context_key: str
    ) -> List[MessageDict]:
        """上下文截断
        
        策略：仅保留最近 N 条完整消息（FIFO）
        注意：用户决定禁用智能摘要功能，因此不再注入摘要。
        """
        max_messages = self.max_context * CONTEXT_MESSAGE_MULTIPLIER  # 默认 80 条
        
        if len(messages) <= max_messages:
            return messages
        
        # 简单截断，保留最近的消息
        compressed = messages[-max_messages:]
            
        log.debug(
            f"上下文截断 | key={context_key} | "
            f"原消息数={len(messages)} | 截断后={len(compressed)}"
        )
        
        return compressed
    
    def _sanitize_text_for_safety(self, text: str) -> str:
        """对文本进行安全净化（委派到独立模块）。"""
        return _sanitize_text_for_safety(text)
    
    def _compress_message_content(self, content: Union[str, List[Dict[str, Any]]]) -> Union[str, List[Dict[str, Any]]]:
        """压缩单条消息内容（委派到独立模块）。"""
        return _compress_message_content(content)
    
    async def compress_context_for_safety(
        self,
        messages: List[MessageDict],
        level: int = 1
    ) -> List[MessageDict]:
        """为绕过安全过滤而压缩上下文（委派到独立模块）。"""
        return await _compress_context_for_safety(messages, level=level)
    
    async def get_context(self, user_id: str, group_id: Optional[str] = None) -> List[MessageDict]:
        """获取上下文历史"""
        key = self._make_key(user_id, group_id)
        
        # 优先从缓存读取
        cached = self._cache.get(key)
        if cached is not None:
            log.debug(f"缓存命中: {key}")
            return cached
        
        # 从数据库读取
        try:
            db = await get_db()
            async with db.execute(
                "SELECT messages FROM contexts WHERE context_key = ?",
                (key,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    messages = json.loads(row[0])
                    self._cache.set(key, messages)
                    log.debug(f"从数据库加载上下文: {key} | 消息数={len(messages)}")
                    return messages
        except Exception as e:
            log.error(f"获取上下文失败: {e}", exc_info=True)
        
        return []
    
    async def add_message(
        self,
        user_id: str,
        role: str,
        content: Any,
        group_id: Optional[str] = None,
        message_id: Optional[str] = None,
        timestamp: Optional[float] = None
    ) -> None:
        """添加消息到上下文
        
        改进：使用智能压缩替代简单截断，保留关键用户信息
        """
        async with self._write_lock:
            key = self._make_key(user_id, group_id)
            
            # 获取当前上下文
            messages = await self.get_context(user_id, group_id)
            
            # 构建消息对象
            new_msg = {"role": role, "content": content}
            if message_id:
                new_msg["message_id"] = str(message_id)
            # 添加时间戳
            if timestamp is None:
                import time
                timestamp = time.time()
            new_msg["timestamp"] = timestamp
                
            messages.append(new_msg)
            
            # 智能压缩上下文（保留关键信息，替代简单截断）
            if len(messages) > self.max_context * 2:
                messages = await self._compress_context(messages, key)
            
            # 更新缓存（使用 LRU 策略）
            self._cache.set(key, messages)
            
            # 异步写入数据库（使用显式事务确保原子性）
            db = None
            try:
                db = await get_db()
                
                # 开始显式事务
                await db.execute("BEGIN IMMEDIATE")
                
                try:
                    # 1. 更新上下文快照 (最近 N 条)
                    await db.execute("""
                        INSERT INTO contexts (context_key, messages, updated_at)
                        VALUES (?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(context_key) DO UPDATE SET
                            messages = excluded.messages,
                            updated_at = CURRENT_TIMESTAMP
                    """, (key, json.dumps(messages, ensure_ascii=False)))
                    
                    # 2. 插入归档记录 (全量历史)
                    # 处理 content，如果是列表(多模态)则转JSON字符串，如果是字符串则直接存
                    if isinstance(content, (list, dict)):
                        archive_content = json.dumps(content, ensure_ascii=False)
                    else:
                        archive_content = str(content)
                    
                    await db.execute("""
                        INSERT INTO message_archive (context_key, user_id, role, content, message_id, timestamp)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (key, user_id, role, archive_content, message_id, timestamp))
                    
                    await db.commit()
                    log.debug(f"上下文已保存: {key} | 消息数={len(messages)}")
                except Exception as e:
                    # 事务内部发生错误，回滚
                    await db.rollback()
                    raise
            except Exception as e:
                log.error(f"保存上下文失败: {e}", exc_info=True)
    
    async def clear_context(self, user_id: str, group_id: Optional[str] = None) -> None:
        """清空上下文"""
        key = self._make_key(user_id, group_id)
        
        # 清除缓存
        self._cache.delete(key)
        
        # 从数据库删除
        try:
            db = await get_db()
            await db.execute(
                "DELETE FROM contexts WHERE context_key = ?",
                (key,)
            )
            await db.commit()
            log.info(f"上下文已清空: {key}")
        except Exception as e:
            log.error(f"清空上下文失败: {e}", exc_info=True)
    
    async def get_all_keys(self) -> List[str]:
        """获取所有上下文键（用于调试）"""
        try:
            db = await get_db()
            async with db.execute("SELECT context_key FROM contexts") as cursor:
                rows = await cursor.fetchall()
                keys = [row[0] for row in rows]
                log.debug(f"获取所有键: 共 {len(keys)} 个")
                return keys
        except Exception as e:
            log.error(f"获取键列表失败: {e}", exc_info=True)
            return []
    
    async def get_stats(self) -> Dict[str, Any]:
        """获取存储统计信息"""
        try:
            db = await get_db()
            async with db.execute("SELECT COUNT(*) FROM contexts") as cursor:
                row = await cursor.fetchone()
                total_contexts = row[0] if row else 0
            
            stats = {
                "total_contexts": total_contexts,
                "cached_contexts": len(self._cache),
                "max_cache_size": self._max_cache_size,
                "db_path": str(DB_PATH)
            }
            log.debug(f"存储统计: {stats}")
            return stats
        except Exception as e:
            log.error(f"获取统计信息失败: {e}", exc_info=True)
            return {"error": str(e)}


# 全局存储实例
context_store: Optional[SQLiteContextStore] = None


def get_context_store(max_context: int = 40, max_cache_size: int = MAX_CACHE_SIZE) -> SQLiteContextStore:
    """获取全局上下文存储实例"""
    global context_store
    if context_store is None:
        context_store = SQLiteContextStore(max_context=max_context, max_cache_size=max_cache_size)
    return context_store


# 注意：不在模块顶层注册钩子，因为导入时 NoneBot 可能尚未初始化
# 应在 __init__.py 中手动调用 init_database() 和 close_database()

async def init_context_store() -> None:
    """初始化上下文存储（应在 NoneBot 启动后调用）"""
    log.debug("context_store.init_context_store: use context_db.init_database")
    await init_database()
    log.success("上下文存储初始化完成")


async def close_context_store() -> None:
    """关闭上下文存储（应在 NoneBot 关闭时调用）"""
    await close_database()
    log.info("上下文存储已关闭")
