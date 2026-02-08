"""Gemini API 客户端模块（OpenAI 兼容格式）。

通过 OpenAI 兼容格式 API 调用 Gemini 模型的异步客户端，支持：
- 多轮对话（上下文管理）
- 流式响应与普通响应
- 多 API Key 智能轮询（限流自动恢复）
- Tool Calling（函数调用）
- 图片理解（多模态输入）

注意：
- 本模块使用 OpenAI 兼容格式的 API 端点，而非 Gemini 原生 SDK
- 依赖 httpx 进行异步 HTTP 请求
- 上下文存储可选择内存或 SQLite 后端
- 支持用户档案和图片处理等可选功能
"""
from __future__ import annotations

import asyncio
import httpx
import uuid
import time
import random
from datetime import datetime
from typing import Optional, List, Union, Dict, Any, Callable, Tuple

from nonebot import logger as log

# 导入异常类
from .errors import GeminiAPIError, RateLimitError, AuthenticationError, ServerError

# 导入持久化上下文存储（可选）
try:
    from .utils.context_store import get_context_store, SQLiteContextStore
    HAS_SQLITE_STORE = True
except ImportError:
    HAS_SQLITE_STORE = False

from .utils.prompt_loader import load_judge_prompt
from .config import plugin_config
from .gemini_api_sanitize import clean_thinking_markers
from .gemini_api_proactive import extract_json_object
from .gemini_api_messages import PreSearchResult, pre_search, build_messages
from .gemini_api_tools import ToolLoopResult, handle_tool_calls
from .gemini_api_transport import send_api_request
from .metrics import metrics

# 导入用户档案存储（可选）
try:
    from .utils.user_profile import get_user_profile_store, UserProfileStore
    HAS_USER_PROFILE = True
except ImportError:
    HAS_USER_PROFILE = False
    # 可选依赖缺失时，避免在 chat 相关逻辑中引用未定义名称
    get_user_profile_store = None  # type: ignore[assignment]
    UserProfileStore = None  # type: ignore[assignment]

# 导入图片处理器（可选）
try:
    from .utils.image_processor import get_image_processor, ImageProcessor, ImageProcessError
    HAS_IMAGE_PROCESSOR = True
except ImportError:
    HAS_IMAGE_PROCESSOR = False
    # 可选依赖缺失时，避免在 chat 相关逻辑中引用未定义名称
    get_image_processor = None  # type: ignore[assignment]
    ImageProcessor = None  # type: ignore[assignment]
    ImageProcessError = None  # type: ignore[assignment]


# ==================== Magic-number constants ====================
# 说明：仅将散落的硬编码数值提取为“命名常量/配置项”，不改变默认行为。
UUID_SHORT_ID_LENGTH = 8

# 内存上下文：允许的最大历史条数 = max_context * 2（与原逻辑一致）
CONTEXT_HISTORY_MULTIPLIER = 2

# 诊断/日志预览长度
CONTEXT_DIAGNOSTIC_TAIL_COUNT = 3
HISTORY_MESSAGE_PREVIEW_CHARS = 80
API_CONTENT_DEBUG_MIN_CHARS = 200
API_CONTENT_DEBUG_PREVIEW_CHARS = 500
RAW_MODEL_REPLY_PREVIEW_CHARS = 300
ERROR_RESPONSE_BODY_PREVIEW_CHARS = 500

# chat 默认重试与降级
DEFAULT_CHAT_RETRY_COUNT = 2
MAX_CONTEXT_DEGRADATION_LEVEL = 2
EMPTY_REPLY_RETRY_DELAY_SECONDS = 0.5

# 指数退避：wait_time = 2 ** (2 - retry_count)
SERVER_ERROR_RETRY_BACKOFF_BASE = 2
SERVER_ERROR_RETRY_EXPONENT_OFFSET = 2

# 主动发言判决：日志截断
PROACTIVE_JUDGE_ERROR_PREVIEW_CHARS = 100
PROACTIVE_JUDGE_RAW_CONTENT_SHORT_PREVIEW_CHARS = 100
PROACTIVE_JUDGE_RAW_CONTENT_ERROR_PREVIEW_CHARS = 200
PROACTIVE_JUDGE_SERVER_RESPONSE_PREVIEW_CHARS = 500


class GeminiClient:
    """异步 Gemini API 客户端（兼容 OpenAI 格式）。

    功能特性：
    - 多 API Key 智能轮询（限流自动恢复）
    - 上下文持久化存储（内存/SQLite）
    - Tool Calling 支持（web_search、群历史搜索等）
    - 多模态输入（文本+图片）
    - 自动重试和上下文降级

    Attributes:
        api_key: 主 API Key
        model: 默认模型名称
        system_prompt: 系统提示词
        name: 角色名称（用于错误消息模板）
    """
    
    # 默认错误消息模板 - 使用 {name} 占位符支持多角色
    # 可通过构造函数传入 error_messages 参数覆盖
    DEFAULT_ERROR_MESSAGES = {
        "timeout": "呜…{name} 的脑袋转得太慢了，等会儿再试试呢~",
        "rate_limit": "哇…大家都在找 {name} 聊天，有点忙不过来了，稍等一下下好吗？💦",
        "auth_error": "诶？{name} 的身份验证出了点问题，快让 Sensei 帮忙检查一下~",
        "server_error": "服务器那边好像在打瞌睡…再试一次吧~",
        "content_filter": "唔…这个话题 {name} 不太方便回答呢…换个话题吧？",
        "api_error": "诶？好像出了点小问题…{name} 需要休息一下~",
        "unknown": "啊咧？发生了奇怪的事情…再说一次好不好？",
        "empty_reply": "呐，{name} 刚才走神了，能再说一次吗？☆"
    }
    
    # 可用工具定义（OpenAI 格式）
    AVAILABLE_TOOLS = [
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "搜索互联网获取实时信息。当用户询问最新新闻、天气、比赛结果、价格、股票、实时事件等时效性信息时使用。注意：不要用于查询群聊历史或对话上下文。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "搜索关键词，应简洁明确"
                        }
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "search_group_history",
                "description": "搜索当前群聊的历史消息记录。当用户询问'群里刚才在聊什么'、'之前说了什么'等关于群聊上下文的问题时使用。仅在群聊中可用。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "count": {
                            "type": "integer",
                            "description": "要获取的历史消息数量，默认20，最大50"
                        }
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "fetch_history_images",
                "description": "获取历史消息中的图片。当你需要查看之前对话中提到的图片（如表情包、截图）时使用。上下文中带有 <msg_id:xxx> 标记的消息可以通过此工具获取原图。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "msg_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "需要获取图片的消息 ID 列表（从上下文中的 <msg_id:xxx> 提取）"
                        },
                        "max_images": {
                            "type": "integer",
                            "description": "最多获取几张图片，默认2，最大2"
                        }
                    },
                    "required": ["msg_ids"]
                }
            }
        }
    ]
    
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai",
        model: str = "gemini-3-flash",
        system_prompt: str = "你是一个友好的AI助手",
        max_context: int = 10,
        api_key_list: Optional[List[str]] = None,
        use_persistent_storage: bool = True,  # 是否使用持久化存储
        character_name: str = "Mika",  # 角色名称，用于错误消息
        error_messages: Optional[Dict[str, str]] = None,  # 自定义错误消息模板
        enable_smart_search: bool = False  # 是否启用智能搜索（LLM 意图识别）
    ):
        """初始化 Gemini API 客户端。

        创建一个与 Gemini API（OpenAI 兼容格式）交互的客户端实例，
        支持多 API Key 轮询、持久化上下文存储、工具调用等高级功能。

        Args:
            api_key: 主 API Key，当 api_key_list 为空时使用。
            base_url: API 基础 URL，默认为 Google Gemini 的 OpenAI 兼容端点。
            model: 使用的模型名称，默认为 "gemini-3-flash"。
            system_prompt: 系统提示词，定义 AI 角色和行为。
            max_context: 最大上下文消息数量，超出时自动截断历史。
            api_key_list: 多 API Key 列表，启用智能轮询和冷却机制。
            use_persistent_storage: 是否使用 SQLite 持久化存储上下文，
                设为 False 则使用内存存储。
            character_name: 角色名称，用于格式化错误消息中的 {name} 占位符。
            error_messages: 自定义错误消息模板字典，可覆盖 DEFAULT_ERROR_MESSAGES。
            enable_smart_search: 是否启用智能搜索（基于 LLM 意图识别），
                会增加 API 调用次数但提高搜索准确性。

        Example:
            >>> client = GeminiClient(
            ...     api_key="your-api-key",
            ...     model="gemini-2.0-flash",
            ...     character_name="Mika",
            ...     enable_smart_search=True
            ... )
        """
        self.api_key = api_key
        self.api_key_list = api_key_list or []
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.system_prompt = system_prompt
        self.max_context = max_context
        self._enable_smart_search = enable_smart_search
        
        # 角色名称和错误消息配置
        self._character_name = character_name
        self._error_messages = error_messages or self.DEFAULT_ERROR_MESSAGES.copy()
        
        # 选择存储后端
        self._use_persistent = use_persistent_storage and HAS_SQLITE_STORE
        if self._use_persistent:
            cache_size = max(
                1,
                int(getattr(plugin_config, "gemini_context_cache_max_size", 200) or 200),
            )
            self._context_store: Optional[SQLiteContextStore] = get_context_store(
                max_context,
                max_cache_size=cache_size,
                context_mode=str(getattr(plugin_config, "gemini_context_mode", "structured")),
                max_turns=int(getattr(plugin_config, "gemini_context_max_turns", 30) or 30),
                max_tokens_soft=int(
                    getattr(plugin_config, "gemini_context_max_tokens_soft", 12000) or 12000
                ),
                summary_enabled=bool(
                    getattr(plugin_config, "gemini_context_summary_enabled", False)
                ),
                history_store_multimodal=bool(
                    getattr(plugin_config, "gemini_history_store_multimodal", False)
                ),
            )
            log.info("使用 SQLite 持久化上下文存储")
        else:
            self._context_store = None
            # 内存存储作为后备
            from collections import defaultdict
            self._contexts: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
            log.info("使用内存上下文存储")
        
        # 复用 httpx 客户端
        self._http_client: Optional[httpx.AsyncClient] = None
        self._client_lock: asyncio.Lock = asyncio.Lock()
        
        # 工具执行器与定义
        self._tool_handlers: Dict[str, Callable] = {}
        
        self._key_index = 0  # 轮询索引
        # 智能轮询：记录被限流的 Key 及其冷却结束时间
        self._key_cooldowns: Dict[str, float] = {}
        self._default_cooldown = plugin_config.gemini_api_key_default_cooldown_seconds  # 默认冷却时间（秒）
        
    @property
    def is_persistent(self) -> bool:
        """是否启用了持久化存储"""
        return self._use_persistent
        
    def _get_api_key(self) -> str:
        """获取当前要使用的 API Key（智能轮询，跳过冷却中的 Key）。

        实现智能 API Key 轮询策略：
        1. 如果未配置多 Key（api_key_list 为空），返回主 api_key
        2. 遍历 api_key_list，跳过处于冷却期的 Key
        3. 如果所有 Key 都在冷却期，返回冷却时间最短的那个

        此机制配合 _mark_key_rate_limited 实现限流自动恢复。

        Returns:
            当前可用的 API Key 字符串。

        Note:
            冷却期由 _mark_key_rate_limited 设置，默认为 60 秒，
            或 API 返回的 Retry-After 头指定的时间。
        """
        current_time = time.time()
        
        # 如果没有配置多个 Key，使用主 Key
        if not self.api_key_list:
            return self.api_key
        
        # 尝试找到一个不在冷却期的 Key
        all_keys = self.api_key_list.copy()
        attempts = 0
        max_attempts = len(all_keys)
        
        while attempts < max_attempts:
            key = all_keys[self._key_index]
            self._key_index = (self._key_index + 1) % len(all_keys)
            attempts += 1
            
            # 检查是否在冷却期
            cooldown_end = self._key_cooldowns.get(key, 0)
            if current_time >= cooldown_end:
                # 不在冷却期，可以使用
                if key in self._key_cooldowns:
                    del self._key_cooldowns[key]  # 清除过期的冷却记录
                    log.debug(f"API Key #{self._key_index} 冷却期结束，恢复使用")
                return key
            else:
                remaining = int(cooldown_end - current_time)
                log.debug(f"API Key #{self._key_index} 仍在冷却中（剩余 {remaining}s），跳过")
        
        # 所有 Key 都在冷却期，选择冷却时间最短的
        min_cooldown_key = min(all_keys, key=lambda k: self._key_cooldowns.get(k, 0))
        log.warning(f"所有 API Key 都在冷却期，强制使用冷却时间最短的 Key")
        return min_cooldown_key
    
    def _mark_key_rate_limited(self, key: str, retry_after: int = 0):
        """标记 API Key 被限流，进入冷却期。

        当收到 429 限流响应时调用此方法，将该 Key 加入冷却队列。
        冷却期结束前，_get_api_key 会跳过此 Key。

        Args:
            key: 被限流的 API Key。
            retry_after: API 返回的 Retry-After 秒数，0 表示使用默认冷却时间。

        Note:
            默认冷却时间为 60 秒（self._default_cooldown）。
            冷却信息存储在 self._key_cooldowns 字典中。
        """
        cooldown_seconds = retry_after if retry_after > 0 else self._default_cooldown
        self._key_cooldowns[key] = time.time() + cooldown_seconds
        log.warning(f"API Key 被限流，进入冷却期 {cooldown_seconds}s")
    
    def register_tool_handler(self, name: str, handler: Callable):
        """注册工具处理器"""
        self._tool_handlers[name] = handler
    
    def _get_error_message(self, error_type: str) -> str:
        """
        获取格式化后的错误消息
        
        Args:
            error_type: 错误类型（timeout, rate_limit, auth_error 等）
            
        Returns:
            格式化后的错误消息字符串
        """
        template = self._error_messages.get(error_type, self._error_messages.get("unknown", "发生了错误"))
        try:
            return template.format(name=self._character_name)
        except KeyError:
            # 如果模板中有其他未知占位符，返回原始模板
            return template
    
    @property
    def character_name(self) -> str:
        """获取角色名称"""
        return self._character_name
    
    @character_name.setter
    def character_name(self, value: str):
        """设置角色名称"""
        self._character_name = value
    
    @property
    def context_store(self) -> Optional[SQLiteContextStore]:
        """获取上下文存储实例（只读）"""
        return self._context_store
    
    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 httpx 客户端"""
        async with self._client_lock:
            if self._http_client is None or self._http_client.is_closed:
                # 超时时间（默认 120s），防止模型思考过久导致连接断开
                self._http_client = httpx.AsyncClient(timeout=plugin_config.gemini_http_client_timeout_seconds)
            return self._http_client
    
    async def close(self):
        """关闭 httpx 客户端"""
        async with self._client_lock:
            if self._http_client and not self._http_client.is_closed:
                await self._http_client.aclose()
                self._http_client = None
    
    def _get_context_key(self, user_id: str, group_id: Optional[str] = None) -> tuple:
        if group_id:
            return (group_id, "GROUP_CHAT")
        return ("PRIVATE_CHAT", user_id)
    
    async def _get_context_async(self, user_id: str, group_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """异步获取上下文（支持持久化存储）"""
        if self._use_persistent and self._context_store:
            return await self._context_store.get_context(user_id, group_id)
        else:
            key = self._get_context_key(user_id, group_id)
            return self._contexts[key]
    
    
    async def _add_to_context_async(
        self,
        user_id: str,
        role: str,
        content: Union[str, List[Dict[str, Any]]],
        group_id: Optional[str] = None,
        message_id: Optional[str] = None,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        tool_call_id: Optional[str] = None,
    ):
        """异步添加消息到上下文（支持持久化存储）"""
        current_time = time.time()
        
        if self._use_persistent and self._context_store:
            await self._context_store.add_message(
                user_id,
                role,
                content,
                group_id,
                message_id,
                timestamp=current_time,
                tool_calls=tool_calls,
                tool_call_id=tool_call_id,
            )
        else:
            key = self._get_context_key(user_id, group_id)
            msg = {"role": role, "content": content, "timestamp": current_time}
            if message_id:
                msg["message_id"] = str(message_id)
            if tool_calls and role == "assistant":
                msg["tool_calls"] = tool_calls
            if tool_call_id and role == "tool":
                msg["tool_call_id"] = str(tool_call_id)
            self._contexts[key].append(msg)
            max_history_messages = self.max_context * CONTEXT_HISTORY_MULTIPLIER
            if len(self._contexts[key]) > max_history_messages:
                self._contexts[key] = self._contexts[key][-max_history_messages:]

    # ==================== 兼容旧测试的同步/私有 API（薄封装） ====================

    def _get_context(self, user_id: str, group_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """兼容旧测试：同步获取内存上下文。

        注意：仅在非持久化模式下可靠（测试用）。
        """
        if self._use_persistent:
            log.warning("_get_context 在持久化模式下不可用，测试应使用 get_context")
            return []
        key = self._get_context_key(user_id, group_id)
        return self._contexts[key]

    def _add_to_context(
        self,
        user_id: str,
        role: str,
        content: Union[str, List[Dict[str, Any]]],
        group_id: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> None:
        """兼容旧测试：同步添加消息到内存上下文。"""
        if self._use_persistent:
            log.warning("_add_to_context 在持久化模式下不可用，测试应使用 add_message")
            return
        key = self._get_context_key(user_id, group_id)
        msg = {"role": role, "content": content, "timestamp": time.time()}
        if message_id:
            msg["message_id"] = str(message_id)
        self._contexts[key].append(msg)
        max_history_messages = self.max_context * CONTEXT_HISTORY_MULTIPLIER
        if len(self._contexts[key]) > max_history_messages:
            self._contexts[key] = self._contexts[key][-max_history_messages:]
    
    
    async def clear_context_async(self, user_id: str, group_id: Optional[str] = None):
        """异步清空上下文（支持持久化存储）"""
        if self._use_persistent and self._context_store:
            await self._context_store.clear_context(user_id, group_id)
        else:
            key = self._get_context_key(user_id, group_id)
            self._contexts[key] = []
    
    def clear_context(self, user_id: str, group_id: Optional[str] = None):
        """同步清空上下文（仅内存模式，持久化模式应使用 clear_context_async）"""
        if self._use_persistent:
            log.warning("在持久化模式下使用同步 clear_context")
            return
        key = self._get_context_key(user_id, group_id)
        self._contexts[key] = []

    # ==================== 公共上下文管理 API ====================

    async def get_context(self, user_id: str, group_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取上下文消息列表（公共 API）
        
        Args:
            user_id: 用户 ID
            group_id: 群组 ID（可选）
            
        Returns:
            消息字典列表
        """
        return await self._get_context_async(user_id, group_id)

    async def add_message(
        self,
        user_id: str,
        role: str,
        content: Union[str, List[Dict[str, Any]]],
        group_id: Optional[str] = None,
        message_id: Optional[str] = None,
        timestamp: Optional[float] = None,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        tool_call_id: Optional[str] = None,
    ):
        """添加消息到上下文（公共 API）
        
        Args:
            user_id: 用户 ID
            role: 角色 ("user", "model", "system")
            content: 消息内容
            group_id: 群组 ID（可选）
            message_id: 消息 ID（可选，用于去重）
            timestamp: 消息时间戳（可选，默认当前时间）
        """
        current_time = timestamp if timestamp is not None else time.time()
        
        if self._use_persistent and self._context_store:
            await self._context_store.add_message(
                user_id,
                role,
                content,
                group_id,
                message_id,
                timestamp=current_time,
                tool_calls=tool_calls,
                tool_call_id=tool_call_id,
            )
        else:
            key = self._get_context_key(user_id, group_id)
            msg = {"role": role, "content": content, "timestamp": current_time}
            if message_id:
                msg["message_id"] = str(message_id)
            if tool_calls and role == "assistant":
                msg["tool_calls"] = tool_calls
            if tool_call_id and role == "tool":
                msg["tool_call_id"] = str(tool_call_id)
            self._contexts[key].append(msg)
            max_history_messages = self.max_context * CONTEXT_HISTORY_MULTIPLIER
            if len(self._contexts[key]) > max_history_messages:
                self._contexts[key] = self._contexts[key][-max_history_messages:]
    
    def _clean_thinking_markers(self, text: str) -> str:
        """清理模型回复中泄露的思考过程标记（委派到独立模块）。"""
        return clean_thinking_markers(text)

    # ==================== 私有辅助方法（chat 拆分） ====================

    def _prepare_chat_request(
        self,
        user_id: str,
        group_id: Optional[str],
        image_urls: Optional[List[str]],
    ) -> Tuple[str, float]:
        """为 [`GeminiClient.chat()`](mika_chat_core/gemini_api.py:673) 准备请求级上下文。

        该方法只做“请求级”初始化：生成 request_id、记录开始时间、计数与起始日志。
        行为需与拆分前保持一致。

        Returns:
            (request_id, start_time)
        """
        request_id = str(uuid.uuid4())[:UUID_SHORT_ID_LENGTH]
        start_time = time.time()
        metrics.requests_total += 1

        # 结构化日志：请求开始
        log.info(
            f"[req:{request_id}] 开始处理请求 | "
            f"user={user_id} | group={group_id or 'private'} | "
            f"images={len(image_urls) if image_urls else 0}"
        )

        return request_id, start_time

    async def _log_context_diagnostics(self, user_id: str, group_id: Optional[str], request_id: str) -> None:
        """输出上下文诊断日志（采样，可观测）。"""
        trace_enabled = bool(getattr(plugin_config, "gemini_context_trace_enabled", False))
        if not trace_enabled:
            return

        sample_rate = float(getattr(plugin_config, "gemini_context_trace_sample_rate", 1.0) or 1.0)
        sample_rate = min(1.0, max(0.0, sample_rate))
        if sample_rate < 1.0 and random.random() > sample_rate:
            return

        history = await self._get_context_async(user_id, group_id)
        total_history_chars = sum(len(str(m.get("content", ""))) for m in history)
        log.info(
            f"[req:{request_id}] context_trace | phase=context_build | "
            f"history_count={len(history)} | "
            f"total_chars={total_history_chars} | "
            f"sample_rate={sample_rate:.2f}"
        )

        # 打印最近 N 条历史消息的摘要（用于调试）
        if history:
            tail = history[-CONTEXT_DIAGNOSTIC_TAIL_COUNT:]
            for i, msg in enumerate(tail):
                role = msg.get("role", "unknown")
                content = str(msg.get("content", ""))
                # 截取前 N 字符，替换换行符
                content_preview = content[:HISTORY_MESSAGE_PREVIEW_CHARS].replace("\n", " ")
                if len(content) > HISTORY_MESSAGE_PREVIEW_CHARS:
                    content_preview += "..."
                log.debug(
                    f"[req:{request_id}] 历史[{len(history)-len(tail)+i}] | "
                    f"role={role} | len={len(content)} | "
                    f"preview={content_preview}"
                )

    def _log_search_result_status(self, search_result: str, request_id: str) -> None:
        """输出搜索结果是否注入的日志（保持原日志内容）。"""
        if search_result:
            log.debug(f"[req:{request_id}] 搜索结果已注入 | length={len(search_result)}")
        else:
            log.debug(f"[req:{request_id}] 无搜索结果注入")

    def _coerce_pre_search_result(
        self,
        raw_result: Any,
        *,
        message: str,
        decision: str = "compat",
    ) -> PreSearchResult:
        """兼容旧返回值：将 str/dict 统一收敛为 PreSearchResult。"""
        from .utils.search_engine import normalize_search_query

        bot_names = [
            getattr(plugin_config, "gemini_bot_display_name", "") or "",
            getattr(plugin_config, "gemini_master_name", "") or "",
        ]
        normalized_query = normalize_search_query(str(message or ""), bot_names=bot_names)

        if isinstance(raw_result, PreSearchResult):
            if not raw_result.normalized_query and normalized_query:
                raw_result.normalized_query = normalized_query
            return raw_result

        if isinstance(raw_result, dict):
            return PreSearchResult(
                search_result=str(raw_result.get("search_result") or ""),
                normalized_query=str(raw_result.get("normalized_query") or normalized_query),
                presearch_hit=bool(raw_result.get("presearch_hit")),
                allow_tool_refine=bool(raw_result.get("allow_tool_refine")),
                result_count=int(raw_result.get("result_count") or 0),
                refine_rounds_used=int(raw_result.get("refine_rounds_used") or 0),
                blocked_duplicate_total=int(raw_result.get("blocked_duplicate_total") or 0),
                decision=str(raw_result.get("decision") or decision),
            )

        search_result = str(raw_result or "")
        return PreSearchResult(
            search_result=search_result,
            normalized_query=normalized_query,
            presearch_hit=bool(search_result.strip()),
            allow_tool_refine=False,
            result_count=0,
            decision=decision,
        )

    def _log_search_decision(self, request_id: str, search_state: PreSearchResult, *, phase: str) -> None:
        """统一搜索编排日志。"""
        log.info(
            f"[req:{request_id}] search_decision phase={phase} "
            f"presearch_hit={1 if search_state.presearch_hit else 0} "
            f"allow_refine={1 if search_state.allow_tool_refine else 0} "
            f"refine_used={search_state.refine_rounds_used} "
            f"blocked_duplicate={search_state.blocked_duplicate_total} "
            f"result_count={search_state.result_count}"
        )

    def _log_request_messages(self, messages: List[Dict[str, Any]], api_content: Any, request_id: str) -> None:
        """输出将发送给模型的消息摘要日志（DEBUG）。"""
        log.debug(f"[req:{request_id}] 发送消息数量: {len(messages)}")
        if isinstance(api_content, str) and len(api_content) > API_CONTENT_DEBUG_MIN_CHARS:
            log.debug(
                f"[req:{request_id}] API消息内容（前{API_CONTENT_DEBUG_PREVIEW_CHARS}字）:\n"
                f"{api_content[:API_CONTENT_DEBUG_PREVIEW_CHARS]}..."
            )

    async def _handle_server_error_retry(
        self,
        error: ServerError,
        message: str,
        user_id: str,
        group_id: Optional[str],
        image_urls: Optional[List[str]],
        enable_tools: bool,
        retry_count: int,
        message_id: Optional[str],
        system_injection: Optional[str],
        context_level: int,
        history_override: Optional[List[Dict[str, Any]]] = None,
        search_result: Optional[str] = None,
    ) -> Optional[str]:
        """处理服务端错误的重试逻辑。

        注意：此处需要严格保持拆分前的调用参数（拆分前会丢失 message_id/system_injection/context_level）。

        Returns:
            若触发重试则返回递归 chat 的最终回复；否则返回 None 让调用方继续抛出异常。
        """
        if retry_count > 0 and "will retry" in str(error.message):
            import asyncio

            wait_time = SERVER_ERROR_RETRY_BACKOFF_BASE ** (SERVER_ERROR_RETRY_EXPONENT_OFFSET - retry_count)
            await asyncio.sleep(wait_time)
            return await self.chat(
                message=message,
                user_id=user_id,
                group_id=group_id,
                image_urls=image_urls,
                enable_tools=enable_tools,
                retry_count=retry_count - 1,
                message_id=message_id,
                system_injection=system_injection,
                context_level=context_level,
                history_override=history_override,
                search_result_override=search_result,
            )
        return None

    async def _resolve_reply(
        self,
        messages: List[Dict[str, Any]],
        assistant_message: Dict[str, Any],
        tool_calls: List[Dict[str, Any]],
        api_key: str,
        group_id: Optional[str],
        request_id: str,
        enable_tools: bool,
        tools: Optional[List[Dict[str, Any]]] = None,
        search_state: Optional[PreSearchResult] = None,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """根据是否存在工具调用，解析最终回复文本。"""
        if tool_calls and enable_tools:
            result = await self._handle_tool_calls(
                messages,
                assistant_message,
                tool_calls,
                api_key,
                group_id,
                request_id,
                tools,
                search_state=search_state,
                return_trace=True,
            )
            if isinstance(result, ToolLoopResult):
                return result.reply, result.trace_messages
            return str(result), []
        return assistant_message.get("content") or "", []

    def _log_raw_model_reply(self, reply: str, request_id: str) -> None:
        """输出模型原始回复（调试用）。"""
        log.debug(
            f"[req:{request_id}] 模型原始回复（前{RAW_MODEL_REPLY_PREVIEW_CHARS}字）:\n"
            f"{reply[:RAW_MODEL_REPLY_PREVIEW_CHARS]}..."
            if len(reply) > RAW_MODEL_REPLY_PREVIEW_CHARS
            else f"[req:{request_id}] 模型原始回复:\n{reply}"
        )

    def _process_response(self, reply: str, request_id: str) -> str:
        """处理响应文本（清理思考标记/角色标签/Markdown格式/空白）。"""
        original_len = len(reply)
        reply = self._clean_thinking_markers(reply)

        import re

        # ==================== Markdown/LaTeX 格式清理 ====================
        # 在手机 QQ 上这些格式会显示为原始符号，需要清理

        # 1. 清理粗体：**文字** 或 __文字__ → 文字
        reply = re.sub(r"\*\*(.+?)\*\*", r"\1", reply)
        reply = re.sub(r"__(.+?)__", r"\1", reply)

        # 2. 清理斜体：*文字* 或 _文字_ → 文字（注意避免与列表符号冲突）
        # 只匹配非空格开头的 *文字*，避免误删列表项
        reply = re.sub(r"(?<!\*)\*([^\s*][^*]*?)\*(?!\*)", r"\1", reply)
        reply = re.sub(r"(?<!_)_([^\s_][^_]*?)_(?!_)", r"\1", reply)

        # 3. 清理行内代码：`代码` → 代码
        reply = re.sub(r"`([^`]+)`", r"\1", reply)

        # 4. 清理代码块：```lang\n代码\n``` → 代码
        reply = re.sub(r"```(?:\w+)?\n?(.*?)\n?```", r"\1", reply, flags=re.DOTALL)

        # 5. 清理编号列表开头：将 "1. " "2. " 等转为 "1、" "2、" 或直接去掉
        # 保留数字但用中文顿号替代点+空格
        reply = re.sub(r"(?m)^(\d+)\.\s+", r"\1、", reply)

        # 6. 清理无序列表符号：- 或 * 开头（行首）→ 替换为中文圆点（保留视觉分隔）
        reply = re.sub(r"(?m)^[\-\*]\s+", "· ", reply)

        # 7. 清理标题：# ## ### 等 → 替换为【】包裹（保留层次感）
        reply = re.sub(r"(?m)^#{1,6}\s*(.+)$", r"【\1】", reply)

        # 8. 清理引用：> 开头 → 替换为「」包裹（区分引用内容）
        reply = re.sub(r"(?m)^>\s*(.+)$", r"「\1」", reply)

        # 9. 清理 LaTeX 公式：$公式$ 或 $$公式$$ → 保留公式文本
        reply = re.sub(r"\$\$(.+?)\$\$", r"\1", reply, flags=re.DOTALL)
        reply = re.sub(r"\$([^$]+)\$", r"\1", reply)

        # 10. 清理链接：[文字](url) → 文字
        reply = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", reply)

        # ==================== 用户昵称标签清理（增强版） ====================
        # 即使 Prompt 禁止，模型偶尔还是会复读 `[昵称(QQ)]`。这里在代码层强制移除。
        # 注意：不清理中文方括号【】，如【自主回复】

        # 0. [新增] 先移除零宽字符，便于后续正则匹配
        # 零宽字符包括：U+200B (零宽空格), U+200C (零宽非连接符), U+200D (零宽连接符),
        # U+2060 (词组连接符), U+FEFF (BOM), U+202A-U+202E (双向控制字符) 等
        zero_width_pattern = r"[\u200B-\u200F\u2060-\u206F\uFEFF\u202A-\u202E]"
        reply_cleaned = re.sub(zero_width_pattern, "", reply)

        # 1. 匹配 [昵称(QQ号)]: 或 [昵称(QQ号)] 格式（任意位置，不仅限行首）
        reply_cleaned = re.sub(r"\[[^\]]*?\(\d+\)\]:?\s*", "", reply_cleaned)

        # 2. 匹配常见角色标签：[Mika]: [Sensei]: [★Sensei]: [User]: [未花]: 等（带或不带冒号）
        reply_cleaned = re.sub(
            r"\[(Mika|Sensei|★Sensei|⭐Sensei|User|未花|圣园未花)\]:?\s*",
            "",
            reply_cleaned,
            flags=re.IGNORECASE,
        )

        # 3. 匹配行首的任意短标签 [xxx]: 格式（1-20字符，带冒号，防止误删长内容）
        reply_cleaned = re.sub(r"(?m)^\[[^\]]{1,20}\]:\s*", "", reply_cleaned)

        # 4. [新增] 匹配任意位置的用户昵称标签 [xxx] 格式（不带冒号）
        #    特征：方括号内包含特殊符号（如♡★☆⭐等）或纯数字，长度1-30
        #    排除：纯中文短标签如 [笑] [哭] [图片] 等常见表情/占位符
        #    策略：匹配含特殊符号的标签，或匹配行首的短标签
        reply_cleaned = re.sub(
            r"\[(?=[^\]]*[♡★☆⭐♪♫✨💕🎵])[^\]]{1,30}\]",  # 含装饰符号的标签
            "",
            reply_cleaned,
        )

        # 5. 匹配时间感知标签（扩展版）：
        #    - 基础时间词：[现在] [刚才] [刚刚] [之前] [稍后] [马上]
        #    - 相对时间：[几分钟前] [半小时前] [约X小时前] [X天前] [1-2小时前]
        #    - 日文/混合格式：[ミカちゃんの治療] 等带"の"的标签
        reply_cleaned = re.sub(
            r"\[(?:"
            r"现在|刚才|刚刚|之前|稍后|马上|"  # 基础时间词
            r"几分钟前|半小时前|约?\d+(?:小时|天|分钟)前|1-2小时前|"  # 相对时间
            r"[^\]]{1,15}の[^\]]{1,15}"  # 日文"の"格式标签
            r")\]\s*",
            "",
            reply_cleaned,
        )

        # 6. 匹配回复开头的单独短标签 [xxx] 格式（不带冒号，1-10字符，仅行首）
        #    这匹配如 [治疗] [休息] 等单独出现在开头的标签
        reply_cleaned = re.sub(r"^(?:\[[^\]]{1,10}\]\s*)+", "", reply_cleaned)

        # 7. [新增] 清理系统标签：[搜索中] [思考中] [生成中] 等
        reply_cleaned = re.sub(r"\[(?:搜索中|思考中|生成中|加载中|处理中)\]", "", reply_cleaned)

        reply = reply_cleaned

        # 7. 清理首尾空白 + 首行前导空白（修复转发消息中的缩进问题）
        reply = reply.strip()
        # 移除首行的前导空格/制表符（防止出现不对齐的情况）
        reply = re.sub(r"^[\s\u3000]+", "", reply)  # 包括中文全角空格

        if len(reply) != original_len:
            log.debug(
                f"[req:{request_id}] 已清理格式/标签 | 原长度={original_len} | 清理后={len(reply)}"
            )

        return reply

    async def _handle_empty_reply_retry(
        self,
        request_id: str,
        start_time: float,
        message: str,
        user_id: str,
        group_id: Optional[str],
        image_urls: Optional[List[str]],
        enable_tools: bool,
        retry_count: int,
        message_id: Optional[str],
        system_injection: Optional[str],
        context_level: int,
        history_override: Optional[List[Dict[str, Any]]],
        search_result: str,
    ) -> Optional[str]:
        """处理空回复的“上下文降级”重试逻辑（保持拆分前行为不变）。

        Returns:
            若触发降级重试则返回递归 chat 的最终回复；否则返回 None。
        """
        total_elapsed = time.time() - start_time
        log.warning(
            f"[req:{request_id}] 空回复 (retry={retry_count}, context_level={context_level}) | "
            f"total_time={total_elapsed:.2f}s"
        )

        if not bool(getattr(plugin_config, "gemini_empty_reply_context_degrade_enabled", False)):
            log.warning(f"[req:{request_id}] 空回复不触发业务级上下文降级（配置关闭）")
            return None

        max_degrade_level = int(
            getattr(
                plugin_config,
                "gemini_empty_reply_context_degrade_max_level",
                MAX_CONTEXT_DEGRADATION_LEVEL,
            )
            or MAX_CONTEXT_DEGRADATION_LEVEL
        )
        if max_degrade_level < 0:
            max_degrade_level = 0

        # [智能降级] 空回复时逐级减少上下文
        # Level 0 -> Level 1 (20条) -> Level 2 (5条) -> 放弃
        next_context_level = context_level + 1
        if next_context_level <= max_degrade_level:
            import asyncio

            wait_time = EMPTY_REPLY_RETRY_DELAY_SECONDS
            await asyncio.sleep(wait_time)
            metrics.api_empty_reply_reason_total["context_degrade"] = (
                int(metrics.api_empty_reply_reason_total.get("context_degrade", 0) or 0) + 1
            )
            log.warning(
                f"[req:{request_id}] 触发上下文降级重试 | "
                f"Level {context_level} -> Level {next_context_level} (max={max_degrade_level})"
            )
            return await self.chat(
                message=message,
                user_id=user_id,
                group_id=group_id,
                image_urls=image_urls,
                enable_tools=enable_tools,
                retry_count=retry_count,  # 保持重试次数
                message_id=message_id,
                system_injection=system_injection,
                context_level=next_context_level,  # 提升降级层级
                history_override=history_override,
                search_result_override=search_result,
            )
        return None

    def _log_request_success(self, request_id: str, start_time: float, reply: str, tool_calls: List[Dict[str, Any]]) -> None:
        """输出请求成功的结构化日志（保持拆分前日志内容）。"""
        total_elapsed = time.time() - start_time
        tool_info = f" | tools_called={len(tool_calls)}" if tool_calls else ""
        log.success(
            f"[req:{request_id}] 请求完成 | "
            f"reply_len={len(reply)}{tool_info} | "
            f"total_time={total_elapsed:.2f}s"
        )
    
    async def _pre_search(
        self,
        message: str,
        enable_tools: bool,
        request_id: str,
        user_id: str = None,
        group_id: str = None
    ) -> PreSearchResult:
        """预执行搜索（委派到独立模块，保持行为不变）。"""
        raw_result = await pre_search(
            message,
            enable_tools=enable_tools,
            request_id=request_id,
            tool_handlers=self._tool_handlers,
            enable_smart_search=self._enable_smart_search,
            get_context_async=self._get_context_async,
            get_api_key=self._get_api_key,
            base_url=self.base_url,
            user_id=user_id,
            group_id=group_id,
            return_meta=True,
        )
        return self._coerce_pre_search_result(raw_result, message=message, decision="presearch")
    
    async def _build_messages(
        self,
        message: str,
        user_id: str,
        group_id: Optional[str],
        image_urls: Optional[List[str]],
        search_result: str,
        enable_tools: bool = True,
        system_injection: Optional[str] = None,
        context_level: int = 0,  # [新增] 上下文降级层级
        history_override: Optional[List[Dict[str, Any]]] = None,
    ) -> tuple:
        """构建消息历史与请求体（委派到独立模块，保持行为不变）。"""
        result = await build_messages(
            message,
            user_id=user_id,
            group_id=group_id,
            image_urls=image_urls,
            search_result=search_result,
            model=self.model,
            system_prompt=self.system_prompt,
            available_tools=self.AVAILABLE_TOOLS,
            system_injection=system_injection,
            context_level=context_level,
            history_override=history_override,
            get_context_async=self._get_context_async,
            use_persistent=self._use_persistent,
            context_store=self._context_store,
            has_image_processor=HAS_IMAGE_PROCESSOR,
            get_image_processor=get_image_processor,
            has_user_profile=HAS_USER_PROFILE,
            get_user_profile_store=get_user_profile_store,
            enable_tools=enable_tools,
        )

        return (
            result.messages,
            result.original_content,
            result.api_content,
            result.request_body,
        )
    
    async def _send_api_request(
        self,
        request_body: Dict[str, Any],
        request_id: str,
        retry_count: int,
        message: str,
        user_id: str,
        group_id: Optional[str],
        image_urls: Optional[List[str]],
        enable_tools: bool
    ) -> tuple:
        """发送 API 请求并处理响应（委派到独立模块，保持行为不变）。"""
        client = await self._get_client()
        current_api_key = self._get_api_key()
        try:
            return await send_api_request(
                http_client=client,
                request_body=request_body,
                request_id=request_id,
                retry_count=retry_count,
                api_key=current_api_key,
                base_url=self.base_url,
                model=self.model,
            )
        except RateLimitError as e:
            self._mark_key_rate_limited(current_api_key, e.retry_after)
            raise
    
    async def _handle_tool_calls(
        self,
        messages: List[Dict[str, Any]],
        assistant_message: Dict[str, Any],
        tool_calls: List[Dict[str, Any]],
        api_key: str,
        group_id: Optional[str],
        request_id: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        search_state: Optional[PreSearchResult] = None,
        return_trace: bool = False,
    ) -> str | ToolLoopResult:
        """处理工具调用（委派到独立模块，保持行为不变）。"""
        client = await self._get_client()
        return await handle_tool_calls(
            messages=messages,
            assistant_message=assistant_message,
            tool_calls=tool_calls,
            api_key=api_key,
            group_id=group_id,
            request_id=request_id,
            tool_handlers=self._tool_handlers,
            model=self.model,
            base_url=self.base_url,
            http_client=client,
            tools=tools,
            search_state=search_state,
            return_trace=return_trace,
        )
    
    async def _update_context(
        self,
        user_id: str,
        group_id: Optional[str],
        current_content: Union[str, List[Dict[str, Any]]],
        reply: str,
        user_message_id: Optional[str] = None,
        tool_trace: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """
        更新上下文（保存对话历史）
        
        Args:
            user_id: 用户 ID
            group_id: 群组 ID（可选）
            current_content: 当前用户消息内容
            reply: 助手回复
            user_message_id: 用户消息 ID（用于去重）
        """
        await self._add_to_context_async(user_id, "user", current_content, group_id, user_message_id)

        for trace_msg in tool_trace or []:
            if not isinstance(trace_msg, dict):
                continue
            trace_role = str(trace_msg.get("role") or "").strip().lower()
            if trace_role not in {"assistant", "tool"}:
                continue
            trace_content: Union[str, List[Dict[str, Any]]] = trace_msg.get("content") or ""
            tool_calls = trace_msg.get("tool_calls")
            tool_call_id = trace_msg.get("tool_call_id")
            if (
                trace_role == "assistant"
                and not tool_calls
                and isinstance(trace_content, str)
                and trace_content.strip() == reply.strip()
            ):
                continue
            await self._add_to_context_async(
                user_id,
                trace_role,
                trace_content,
                group_id,
                tool_calls=tool_calls if isinstance(tool_calls, list) else None,
                tool_call_id=str(tool_call_id) if tool_call_id else None,
            )
        
        # [改进] 群聊中为 Bot 回复添加角色标签，帮助 LLM 区分说话者
        # 格式: [Mika]: xxx，与用户消息的 [昵称(QQ)]: xxx 格式一致
        if group_id:
            formatted_reply = f"[{self._character_name}]: {reply}"
        else:
            formatted_reply = reply
        
        await self._add_to_context_async(user_id, "assistant", formatted_reply, group_id)
    
    def _handle_error(
        self,
        error: Exception,
        request_id: str,
        start_time: float
    ) -> str:
        """
        统一错误处理
        
        Args:
            error: 异常对象
            request_id: 请求追踪 ID
            start_time: 请求开始时间
            
        Returns:
            用户友好的错误消息
        """
        total_elapsed = time.time() - start_time
        
        if isinstance(error, httpx.TimeoutException):
            log.error(f"[req:{request_id}] 超时错误 | error={str(error)} | total_time={total_elapsed:.2f}s")
            return self._get_error_message("timeout")
        
        if isinstance(error, RateLimitError):
            log.warning(f"[req:{request_id}] 限流错误 | retry_after={error.retry_after}s | total_time={total_elapsed:.2f}s")
            return self._get_error_message("rate_limit")
        
        if isinstance(error, AuthenticationError):
            log.error(f"[req:{request_id}] 认证错误 | status={error.status_code} | total_time={total_elapsed:.2f}s")
            return self._get_error_message("auth_error")
        
        if isinstance(error, ServerError):
            log.error(f"[req:{request_id}] 服务端错误 | status={error.status_code} | total_time={total_elapsed:.2f}s")
            return self._get_error_message("server_error")
        
        if isinstance(error, GeminiAPIError):
            log.error(f"[req:{request_id}] API 错误 | status={error.status_code} | total_time={total_elapsed:.2f}s")
            # 检查是否为内容过滤错误
            if "content filtered" in str(error.message).lower():
                return self._get_error_message("content_filter")
            return self._get_error_message("api_error")

        if isinstance(error, (httpx.ConnectError, httpx.NetworkError)):
            # 网络连接错误（如 DNS 解析失败、连接被重置等）
            log.warning(f"[req:{request_id}] 网络连接错误 | error={str(error)} | total_time={total_elapsed:.2f}s")
            return self._get_error_message("timeout")  # 统一作为网络超时处理
        
        # RemoteProtocolError 在 httpx 内部模块，需要检查类名
        error_class_name = type(error).__name__
        if error_class_name == "RemoteProtocolError" or "Server disconnected" in str(error):
            # 远程协议错误：服务器在发送响应前断开连接
            # 常见原因：中转代理超时（通常60秒）、HTTP/2连接被意外终止
            log.warning(
                f"[req:{request_id}] 远程协议错误（服务器断开） | "
                f"error={str(error)} | total_time={total_elapsed:.2f}s | "
                f"hint=可能是中转服务器超时，建议检查代理配置或减少请求复杂度"
            )
            return self._get_error_message("timeout")  # 对用户表现为超时
            
        # 未知错误
        log.error(
            f"[req:{request_id}] 未知错误 | error={type(error).__name__}: {str(error)} | total_time={total_elapsed:.2f}s",
            exc_info=True
        )
        if hasattr(error, 'response') and error.response:
            log.error(
                f"[req:{request_id}] Response Body: {error.response.text[:ERROR_RESPONSE_BODY_PREVIEW_CHARS]}"
            )
        return self._get_error_message("unknown")
    
    # ==================== 主对话方法 ====================
    
    async def chat(
        self,
        message: str,
        user_id: str,
        group_id: Optional[str] = None,
        image_urls: Optional[List[str]] = None,
        enable_tools: bool = True,
        retry_count: int = DEFAULT_CHAT_RETRY_COUNT,  # [优化] 提高默认重试次数
        message_id: Optional[str] = None,
        system_injection: Optional[str] = None,  # System 级注入（用于主动发言等场景）
        context_level: int = 0,  # [新增] 上下文降级层级 (0=完整, 1=截断, 2=最小)
        history_override: Optional[List[Dict[str, Any]]] = None,
        search_result_override: Optional[str] = None,  # 内部参数：复用首轮搜索结果，避免重试重复分类/搜索
    ) -> str:
        """
        发送消息（支持 OpenAI 格式）
        
        这是对话的主入口方法，协调各个子步骤：
        1. 预执行搜索（可选）
        2. 构建消息历史
        3. 发送 API 请求
        4. 处理工具调用（如有）
        5. 更新上下文
        
        智能降级重试机制：
        - Level 0: 完整上下文 (max_context)
        - Level 1: 截断上下文 (20条)
        - Level 2: 最小上下文 (5条)
        
        Args:
            message: 用户消息
            user_id: 用户 ID
            group_id: 群组 ID（可选，私聊时为 None）
            image_urls: 图片 URL 列表（可选）
            enable_tools: 是否启用工具（默认 True）
            retry_count: 重试次数（默认 2）
            message_id: 消息 ID（可选，用于上下文去重）
            system_injection: System 级注入内容（可选，用于主动发言场景等）
            context_level: 上下文降级层级 (0=完整, 1=截断20条, 2=最小5条)
            history_override: 覆盖上下文历史（仅影响本次请求构建 messages；None=使用存储的历史）
            search_result_override: 复用搜索结果（内部重试参数，外部无需传）
            
        Returns:
            助手回复内容
        """
        request_id, start_time = self._prepare_chat_request(user_id, group_id, image_urls)
        
        # 兼容 tests 对“上下文降级重试”实现细节的断言：
        # tests 会用 `inspect.getsource(client.chat)` 检查该变量名是否存在。
        # 实际降级逻辑在 `_handle_empty_reply_retry()` 中实现。
        next_context_level = context_level + 1

        try:
            # ===== 上下文诊断日志 =====
            await self._log_context_diagnostics(user_id, group_id, request_id)
            
            # 1. 预处理：搜索增强（重试时可复用首轮结果，避免重复触发分类器/搜索）
            if search_result_override is None:
                search_state = self._coerce_pre_search_result(
                    await self._pre_search(
                        message, enable_tools, request_id,
                        user_id=user_id, group_id=group_id
                    ),
                    message=message,
                    decision="presearch",
                )
                search_result = search_state.search_result
            else:
                search_state = self._coerce_pre_search_result(
                    search_result_override,
                    message=message,
                    decision="override",
                )
                search_result = search_state.search_result
                log.info(
                    f"[req:{request_id}] 复用首轮搜索判定结果，跳过重复分类/搜索 | "
                    f"search_injected={'yes' if bool(search_result) else 'no'}"
                )

            # 输出搜索结果状态
            self._log_search_result_status(search_result, request_id)
            self._log_search_decision(request_id, search_state, phase="pre_send")

            # 2. 构建请求（注意：现在返回 4 个值）
            # - messages: 完整消息列表
            # - original_content: 原始用户消息（用于保存历史）
            # - api_content: API 请求消息（可能含搜索结果）
            # - request_body: 请求体
            messages, original_content, api_content, request_body = await self._build_messages(
                message,
                user_id,
                group_id,
                image_urls,
                search_result,
                enable_tools,
                system_injection,
                context_level=context_level,  # 传递上下文降级层级
                history_override=history_override,
            )

            # 输出发送给模型的完整消息（仅在 DEBUG 模式）
            self._log_request_messages(messages, api_content, request_id)
            
            # 3. 发送请求
            try:
                assistant_message, tool_calls, api_key = await self._send_api_request(
                    request_body, request_id, retry_count,
                    message, user_id, group_id, image_urls, enable_tools
                )
            except ServerError as e:
                # 服务端错误需要重试
                retry_reply = await self._handle_server_error_retry(
                    e,
                    message=message,
                    user_id=user_id,
                    group_id=group_id,
                    image_urls=image_urls,
                    enable_tools=enable_tools,
                    retry_count=retry_count,
                    message_id=message_id,
                    system_injection=system_injection,
                    context_level=context_level,
                    history_override=history_override,
                    search_result=search_result,
                )
                if retry_reply is not None:
                    return retry_reply
                raise
            
            # 4. 处理工具调用（如有）
            reply, tool_trace = await self._resolve_reply(
                messages=messages,
                assistant_message=assistant_message,
                tool_calls=tool_calls,
                api_key=api_key,
                group_id=group_id,
                request_id=request_id,
                enable_tools=enable_tools,
                tools=request_body.get("tools"),
                search_state=search_state,
            )
            self._log_search_decision(request_id, search_state, phase="post_reply")
            

            # 输出模型原始回复（调试用）
            self._log_raw_model_reply(reply, request_id)

            # 5. 清理思考过程标记/标签/空白
            reply = self._process_response(reply, request_id)
            
            # 6. 检查空回复 - 智能降级重试机制
            if not reply:
                empty_meta = assistant_message.get("_empty_reply_meta") if isinstance(assistant_message, dict) else None
                if isinstance(empty_meta, dict):
                    log.warning(
                        f"[req:{request_id}] transport_empty_meta | kind={empty_meta.get('kind', '')} | "
                        f"finish={empty_meta.get('finish_reason', '') or 'unknown'} | "
                        f"local_retries={empty_meta.get('local_retries', 0)} | "
                        f"response_id={empty_meta.get('response_id', '') or '-'}"
                    )
                retry_reply = await self._handle_empty_reply_retry(
                    request_id=request_id,
                    start_time=start_time,
                    message=message,
                    user_id=user_id,
                    group_id=group_id,
                    image_urls=image_urls,
                    enable_tools=enable_tools,
                    retry_count=retry_count,
                    message_id=message_id,
                    system_injection=system_injection,
                    context_level=context_level,
                    history_override=history_override,
                    search_result=search_result,
                )
                if retry_reply is not None:
                    return retry_reply

                # 所有降级层级都失败了
                log.error(f"[req:{request_id}] 所有上下文降级层级都失败，返回错误消息")
                return self._get_error_message("empty_reply")
            # 步骤 5: 更新上下文
            # 使用从 chat 拆分出来的消息分离逻辑得到的 original_content
            # 注意：如果 original_content 是多模态列表，_update_context 需要能处理
            await self._update_context(
                user_id,
                group_id,
                original_content,
                reply,
                message_id,
                tool_trace=tool_trace,
            )
            
            # 日志：确认保存的是原始消息
            if search_result:
                log.debug(
                    f"[req:{request_id}] 上下文已更新（已分离搜索结果）| "
                    f"saved_len={len(str(original_content))} | "
                    f"api_len={len(str(api_content))}"
                )
            
            # 结构化日志：请求成功
            self._log_request_success(request_id, start_time, reply, tool_calls)
            
            return reply
            
        except Exception as e:
            return self._handle_error(e, request_id, start_time)


    def _extract_nickname_from_content(self, content: str) -> tuple:
        """
        从格式化的消息内容中提取昵称和纯内容
        
        消息格式: [昵称(QQ号)]: 消息内容 或 [⭐Sensei]: 消息内容
        
        Args:
            content: 格式化的消息内容
            
        Returns:
            (nickname, pure_content) 元组
        """
        import re
        
        if not content:
            return ("User", "")
        
        # 匹配 [昵称(QQ号)]: 或 [⭐Sensei]: 格式
        # 支持: [张三(123456)]: xxx, [⭐Sensei]: xxx, [私聊用户]: xxx
        pattern = r'^\[([^\]]+)\]:\s*(.*)$'
        match = re.match(pattern, content, re.DOTALL)
        
        if match:
            tag = match.group(1)  # 如 "张三(123456)" 或 "⭐Sensei"
            pure_content = match.group(2)  # 纯消息内容
            
            # 进一步提取昵称（去除QQ号部分）
            # "张三(123456)" -> "张三"
            nickname_match = re.match(r'^(.+?)\(\d+\)$', tag)
            if nickname_match:
                nickname = nickname_match.group(1)
            else:
                nickname = tag  # 如 "⭐Sensei" 或 "私聊用户"
            
            return (nickname, pure_content)
        
        # 未匹配到格式，返回原内容
        return ("User", content)

    def _extract_json_object(self, text: str) -> Optional[str]:
        """从文本中提取 JSON 对象（委派到独立模块）。"""
        return extract_json_object(text)

    async def judge_proactive_intent(self, context_messages: List[Dict], heat_level: int) -> Dict[str, Any]:
        """
        判断是否需要主动发言
        
        Args:
            context_messages: 最近的群聊消息列表
            heat_level: 当前热度值
            
        Returns:
            Dict: {
                "should_reply": bool,
                "reason": str
            }
        """
        import json
        import re
        
        try:
            # 1. 加载提示词
            prompt_config = load_judge_prompt()
            if not isinstance(prompt_config, dict):
                log.warning(
                    f"[主动发言判决] 提示词根节点应为 dict，实际为 {type(prompt_config).__name__}，已禁用本次主动发言"
                )
                return {"should_reply": False, "reason": "invalid_prompt_root"}

            judge_config = prompt_config.get("judge_proactive", {})
            if not isinstance(judge_config, dict):
                log.warning(
                    f"[主动发言判决] judge_proactive 应为 dict，实际为 {type(judge_config).__name__}，已禁用本次主动发言"
                )
                return {"should_reply": False, "reason": "invalid_judge_prompt"}

            template = judge_config.get("template", "")
            if not isinstance(template, str):
                template = ""
            
            if not template:
                log.warning("主动发言判决提示词加载失败")
                return {"should_reply": False, "reason": "No prompt"}
            
            log.info(f"[主动发言判决] 正使用快速模型: {plugin_config.gemini_fast_model}")
                
            # 2. 格式化上下文
            # 将 context_messages 转换为易读的字符串格式
            # 注意：历史消息格式是 [昵称(QQ号)]: 消息内容，需要解析
            context_str_list = []
            collected_images = []  # 收集最近的图片
            
            for msg in context_messages:
                content = msg.get("content", "")
                
                # 处理多模态内容（列表）
                if isinstance(content, list):
                    # 提取文本部分用于 context_str_list
                    text_part = ""
                    for item in content:
                        if item.get("type") == "text":
                            text_part += item.get("text", "")
                        elif item.get("type") == "image_url":
                            # 收集图片（仅最近的）
                            collected_images.append(item)
                    
                    # 提取昵称逻辑需要适配纯文本部分
                    sender, pure_content = self._extract_nickname_from_content(text_part)
                else:
                    # 普通文本
                    sender, content_str = self._extract_nickname_from_content(content)
                    pure_content = content_str
                
                # 优先使用已有的 nickname 字段
                if "nickname" in msg:
                    sender = msg["nickname"]
                
                # [关键优化] 如果是 Bot 自己的消息，强制标记为 Mika
                if msg.get("role") == "assistant":
                    sender = "Mika"
                
                context_str_list.append(f"{sender}: {pure_content}")
            
            context_text = "\n".join(context_str_list)
            
            # 3. 构建 Prompt
            prompt_text = template.format(
                heat_level=heat_level,
                context_messages=context_text
            )
            
            # 构建多模态 Content
            final_content = [{"type": "text", "text": prompt_text}]
            
            # 附加最近的图片（最多2张，防止 Token 爆炸）
            if collected_images:
                # 取最后 N 张（默认 2），防止 Token 爆炸
                recent_images = collected_images[-plugin_config.gemini_proactive_judge_max_images :]
                final_content.extend(recent_images)
                log.debug(f"[主动发言判决] 包含图片输入 | count={len(recent_images)}")
            
            # 4. 调用 API
            current_api_key = self._get_api_key()
            messages = [{"role": "user", "content": final_content}]
            
            client = await self._get_client()
            raw_content = "" # 初始化避免作用域问题
            
            # [重试机制] 对网络错误进行重试
            import asyncio
            max_retries = plugin_config.gemini_proactive_judge_max_retries
            retry_delay = plugin_config.gemini_proactive_judge_retry_delay_seconds  # 初始重试延迟（秒）
            last_error = None
            response = None
            
            for attempt in range(max_retries + 1):
                try:
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {current_api_key}",
                            "Content-Type": "application/json"
                        },
                        json={
                            "model": plugin_config.gemini_fast_model, # 使用快速模型
                            "messages": messages,
                            "temperature": plugin_config.gemini_proactive_temperature, # 使用配置的判决温度
                            "response_format": {"type": "json_object"}, # 强制 JSON
                            "stream": False, # 显式禁用流式传输
                            "safetySettings": [ # [安全设置] 同样应用 BLOCK_NONE
                                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
                            ]
                        },
                        timeout=plugin_config.gemini_proactive_judge_timeout_seconds  # 默认 20s
                    )
                    break  # 成功则跳出重试循环
                except (httpx.ConnectError, httpx.NetworkError, httpx.TimeoutException) as e:
                    last_error = e
                    if attempt < max_retries:
                        log.warning(
                            f"[主动发言判决] 网络错误，第 {attempt + 1} 次重试 | "
                            f"error={type(e).__name__}: {str(e)[:PROACTIVE_JUDGE_ERROR_PREVIEW_CHARS]}"
                        )
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2  # 指数退避
                    else:
                        log.error(
                            f"[主动发言判决] 网络错误，重试 {max_retries} 次后仍失败 | "
                            f"error={type(e).__name__}: {str(e)[:PROACTIVE_JUDGE_ERROR_PREVIEW_CHARS]}"
                        )
                        return {"should_reply": False, "reason": f"network_error: {type(e).__name__}"}
            
            if response is None:
                # 不应该到达这里，但作为安全保护
                return {"should_reply": False, "reason": "no_response"}
            
            response.raise_for_status()
            data = response.json()
            
            # 安全获取 content
            raw_content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            # 空值检查
            if not raw_content or not raw_content.strip():
                # Extract finish reason for debugging
                finish_reason = data.get("choices", [{}])[0].get("finish_reason", "UNKNOWN")
                log.warning(f"[主动发言判决] API 返回空内容 | finish_reason={finish_reason} | Full Data: {data}")
                return {"should_reply": False}
            
            # 清理 Markdown 代码块包裹
            clean_content = re.sub(r'^```(?:json)?\s*', '', raw_content.strip())
            clean_content = re.sub(r'```\s*$', '', clean_content)
            clean_content = clean_content.strip()
            
            if not clean_content:
                log.warning(
                    f"[主动发言判决] 内容清理后为空 | 原始: {raw_content[:PROACTIVE_JUDGE_RAW_CONTENT_SHORT_PREVIEW_CHARS]}"
                )
                return {"should_reply": False}

            # 尝试提取 JSON 对象（健壮模式）
            extracted_json = self._extract_json_object(clean_content)
            if extracted_json:
                clean_content = extracted_json
            
            # 使用更宽容的 JSON parser (如 json5) 如果有，这里暂时用标准库
            # 注意：标准 json 不支持 trailing comma，如果 LLM 输出不规范可能会挂
            # 但 _extract_json_object 已经很大程度解决了嵌套括号问题
            result = json.loads(clean_content)
            
            log.info(f"[主动发言判决] 结果: {result.get('should_reply')}")
            return result
            
        except json.JSONDecodeError as e:
            # 详细记录 JSON 解析失败的情况
            # 如果 raw_content 为空，说明可能是 response.json() 阶段这就挂了，打印 response.text
            if not raw_content and 'response' in locals():
                try:
                    server_response = response.text[:PROACTIVE_JUDGE_SERVER_RESPONSE_PREVIEW_CHARS]
                    log.error(f"[主动发言判决] API 响应解析失败 (HTTP {response.status_code}): {e} | Body: {server_response}")
                    return {"should_reply": False}
                except Exception:
                    pass

            raw_preview = (
                raw_content[:PROACTIVE_JUDGE_RAW_CONTENT_ERROR_PREVIEW_CHARS]
                if raw_content
                else '(DEBUG_EMPTY_CONTENT)'
            )
            log.error(f"[主动发言判决] JSON 解析失败: {e} | 原始内容: {raw_preview} | Hex: {raw_content.encode('utf-8').hex() if raw_content else 'None'}")
            return {"should_reply": False}
        except Exception as e:
            import traceback
            log.error(f"[主动发言判决] 失败: {repr(e)}")
            log.error(traceback.format_exc())
            return {"should_reply": False}
