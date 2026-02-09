"""Gemini Chat 插件配置模块。

提供插件配置的定义和验证，支持：
- API Key 配置与占位符检测
- 模型参数验证（温度范围等）
- HTTP/网络参数配置
- 多种触发规则配置

配置由宿主适配层在启动时注入到 mika_chat_core.runtime。
"""
from pydantic import BaseModel, field_validator, model_validator
from typing import Any, Dict, List, Optional
from pathlib import Path
import json
import os
import re


# ==================== Gemini API Key 占位符检测（仅用于 gemini_api_key / gemini_api_key_list） ====================
# 说明：
# - 只做「等值匹配」或「整串(fullmatch)匹配」，避免把真实 key 的子串误判为占位符。
# - 必须在 strip() + lower() 归一化后进行匹配。
_GEMINI_API_KEY_PLACEHOLDER_LITERALS = frozenset(
    {
        # 常见占位符
        "xxx",
        "your-api-key",
        "your_api_key",
        "your api key",
        "apikey",
        "api-key",
        "api_key",
        "api key",
        "api_key_here",
        "api-key-here",
        "placeholder",
        "test_key",
        "testkey",
        "changeme",
        "change-me",
        "replace_me",
        "replace-me",
    }
)

_GEMINI_API_KEY_PLACEHOLDER_FULLMATCH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^x{3,}$", re.IGNORECASE),
    re.compile(r"^<.*>$"),
)


def _is_gemini_api_key_placeholder(raw_value: str) -> bool:
    normalized = raw_value.strip().lower()
    if normalized in _GEMINI_API_KEY_PLACEHOLDER_LITERALS:
        return True
    return any(p.fullmatch(normalized) is not None for p in _GEMINI_API_KEY_PLACEHOLDER_FULLMATCH_PATTERNS)


def _get_project_relative_path(subpath: str) -> str:
    """获取项目相对路径"""
    project_root = Path(__file__).parent.parent.parent.parent
    return str(project_root / subpath)



class ConfigValidationError(Exception):
    """配置验证错误"""
    pass


class Config(BaseModel):
    """Gemini 插件配置"""
    
    # API 配置
    gemini_api_key: str = ""
    gemini_api_key_list: List[str] = []
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    gemini_model: str = "gemini-3-pro-high" # 主模型 (对应列表中的 Gemini 3 Pro (High))
    gemini_fast_model: str = "gemini-2.5-flash-lite" # 快速模型 (对应列表中的 Gemini 2.5 Flash Lite)
    # ===== 新一代 Provider 单一配置入口（兼容旧 GEMINI_* 读取） =====
    llm_provider: str = "openai_compat"  # openai_compat | anthropic | google_genai
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_api_key_list: List[str] = []
    llm_model: str = ""
    llm_fast_model: str = ""
    llm_extra_headers_json: str = ""
    # 搜索 provider 单一入口（兼容旧 serper_api_key）
    search_provider: str = "serper"  # serper | tavily
    search_api_key: str = ""
    search_extra_headers_json: str = ""

    # HTTP / 网络参数
    # 注意：这些参数只作为“默认值”，不改变现有行为（默认与原硬编码一致）。
    gemini_http_client_timeout_seconds: float = 120.0
    gemini_api_key_default_cooldown_seconds: float = 60.0
    
    # 模型参数
    gemini_temperature: float = 1.0 # 主对话温度
    gemini_proactive_temperature: float = 0.5 # 主动发言判决温度
    
    # 启动时是否验证 API 连接
    gemini_validate_on_startup: bool = True
    # /metrics 是否支持 Prometheus 文本导出
    gemini_metrics_prometheus_enabled: bool = True
    # /health 是否启用主动 API 连通性探测（默认关闭，避免额外成本）
    gemini_health_check_api_probe_enabled: bool = False
    # 主动探测超时（秒）
    gemini_health_check_api_probe_timeout_seconds: float = 3.0
    # 主动探测缓存 TTL（秒）
    gemini_health_check_api_probe_ttl_seconds: int = 30
    # 上下文 trace 日志（采样）
    gemini_context_trace_enabled: bool = False
    gemini_context_trace_sample_rate: float = 1.0
    
    @field_validator('gemini_temperature', 'gemini_proactive_temperature')
    @classmethod
    def validate_temperature(cls, v: float) -> float:
        """验证温度参数范围（0.0-2.0）"""
        if v < 0.0 or v > 2.0:
            raise ValueError(f"温度参数必须在 0.0 到 2.0 之间，当前值: {v}")
        return v

    @field_validator("gemini_health_check_api_probe_timeout_seconds")
    @classmethod
    def validate_health_probe_timeout(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("gemini_health_check_api_probe_timeout_seconds 必须大于 0")
        return v

    @field_validator("gemini_health_check_api_probe_ttl_seconds")
    @classmethod
    def validate_health_probe_ttl(cls, v: int) -> int:
        if v < 1:
            raise ValueError("gemini_health_check_api_probe_ttl_seconds 必须大于等于 1")
        return v

    @field_validator(
        "gemini_active_reply_probability",
        "gemini_context_trace_sample_rate",
        "gemini_history_inline_threshold",
        "gemini_history_two_stage_threshold",
    )
    @classmethod
    def validate_probability_ratio(cls, v: float) -> float:
        if v < 0 or v > 1:
            raise ValueError("概率参数必须在 0.0 到 1.0 之间")
        return v

    @field_validator("gemini_quote_image_caption_timeout_seconds")
    @classmethod
    def validate_quote_caption_timeout(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("gemini_quote_image_caption_timeout_seconds 必须大于 0")
        return v
    
    @field_validator('gemini_api_key')
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        """验证 API Key 格式"""
        if not v:
            return v  # 允许为空，因为可能使用 api_key_list

        # 先去除首尾空白（允许用户在 env 里不小心写了空格）
        v = v.strip()
        
        # 检查是否为占位符值
        if _is_gemini_api_key_placeholder(v):
            raise ValueError("API Key 看起来是占位符，请配置真实的 API Key")
        
        # Gemini API Key 通常以 'AI' 开头，长度约 39 字符
        # 测试/中转场景下 key 可能更短；这里保持最小长度校验但放宽至 25。
        if len(v) < 25:
            raise ValueError("API Key 长度不符合要求")
        
        # 检查是否包含空格（中间不允许有任何空白字符）
        if re.search(r'\s', v):
            raise ValueError("API Key 不应包含空格")

        return v
    
    @field_validator('gemini_api_key_list')
    @classmethod
    def validate_api_key_list(cls, v: List[str]) -> List[str]:
        """验证 API Key 列表"""
        validated_keys = []
        for i, key in enumerate(v):
            key = key.strip()
            if not key:
                continue  # 跳过空字符串

            if _is_gemini_api_key_placeholder(key):
                raise ValueError(f"API Key #{i+1} 看起来是占位符，请配置真实的 API Key")

            if len(key) < 25:
                raise ValueError(f"API Key #{i+1} 长度过短（当前 {len(key)} 字符）")
            if re.search(r'\s', key):
                raise ValueError(f"API Key #{i+1} 不应包含空格")
            validated_keys.append(key)
        return validated_keys
    
    @field_validator('gemini_base_url')
    @classmethod
    def validate_base_url(cls, v: str) -> str:
        """验证 Base URL 格式"""
        if not v:
            raise ValueError("Base URL 不能为空")
        if not v.startswith(('http://', 'https://')):
            raise ValueError("Base URL 必须以 http:// 或 https:// 开头")
        return v.rstrip('/')  # 统一去除尾部斜杠

    @field_validator("gemini_context_mode")
    @classmethod
    def validate_context_mode(cls, v: str) -> str:
        """验证上下文模式。"""
        value = (v or "").strip().lower()
        if value not in {"legacy", "structured"}:
            raise ValueError("gemini_context_mode 仅支持 legacy 或 structured")
        return value
    
    @field_validator('gemini_master_id')
    @classmethod
    def validate_master_id(cls, v: int) -> int:
        """验证 master_id 必须为正整数"""
        if v <= 0:
            raise ValueError(
                "GEMINI_MASTER_ID 未配置或无效，请在 .env / .env.prod 中设置，例如：GEMINI_MASTER_ID=123456789"
            )
        return v

    @field_validator("llm_provider")
    @classmethod
    def validate_llm_provider(cls, v: str) -> str:
        value = (v or "").strip().lower()
        allowed = {"openai_compat", "anthropic", "google_genai"}
        if value not in allowed:
            raise ValueError("llm_provider 仅支持 openai_compat / anthropic / google_genai")
        return value

    @field_validator("search_provider")
    @classmethod
    def validate_search_provider(cls, v: str) -> str:
        value = (v or "").strip().lower()
        allowed = {"serper", "tavily"}
        if value not in allowed:
            raise ValueError("search_provider 仅支持 serper / tavily")
        return value

    @field_validator("llm_base_url")
    @classmethod
    def validate_llm_base_url(cls, v: str) -> str:
        value = (v or "").strip()
        if not value:
            return ""
        if not value.startswith(("http://", "https://")):
            raise ValueError("llm_base_url 必须以 http:// 或 https:// 开头")
        return value.rstrip("/")

    @field_validator("llm_api_key")
    @classmethod
    def validate_llm_api_key(cls, v: str) -> str:
        value = (v or "").strip()
        if not value:
            return ""
        if _is_gemini_api_key_placeholder(value):
            raise ValueError("llm_api_key 看起来是占位符，请配置真实 key")
        if re.search(r"\s", value):
            raise ValueError("llm_api_key 不应包含空白字符")
        if len(value) < 10:
            raise ValueError("llm_api_key 长度过短")
        return value

    @field_validator("llm_api_key_list")
    @classmethod
    def validate_llm_api_key_list(cls, v: List[str]) -> List[str]:
        cleaned: List[str] = []
        for index, key in enumerate(v or []):
            item = str(key or "").strip()
            if not item:
                continue
            if _is_gemini_api_key_placeholder(item):
                raise ValueError(f"llm_api_key_list 第 {index + 1} 项看起来是占位符")
            if re.search(r"\s", item):
                raise ValueError(f"llm_api_key_list 第 {index + 1} 项包含空白字符")
            if len(item) < 10:
                raise ValueError(f"llm_api_key_list 第 {index + 1} 项长度过短")
            cleaned.append(item)
        return cleaned

    @field_validator("llm_extra_headers_json", "search_extra_headers_json")
    @classmethod
    def validate_extra_headers_json(cls, v: str) -> str:
        value = (v or "").strip()
        if not value:
            return ""
        try:
            parsed = json.loads(value)
        except Exception as exc:
            raise ValueError(f"headers JSON 解析失败: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("headers JSON 必须是对象（key/value）")
        for key, item in parsed.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("headers JSON 的键必须是非空字符串")
            if not isinstance(item, (str, int, float, bool)):
                raise ValueError("headers JSON 的值必须是标量（str/int/float/bool）")
        return value
    
    @model_validator(mode='after')
    def validate_and_set_defaults(self) -> 'Config':
        """验证配置并设置默认值"""
        llm_api_key = self.llm_api_key.strip()
        llm_api_key_list = [item for item in self.llm_api_key_list if item]

        # 兼容旧配置：若新字段未配置，则自动映射旧 GEMINI_* 字段
        if not llm_api_key and not llm_api_key_list:
            llm_api_key = self.gemini_api_key.strip()
            llm_api_key_list = [item for item in self.gemini_api_key_list if item]
            object.__setattr__(self, "llm_api_key", llm_api_key)
            object.__setattr__(self, "llm_api_key_list", llm_api_key_list)

        if not (self.llm_base_url or "").strip() and (self.gemini_base_url or "").strip():
            object.__setattr__(self, "llm_base_url", str(self.gemini_base_url).rstrip("/"))
        if not (self.llm_model or "").strip() and (self.gemini_model or "").strip():
            object.__setattr__(self, "llm_model", str(self.gemini_model).strip())
        if not (self.llm_fast_model or "").strip() and (self.gemini_fast_model or "").strip():
            object.__setattr__(self, "llm_fast_model", str(self.gemini_fast_model).strip())

        if not (self.search_api_key or "").strip() and (self.serper_api_key or "").strip():
            object.__setattr__(self, "search_api_key", str(self.serper_api_key).strip())
            if not (self.search_provider or "").strip():
                object.__setattr__(self, "search_provider", "serper")

        # 确保至少配置了一个 API Key
        if not self.llm_api_key and not self.llm_api_key_list and not self.gemini_api_key and not self.gemini_api_key_list:
            raise ValueError(
                "必须至少配置 GEMINI_API_KEY 或 GEMINI_API_KEY_LIST 其中的至少一个，例如："
                "GEMINI_API_KEY=\"你的Key\" 或 GEMINI_API_KEY_LIST=[\"key1\", \"key2\"]"
            )
        
        # 如果语义模型路径未配置，使用项目相对路径作为默认值
        if not self.gemini_semantic_model:
            object.__setattr__(self, 'gemini_semantic_model',
                              _get_project_relative_path("models/semantic_model"))
        
        # 当内置搜索或外置搜索功能可能启用时，验证 serper_api_key
        # 注意：gemini_enable_builtin_search 是内置搜索开关
        # 外置搜索默认启用，需要 serper_api_key
        if self.serper_api_key:
            # 验证 serper_api_key 格式
            key = self.serper_api_key.strip()
            placeholder_patterns = ['your_api_key', 'xxx', 'placeholder', 'test_key', 'api_key_here']
            if any(p in key.lower() for p in placeholder_patterns):
                raise ValueError("Serper API Key 看起来是占位符，请配置真实的 API Key")
            if len(key) < 10:
                raise ValueError("Serper API Key 长度不符合要求")
        
        return self
    
    def get_effective_api_keys(self) -> List[str]:
        """获取所有有效的 API Key 列表"""
        keys = []
        if self.llm_api_key:
            keys.append(self.llm_api_key)
        keys.extend(self.llm_api_key_list)
        if not keys:
            if self.gemini_api_key:
                keys.append(self.gemini_api_key)
            keys.extend(self.gemini_api_key_list)
        return list(set(keys))  # 去重

    def get_llm_config(self) -> Dict[str, Any]:
        """获取当前生效的 LLM provider 配置。"""
        provider = (self.llm_provider or "openai_compat").strip().lower()
        base_url = (self.llm_base_url or self.gemini_base_url or "").strip().rstrip("/")
        model = (self.llm_model or self.gemini_model or "").strip()
        fast_model = (self.llm_fast_model or self.gemini_fast_model or "").strip()
        api_keys = self.get_effective_api_keys()
        extra_headers: Dict[str, str] = {}
        if self.llm_extra_headers_json.strip():
            parsed = json.loads(self.llm_extra_headers_json)
            extra_headers = {str(key): str(value) for key, value in parsed.items()}
        return {
            "provider": provider,
            "base_url": base_url,
            "model": model,
            "fast_model": fast_model,
            "api_keys": api_keys,
            "extra_headers": extra_headers,
        }

    def get_search_provider_config(self) -> Dict[str, Any]:
        """获取当前生效的 Search provider 配置。"""
        provider = (self.search_provider or "serper").strip().lower()
        api_key = (self.search_api_key or self.serper_api_key or "").strip()
        extra_headers: Dict[str, str] = {}
        if self.search_extra_headers_json.strip():
            parsed = json.loads(self.search_extra_headers_json)
            extra_headers = {str(key): str(value) for key, value in parsed.items()}
        return {
            "provider": provider,
            "api_key": api_key,
            "extra_headers": extra_headers,
        }

    # ==================== 配置分层访问器（P1） ====================
    def get_core_config(self) -> dict:
        """核心对话/网络配置（分层读取，不改变现有 env 键）。"""
        llm_cfg = self.get_llm_config()
        return {
            "provider": llm_cfg["provider"],
            "api_key": self.llm_api_key or self.gemini_api_key,
            "api_key_list": list(llm_cfg["api_keys"]),
            "base_url": llm_cfg["base_url"],
            "model": llm_cfg["model"],
            "fast_model": llm_cfg["fast_model"],
            "extra_headers": dict(llm_cfg["extra_headers"]),
            "max_context": self.gemini_max_context,
            "temperature": self.gemini_temperature,
            "http_timeout_seconds": self.gemini_http_client_timeout_seconds,
        }

    def get_search_config(self) -> dict:
        """搜索相关配置分层。"""
        provider_cfg = self.get_search_provider_config()
        return {
            "provider": provider_cfg["provider"],
            "api_key": provider_cfg["api_key"],
            "extra_headers": dict(provider_cfg["extra_headers"]),
            "cache_ttl_seconds": self.gemini_search_cache_ttl_seconds,
            "cache_max_size": self.gemini_search_cache_max_size,
            "classify_cache_ttl_seconds": self.gemini_search_classify_cache_ttl_seconds,
            "classify_cache_max_size": self.gemini_search_classify_cache_max_size,
            "llm_gate_enabled": self.gemini_search_llm_gate_enabled,
            "llm_gate_fallback_mode": self.gemini_search_llm_gate_fallback_mode,
            "allow_tool_refine": self.gemini_search_allow_tool_refine,
            "tool_refine_max_rounds": self.gemini_search_tool_refine_max_rounds,
        }

    def get_image_config(self) -> dict:
        """图片处理与缓存配置分层。"""
        return {
            "max_images": self.gemini_max_images,
            "require_keyword": self.gemini_image_require_keyword,
            "download_concurrency": self.gemini_image_download_concurrency,
            "cache_max_entries": self.gemini_image_cache_max_entries,
            "keywords": list(self.gemini_image_keywords),
        }

    def get_proactive_config(self) -> dict:
        """主动发言配置分层。"""
        return {
            "keywords": list(self.gemini_proactive_keywords),
            "rate": self.gemini_proactive_rate,
            "cooldown_seconds": self.gemini_proactive_cooldown,
            "cooldown_messages": self.gemini_proactive_cooldown_messages,
            "heat_threshold": self.gemini_heat_threshold,
            "ignore_len": self.gemini_proactive_ignore_len,
            "active_reply_ltm_enabled": self.gemini_active_reply_ltm_enabled,
            "active_reply_probability": self.gemini_active_reply_probability,
            "active_reply_whitelist": list(self.gemini_active_reply_whitelist),
        }

    def get_observability_config(self) -> dict:
        """可观测性配置分层。"""
        return {
            "prometheus_enabled": self.gemini_metrics_prometheus_enabled,
            "health_api_probe_enabled": self.gemini_health_check_api_probe_enabled,
            "health_api_probe_timeout_seconds": self.gemini_health_check_api_probe_timeout_seconds,
            "health_api_probe_ttl_seconds": self.gemini_health_check_api_probe_ttl_seconds,
            "context_trace_enabled": self.gemini_context_trace_enabled,
            "context_trace_sample_rate": self.gemini_context_trace_sample_rate,
        }
    
    # ==================== 用户标识配置 ====================
    gemini_master_id: int = 0              # Master 的 QQ 号
    gemini_master_name: str = "Sensei"     # Master 的称呼
    gemini_bot_display_name: str = "Mika"  # 机器人显示名称（用于转发消息等）
    
    # ==================== 提示词配置 ====================
    gemini_prompt_file: str = "system.yaml"  # 外部提示词文件名（prompts/目录下）
    gemini_system_prompt: str = ""           # 内置提示词（仅在文件为空时使用）
    
    # ==================== 上下文配置 ====================
    gemini_max_context: int = 40       # 最大上下文轮数
    gemini_history_count: int = 50     # 群历史消息查询数量
    # SQLiteContextStore 的 LRU 缓存条目数上限（越小越省内存，越大越高命中率）
    gemini_context_cache_max_size: int = 200
    # 上下文存储模式：legacy=历史兼容，structured=结构化内容（推荐）
    gemini_context_mode: str = "structured"
    # 上下文最大保留轮次（优先于按消息条数截断）
    gemini_context_max_turns: int = 30
    # 软 token 上限（估算），超过后会逐轮裁剪旧上下文
    gemini_context_max_tokens_soft: int = 12000
    # 是否启用摘要压缩（默认关闭，稳定优先）
    gemini_context_summary_enabled: bool = False
    # 多模态严格模式：清理不合法的历史多模态块，避免接口报错
    gemini_multimodal_strict: bool = True
    # 是否为引用消息中的图片注入简短说明（best-effort）
    gemini_quote_image_caption_enabled: bool = True
    # 引用图片说明模板（仅用于构造提示文本，不触发额外模型调用）
    gemini_quote_image_caption_prompt: str = "[引用图片共{count}张]"
    # 解析引用消息的 API 超时阈值（秒）
    gemini_quote_image_caption_timeout_seconds: float = 3.0

    # ==================== OneBot 兼容性配置 ====================
    # 离线消息同步依赖非标准 API（如 get_group_msg_history），默认关闭以提升兼容性
    gemini_offline_sync_enabled: bool = False
    
    # ==================== 触发配置 ====================
    gemini_reply_private: bool = True  # 是否响应私聊
    gemini_reply_at: bool = True       # 是否响应@消息
    gemini_group_whitelist: List[int] = []  # 群白名单（空=全部允许）
    
    # ==================== 主动发言配置 ====================
    gemini_proactive_keywords: List[str] = ["Mika", "未花",]  # 强触发关键词
    gemini_proactive_topics: List[str] = [  # 语义话题库 (扩充为短语以增强语义匹配)
        # 娱乐
        "玩游戏或讨论游戏相关话题",
        "抽卡或氪金相关的话题",
        # 美食 (Mika最爱)
        "关于甜点、蛋糕、零食的话题",
        "想吃东西或讨论美食",
        # 校园生活
        "作业、学习或课程相关",
        "考试成绩或挂科相关",
        # BA世界观
        "Blue Archive 蔚蓝档案游戏",
        # 科技与音乐
        "科技数码或电子产品",
        "听歌或音乐相关话题",
    ]
    gemini_proactive_rate: float = 0.2       # 触发概率 (0.0 - 1.0)
    gemini_proactive_cooldown: int = 30       # 冷却时间 (秒)
    gemini_proactive_cooldown_messages: int = 5  # 消息条数冷却 (上次主动发言后需要至少 N 条新消息)
    gemini_heat_threshold: int = 10           # 热度阈值 (消息数/分钟)
    gemini_proactive_ignore_len: int = 4     # 忽略短于此长度的消息

    # 主动发言判决（网络重试/超时）
    gemini_proactive_judge_timeout_seconds: float = 20.0
    gemini_proactive_judge_max_retries: int = 2
    gemini_proactive_judge_retry_delay_seconds: float = 1.0
    gemini_proactive_judge_max_images: int = 2
    # Active Reply（LTM 风格）门控
    gemini_active_reply_ltm_enabled: bool = True
    gemini_active_reply_probability: float = 1.0
    gemini_active_reply_whitelist: List[str] = []
    
    # ==================== 语义匹配配置 ====================
    # 是否启用语义匹配（sentence-transformers/torch）。关闭可显著降低内存占用。
    gemini_semantic_enabled: bool = True
    # 语义匹配后端：
    # - auto: 自动选择（优先 fastembed；若模型路径是本地目录则优先 sentence-transformers）
    # - fastembed: 使用 fastembed（更省内存，CPU 推理；首次会下载/缓存模型）
    # - sentence-transformers: 使用 sentence-transformers + torch（兼容本地目录模型）
    gemini_semantic_backend: str = "auto"
    gemini_semantic_model: str = ""          # 模型路径 (env: GEMINI_SEMANTIC_MODEL)
    # 可选：语义模型加载失败时的回退路径（通常用于本地目录模型）
    gemini_semantic_model_fallback: str = ""  # env: GEMINI_SEMANTIC_MODEL_FALLBACK
    # E5 系模型建议使用 query:/passage: 前缀；非 E5（如 multilingual MiniLM）通常不需要。
    gemini_semantic_use_e5_prefixes: bool = True  # env: GEMINI_SEMANTIC_USE_E5_PREFIXES
    # fastembed 的模型缓存目录（可选）。为空则使用 fastembed 默认缓存路径（通常在 ~/.cache）。
    gemini_fastembed_cache_dir: str = ""  # env: GEMINI_FASTEMBED_CACHE_DIR
    # fastembed 的本地模型目录（可选）。设置后将跳过在线下载，直接从该目录加载 ONNX 模型文件。
    gemini_fastembed_model_dir: str = ""  # env: GEMINI_FASTEMBED_MODEL_DIR
    gemini_semantic_threshold: float = 0.4   # 匹配阈值 (0.0 - 1.0)

    @field_validator("gemini_semantic_backend")
    @classmethod
    def validate_semantic_backend(cls, v: str) -> str:
        allowed = {"auto", "fastembed", "sentence-transformers", "sentence_transformers"}
        normalized = (v or "").strip().lower()
        if normalized not in allowed:
            raise ValueError(
                "gemini_semantic_backend 必须是 auto / fastembed / sentence-transformers"
            )
        # 兼容两种写法
        if normalized == "sentence-transformers":
            return "sentence_transformers"
        return normalized

    # ==================== 视觉与图片配置 ====================
    gemini_max_images: int = 10              # 单条消息最大处理图片数
    gemini_image_cache_max_gap: int = 10     # [已废弃] 由 lifecycle 强制覆盖为 max_context * 2
    gemini_image_require_keyword: bool = True  # 是否需要关键词触发缓存读取
    
    # ==================== 消息处理配置 ====================
    gemini_forward_threshold: int = 300      # 合并转发阈值 (字符数)
    # 长回复发送失败时，是否启用“渲染图片并发送”兜底
    gemini_long_reply_image_fallback_enabled: bool = True
    # 长回复渲染图片时最多处理的字符数（超出会截断）
    gemini_long_reply_image_max_chars: int = 12000
    # 长回复渲染图片最大宽度（像素）
    gemini_long_reply_image_max_width: int = 960
    # 长回复渲染图片字号
    gemini_long_reply_image_font_size: int = 24
    # 兼容保留：历史分片配置，当前主链路不再使用
    gemini_long_message_chunk_size: int = 800

    # 空回复本地收敛策略（传输层）
    # 在不重跑整条业务链路（分类/构建/上下文降级）的前提下，做有限次快速重试
    gemini_empty_reply_local_retries: int = 1
    gemini_empty_reply_local_retry_delay_seconds: float = 0.4
    # 传输层超时本地重试（仅针对 TimeoutException）
    gemini_transport_timeout_retries: int = 1
    gemini_transport_timeout_retry_delay_seconds: float = 0.6
    # 是否允许空回复触发业务级上下文降级重试（默认关闭，便于排障）
    gemini_empty_reply_context_degrade_enabled: bool = False
    gemini_empty_reply_context_degrade_max_level: int = 2

    # ==================== 搜索缓存配置 ====================
    gemini_search_cache_ttl_seconds: int = 60
    gemini_search_cache_max_size: int = 100

    # ==================== 外置搜索 P0 优化配置 ====================
    # 外置搜索触发的最低有效 query 长度（清洗后过短将跳过搜索）
    gemini_search_min_query_length: int = 4
    # 注入到 System 的搜索结果条数上限（过滤低质条目后截断）
    gemini_search_max_injection_results: int = 6

    # ==================== 外置搜索 LLM Gate 配置 ====================
    # 是否启用“全量 LLM 判定 gate”：低信号/本地时间过滤后，每条消息都先调用 LLM 判 needs_search
    gemini_search_llm_gate_enabled: bool = False
    # LLM 判定失败时回退策略：
    # - none: 不回退外搜
    # - strong_timeliness: 仅当命中强时效词时回退外搜
    gemini_search_llm_gate_fallback_mode: str = "strong_timeliness"
    # 分类请求参数（稳定性优先，默认 temperature=0）
    gemini_search_classify_temperature: float = 0.0
    gemini_search_classify_max_tokens: int = 256
    # 分类判定缓存（避免短时间内重复调用 LLM）
    gemini_search_classify_cache_ttl_seconds: int = 60
    gemini_search_classify_cache_max_size: int = 200
    # 预搜索命中后，是否允许模型再发起一次工具补搜
    gemini_search_allow_tool_refine: bool = True
    # 单轮对话最多允许补搜几次（仅对 web_search 生效）
    gemini_search_tool_refine_max_rounds: int = 1

    # ==================== 内置搜索配置 ====================
    gemini_enable_builtin_search: bool = False

    # ==================== 图片处理性能 ====================
    gemini_image_download_concurrency: int = 3
    gemini_image_cache_max_entries: int = 200
    gemini_image_keywords: List[str] = []

    # ==================== 历史图片上下文增强配置 ====================
    # 模式: off=关闭, inline=仅回注原图, two_stage=仅两阶段, hybrid=混合(推荐)
    gemini_history_image_mode: str = "hybrid"
    # 历史上下文快照是否保存多模态图片 part（默认关闭，改为文本占位）
    gemini_history_store_multimodal: bool = False
    # 单次请求直接回注的历史原图数量上限
    gemini_history_image_inline_max: int = 1
    # hybrid 模式下触发 inline 的最低置信度阈值
    gemini_history_inline_threshold: float = 0.85
    # 两阶段补图工具最多补几张
    gemini_history_image_two_stage_max: int = 2
    # 触发 two-stage 的最低置信度阈值
    gemini_history_two_stage_threshold: float = 0.5
    # 是否启用连续图片拼图
    gemini_history_image_enable_collage: bool = True
    # 新版开关：是否启用拼图（优先于 gemini_history_image_enable_collage）
    gemini_history_collage_enabled: bool = False
    # 拼图最多合成几张图片
    gemini_history_image_collage_max: int = 4
    # 拼图目标最大边长(px)，用于控制 token 成本
    gemini_history_image_collage_target_px: int = 768
    # 历史图片触发关键词（空则使用默认集合）
    gemini_history_image_trigger_keywords: List[str] = []

    # ==================== 工具调用安全控制 ====================
    gemini_tool_allowlist: List[str] = ["web_search", "search_group_history", "fetch_history_images"]
    gemini_tool_result_max_chars: int = 4000

    # ==================== 工具调用 Loop 配置 ====================
    # 单次对话允许模型触发工具调用的最大轮数（每轮可包含多个 tool_calls）
    gemini_tool_max_rounds: int = 5
    # 单个工具 handler 的超时时间（秒）
    gemini_tool_timeout_seconds: float = 20.0
    # 达到上限后是否强制模型停止使用工具并给出最终答复
    gemini_tool_force_final_on_max_rounds: bool = True

    # ==================== 主动发言策略 ====================
    gemini_proactive_keyword_cooldown: int = 5

    # ==================== 主动发言 Chatroom 模式 ====================
    # 借鉴 AstrBot：主动发言时将群聊记录拼成 transcript 注入，并清空上下文 contexts，减少“已读乱回”
    gemini_proactive_chatroom_enabled: bool = True
    gemini_proactive_chatroom_history_lines: int = 30
    
    # ==================== 外部服务配置 ====================
    serper_api_key: str = ""                 # Serper.dev API Key（Google 搜索）

    # ==================== 用户档案 LLM 抽取配置 ====================
    # 基础开关
    profile_extract_enabled: bool = True              # 是否启用 LLM 档案抽取（群聊）
    profile_extract_enable_private: bool = True       # 私聊是否启用
    
    # 模型配置（默认使用快速模型）
    profile_extract_model: str = ""                   # 空则使用 gemini_fast_model
    profile_extract_temperature: float = 0.0          # 抽取温度（建议 0，稳定输出）
    profile_extract_max_tokens: int = 1024            # 最大输出 token
    
    # 触发与限流
    profile_extract_min_chars: int = 6                # 最小消息长度（过短跳过）
    profile_extract_every_n_messages: int = 10        # 每 N 条消息触发一次兜底抽取
    profile_extract_cooldown_seconds: int = 300       # 每用户抽取冷却（秒）
    profile_extract_max_calls_per_minute: int = 5     # 全局每分钟最大调用次数
    profile_extract_per_user_queue_max: int = 3       # 每用户队列最大待处理任务数
    profile_extract_batch_window: int = 8             # 批量抽取输入窗口（最近 N 条该用户消息）

    # 内存与状态管理（长期运行防止无界增长）
    profile_extract_state_ttl_seconds: int = 7200     # per-user state 超过 TTL 未活跃则清理（秒）
    profile_extract_state_max_users: int = 1000       # 最多保留多少个用户 state（超过则淘汰最旧）
    
    # 合并阈值
    profile_extract_threshold_new_field: float = 0.6  # 新字段写入的最低置信度
    profile_extract_threshold_override_field: float = 0.85  # 覆盖旧值的最低置信度
    profile_extract_override_requires_repeat: bool = True   # 覆盖旧值需二次确认
    
    # 调试与审计
    profile_extract_log_payload: bool = False         # 是否记录 prompt/输出（注意隐私）
    profile_extract_store_audit_events: bool = True   # 是否写入审计表

    # ==================== 用户档案缓存 ====================
    gemini_user_profile_cache_max_size: int = 256


from .runtime import config_proxy as plugin_config
