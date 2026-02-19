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
import json
import re
from typing import List, Dict, Any, Optional, Tuple, TypedDict, Union

from ..infra.logging import logger as log

from .context_cache import LRUCache
from .context_manager import ContextManager
from .context_summarizer import ContextSummarizer
from .context_compress import compress_context_for_safety as _compress_context_for_safety
from .context_compress import compress_message_content as _compress_message_content
from .context_compress import sanitize_text_for_safety as _sanitize_text_for_safety
from .context_store_session_ops import (
    clear_session as service_clear_session,
    get_all_keys as service_get_all_keys,
    get_session_stats as service_get_session_stats,
    get_stats as service_get_stats,
    list_sessions as service_list_sessions,
    preview_text as service_preview_text,
)
from .context_store_summary_ops import (
    build_key_info_summary as service_build_key_info_summary,
    build_summary_for_messages as service_build_summary_for_messages,
    extract_key_info_from_history as service_extract_key_info_from_history,
    get_cached_summary as service_get_cached_summary,
    resolve_summary_runtime_config as service_resolve_summary_runtime_config,
    save_cached_summary as service_save_cached_summary,
)
from .context_store_write_ops import (
    AddMessageDeps,
    add_message_flow as service_add_message_flow,
)
from .context_schema import normalize_content
from .context_db import DB_PATH as _CONTEXT_DB_PATH
from .context_db import get_db, get_db_path, init_database, close_database
from .session_lock import SessionLockManager
from ..runtime import get_config as get_runtime_config

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

# 兼容旧测试/外部补丁入口：context_store.DB_PATH
# 实际数据库路径解析与覆盖由 context_db 统一管理。
DB_PATH = _CONTEXT_DB_PATH


class MessageDict(TypedDict, total=False):
    """消息字典类型定义"""
    role: str
    content: Union[str, List[Dict[str, Any]]]  # 字符串或多模态列表
    message_id: str
    timestamp: float  # 消息时间戳
    tool_calls: List[Dict[str, Any]]
    tool_call_id: str


class ContextStoreWriteError(RuntimeError):
    """上下文持久化写入失败（事务已回滚）。"""


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
    
    def __init__(
        self,
        max_context: int = 40,
        max_cache_size: int = MAX_CACHE_SIZE,
        *,
        context_mode: str = "structured",
        max_turns: int = 30,
        max_tokens_soft: int = 12000,
        summary_enabled: bool = False,
        summary_trigger_turns: int = 20,
        summary_max_chars: int = 500,
        history_store_multimodal: bool = False,
        context_summarizer: Optional[ContextSummarizer] = None,
    ):
        self.max_context = max_context
        # 使用 LRU 缓存替代普通字典，限制缓存大小防止内存溢出
        self._cache: LRUCache = LRUCache(max_size=max_cache_size)
        self._max_cache_size = max_cache_size
        self._context_manager = ContextManager(
            context_mode=context_mode,
            max_turns=max_turns,
            max_tokens_soft=max_tokens_soft,
            summary_enabled=summary_enabled,
            hard_max_messages=max_context * CONTEXT_MESSAGE_MULTIPLIER,
        )
        self._summary_enabled = bool(summary_enabled)
        self._summary_trigger_turns = max(1, int(summary_trigger_turns or 20))
        self._summary_max_chars = max(50, int(summary_max_chars or 500))
        self._context_summarizer = context_summarizer or (
            ContextSummarizer() if self._summary_enabled else None
        )
        self._history_store_multimodal = bool(history_store_multimodal)
        # 关键信息缓存（用户 QQ 号 -> 提取的信息）
        self._key_info_cache: Dict[str, Dict[str, str]] = {}
        # 会话级写锁池（按 context_key 串行，避免全局锁造成跨会话阻塞）
        self._lock_manager = SessionLockManager(
            max_locks=max(512, max_cache_size * 4),
            ttl_seconds=3600.0,
        )
    
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
        """从消息内容中提取用户身份 (平台ID, 昵称)
        
        消息格式：[昵称(平台ID)]: 内容
        Returns:
            (user_id, nickname) 元组
        """
        match = re.match(r'\[(.*?)\(([^)]+)\)\]:', content)
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
            用户平台 ID -> 信息字典 的映射
        """
        return service_extract_key_info_from_history(
            messages,
            extract_user_identity_from_message_fn=self._extract_user_identity_from_message,
            extract_key_info_from_message_fn=self._extract_key_info_from_message,
        )
    
    def _build_key_info_summary(self, user_info: Dict[str, Dict[str, str]]) -> str:
        """构建关键信息摘要
        
        Args:
            user_info: 用户信息字典
            
        Returns:
            格式化的摘要字符串
        """
        return service_build_key_info_summary(user_info)

    def _resolve_summary_runtime_config(self) -> Tuple[str, str, str, Dict[str, str]]:
        """解析摘要调用所需的 provider/base_url/model/key。"""
        return service_resolve_summary_runtime_config(
            get_runtime_config_fn=get_runtime_config,
        )

    async def _get_cached_summary(self, context_key: str) -> Tuple[str, int]:
        return await service_get_cached_summary(
            context_key,
            get_db_fn=get_db,
        )

    async def _save_cached_summary(
        self,
        context_key: str,
        summary: str,
        source_message_count: int,
    ) -> None:
        await service_save_cached_summary(
            context_key,
            summary,
            source_message_count,
            get_db_fn=get_db,
            log_obj=log,
        )

    async def _build_summary_for_messages(
        self,
        *,
        context_key: str,
        messages: List[MessageDict],
    ) -> str:
        """按需生成或复用历史摘要。"""
        return await service_build_summary_for_messages(
            context_key=context_key,
            messages=messages,
            summary_enabled=self._summary_enabled,
            context_summarizer=self._context_summarizer,
            summary_max_chars=self._summary_max_chars,
            get_cached_summary_caller=self._get_cached_summary,
            resolve_summary_runtime_config_caller=self._resolve_summary_runtime_config,
            save_cached_summary_caller=self._save_cached_summary,
        )
    
    async def _compress_context(
        self,
        messages: List[MessageDict],
        context_key: str
    ) -> List[MessageDict]:
        """上下文截断
        
        策略：仅保留最近 N 条完整消息（FIFO）
        注意：用户决定禁用智能摘要功能，因此不再注入摘要。
        """
        max_messages = self.max_context * CONTEXT_MESSAGE_MULTIPLIER

        async def _summary_builder(old_messages: List[MessageDict]) -> str:
            return await self._build_summary_for_messages(
                context_key=context_key,
                messages=old_messages,
            )

        compressed = await self._context_manager.process_with_summary(
            messages,
            summary_builder=_summary_builder if self._summary_enabled else None,
            summary_trigger_turns=self._summary_trigger_turns,
            summary_max_chars=self._summary_max_chars,
        )
        if len(compressed) > max_messages:
            compressed = compressed[-max_messages:]

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
                    raw_messages = json.loads(row[0])
                    messages = self._context_manager.normalize(raw_messages)
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
        timestamp: Optional[float] = None,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        tool_call_id: Optional[str] = None,
    ) -> None:
        """添加消息到上下文
        
        改进：使用智能压缩替代简单截断，保留关键用户信息
        """
        key = self._make_key(user_id, group_id)
        async with self._lock_manager.get_lock(key):
            await service_add_message_flow(
                deps=AddMessageDeps(
                    get_context_caller=self.get_context,
                    build_summary_for_messages_caller=self._build_summary_for_messages,
                    context_manager=self._context_manager,
                    summary_enabled=self._summary_enabled,
                    summary_trigger_turns=self._summary_trigger_turns,
                    summary_max_chars=self._summary_max_chars,
                    max_context=self.max_context,
                    context_message_multiplier=CONTEXT_MESSAGE_MULTIPLIER,
                    compress_context_caller=self._compress_context,
                    prepare_snapshot_messages_caller=self._prepare_snapshot_messages,
                    cache_setter=self._cache.set,
                    get_db_fn=get_db,
                    log_obj=log,
                    context_write_error_cls=ContextStoreWriteError,
                ),
                context_key=key,
                user_id=user_id,
                role=role,
                content=content,
                group_id=group_id,
                message_id=message_id,
                timestamp=timestamp,
                tool_calls=tool_calls,
                tool_call_id=tool_call_id,
            )

    def _textify_content_for_snapshot(
        self, content: Union[str, List[Dict[str, Any]]]
    ) -> str:
        """将多模态 content 压缩为文本，降低历史上下文 token 与网络成本。"""
        normalized = normalize_content(content)
        if isinstance(normalized, str):
            return normalized

        text_parts: List[str] = []
        for item in normalized:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "").lower()
            if item_type == "text":
                text = str(item.get("text") or "").strip()
                if text:
                    text_parts.append(text)
            elif item_type == "image_url":
                text_parts.append("[图片]")
        return " ".join(text_parts).strip()

    def _prepare_snapshot_messages(
        self, messages: List[MessageDict]
    ) -> List[MessageDict]:
        """准备持久化快照；默认将历史图片 part 文本化为 [图片]。"""
        if self._history_store_multimodal:
            return messages

        prepared: List[MessageDict] = []
        for message in messages:
            item: MessageDict = dict(message)
            item["content"] = self._textify_content_for_snapshot(
                message.get("content", "")
            )
            prepared.append(item)
        return prepared
    
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
            await db.execute(
                "DELETE FROM context_summaries WHERE context_key = ?",
                (key,),
            )
            await db.commit()
            log.info(f"上下文已清空: {key}")
        except Exception as e:
            log.error(f"清空上下文失败: {e}", exc_info=True)

    def _preview_text(self, raw_content: Any, *, max_length: int = 120) -> str:
        """将消息内容转换为可展示的单行预览文本。"""
        return service_preview_text(
            raw_content,
            textify_content_for_snapshot_fn=self._textify_content_for_snapshot,
            max_length=max_length,
        )

    async def list_sessions(
        self,
        *,
        query: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """分页列出会话（用于 WebUI 会话管理）。"""
        return await service_list_sessions(
            query=query,
            page=page,
            page_size=page_size,
            get_db_fn=get_db,
            log_obj=log,
        )

    async def get_session_stats(
        self,
        session_key: str,
        *,
        preview_limit: int = 5,
    ) -> Dict[str, Any]:
        """获取单个会话统计信息与消息预览。"""
        return await service_get_session_stats(
            session_key,
            preview_limit=preview_limit,
            get_db_fn=get_db,
            preview_text_fn=self._preview_text,
            log_obj=log,
        )

    async def clear_session(
        self,
        session_key: str,
        *,
        purge_archive: bool = True,
        purge_topic_state: bool = True,
    ) -> Dict[str, int]:
        """按会话键清空上下文数据（用于 WebUI）。"""
        return await service_clear_session(
            session_key,
            purge_archive=purge_archive,
            purge_topic_state=purge_topic_state,
            cache_delete_fn=self._cache.delete,
            get_db_fn=get_db,
            log_obj=log,
        )
    
    async def get_all_keys(self) -> List[str]:
        """获取所有上下文键（用于调试）"""
        return await service_get_all_keys(
            get_db_fn=get_db,
            log_obj=log,
        )
    
    async def get_stats(self) -> Dict[str, Any]:
        """获取存储统计信息"""
        return await service_get_stats(
            get_db_fn=get_db,
            get_db_path_fn=get_db_path,
            cache_len=len(self._cache),
            max_cache_size=self._max_cache_size,
            log_obj=log,
        )


# 全局存储实例
context_store: Optional[SQLiteContextStore] = None


def get_context_store(
    max_context: int = 40,
    max_cache_size: int = MAX_CACHE_SIZE,
    *,
    context_mode: str = "structured",
    max_turns: int = 30,
    max_tokens_soft: int = 12000,
    summary_enabled: bool = False,
    summary_trigger_turns: int = 20,
    summary_max_chars: int = 500,
    history_store_multimodal: bool = False,
) -> SQLiteContextStore:
    """获取全局上下文存储实例"""
    global context_store
    if context_store is None:
        context_store = SQLiteContextStore(
            max_context=max_context,
            max_cache_size=max_cache_size,
            context_mode=context_mode,
            max_turns=max_turns,
            max_tokens_soft=max_tokens_soft,
            summary_enabled=summary_enabled,
            summary_trigger_turns=summary_trigger_turns,
            summary_max_chars=summary_max_chars,
            history_store_multimodal=history_store_multimodal,
        )
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
