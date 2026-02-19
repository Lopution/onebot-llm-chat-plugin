"""Mika Chat 插件配置模块。

提供插件配置的定义和验证，支持：
- API Key 配置与占位符检测
- 模型参数验证（温度范围等）
- HTTP/网络参数配置
- 多种触发规则配置

配置由宿主适配层在启动时注入到 mika_chat_core.runtime。
"""
from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from typing import Any, Dict, List, Optional, get_args, get_origin
from pathlib import Path
import json
import os
import re
from urllib.parse import urlparse


# ==================== LLM API Key 占位符检测（llm_api_key / llm_api_key_list） ====================
# 说明：
# - 只做「等值匹配」或「整串(fullmatch)匹配」，避免把真实 key 的子串误判为占位符。
# - 必须在 strip() + lower() 归一化后进行匹配。
_API_KEY_PLACEHOLDER_LITERALS = frozenset(
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

_API_KEY_PLACEHOLDER_FULLMATCH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^x{3,}$", re.IGNORECASE),
    re.compile(r"^<.*>$"),
)


def _is_api_key_placeholder(raw_value: str) -> bool:
    normalized = raw_value.strip().lower()
    if normalized in _API_KEY_PLACEHOLDER_LITERALS:
        return True
    return any(p.fullmatch(normalized) is not None for p in _API_KEY_PLACEHOLDER_FULLMATCH_PATTERNS)


def _get_project_relative_path(subpath: str) -> str:
    """获取项目相对路径"""
    project_root = Path(__file__).parent.parent.parent.parent
    return str(project_root / subpath)


def _is_local_ollama_base_url(url: str) -> bool:
    try:
        parsed = urlparse(str(url or "").strip())
        if parsed.scheme not in {"http", "https"}:
            return False
        host = str(parsed.hostname or "").lower()
        port = int(parsed.port or 0)
        return host in {"localhost", "127.0.0.1", "::1"} and port == 11434
    except Exception:
        return False


def _legacy_name(*parts: str) -> str:
    return "".join(parts)


_REMOVED_LEGACY_KEYS: tuple[tuple[str, str], ...] = (
    (_legacy_name("mika_", "api_key"), "llm_api_key"),
    (_legacy_name("mika_", "api_key_list"), "llm_api_key_list"),
    (_legacy_name("mika_", "base_url"), "llm_base_url"),
    (_legacy_name("mika_", "model"), "llm_model"),
    (_legacy_name("mika_", "fast_model"), "llm_fast_model"),
    (_legacy_name("serper_", "api_key"), "search_api_key"),
    (_legacy_name("mika_history_image_enable_", "collage"), "mika_history_collage_enabled"),
)

_REMOVED_LEGACY_ENV_KEYS: dict[str, str] = {
    "MIKA_API_KEY": "LLM_API_KEY",
    "MIKA_API_KEY_LIST": "LLM_API_KEY_LIST",
    "MIKA_BASE_URL": "LLM_BASE_URL",
    "MIKA_MODEL": "LLM_MODEL",
    "MIKA_FAST_MODEL": "LLM_FAST_MODEL",
    "SERPER_API_KEY": "SEARCH_API_KEY",
    "MIKA_HISTORY_IMAGE_ENABLE_COLLAGE": "MIKA_HISTORY_COLLAGE_ENABLED",
}



class ConfigValidationError(Exception):
    """配置验证错误"""
    pass


class Config(BaseModel):
    """Mika 插件配置"""

    model_config = ConfigDict(extra="forbid")
    
    # API 配置（单一入口）
    llm_provider: str = "openai_compat"  # openai_compat | anthropic | google_genai
    llm_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    llm_api_key: str = ""
    llm_api_key_list: List[str] = []
    llm_model: str = "gemini-3-pro-high"
    llm_fast_model: str = "gemini-2.5-flash-lite"
    # 多任务模型配置（为空时回退到 llm_fast_model -> llm_model）
    mika_task_filter_model: str = ""
    mika_task_summarizer_model: str = ""
    mika_task_memory_model: str = ""
    llm_extra_headers_json: str = ""
    # 搜索 provider 单一入口
    search_provider: str = "serper"  # serper | tavily
    search_api_key: str = ""
    search_extra_headers_json: str = ""
    # Core 运行模式（Stage C）：已收敛为 remote-only（HTTP Core Service）
    mika_core_runtime_mode: str = "remote"
    mika_core_remote_base_url: str = "http://127.0.0.1:8080"
    mika_core_remote_timeout_seconds: float = 60.0
    mika_core_service_token: str = ""

    # HTTP / 网络参数
    # 注意：这些参数只作为“默认值”，不改变现有行为（默认与原硬编码一致）。
    mika_http_client_timeout_seconds: float = 120.0
    llm_api_key_default_cooldown_seconds: float = 60.0
    
    # 模型参数
    mika_temperature: float = 1.0 # 主对话温度
    mika_proactive_temperature: float = 0.5 # 主动发言判决温度
    
    # 启动时是否验证 API 连接
    mika_validate_on_startup: bool = True
    # /metrics 是否支持 Prometheus 文本导出
    mika_metrics_prometheus_enabled: bool = True
    # /health 是否启用主动 API 连通性探测（默认关闭，避免额外成本）
    mika_health_check_api_probe_enabled: bool = False
    # 主动探测超时（秒）
    mika_health_check_api_probe_timeout_seconds: float = 3.0
    # 主动探测缓存 TTL（秒）
    mika_health_check_api_probe_ttl_seconds: int = 30
    # 上下文 trace 日志（采样）
    mika_context_trace_enabled: bool = False
    mika_context_trace_sample_rate: float = 1.0

    @staticmethod
    def _parse_env_bool(value: str) -> bool:
        normalized = str(value).strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise ValueError("must be a boolean value")

    @staticmethod
    def _parse_env_int(value: str) -> int:
        return int(str(value).strip())

    @staticmethod
    def _parse_env_float(value: str) -> float:
        return float(str(value).strip())

    @classmethod
    def _parse_env_value_for_field(cls, field_name: str, raw_value: str) -> Any:
        """按字段注解类型解析 MIKA_* 别名环境变量。"""
        text = str(raw_value).strip()
        annotation = cls.__annotations__.get(field_name)
        origin = get_origin(annotation)
        args = get_args(annotation)

        if annotation is None or annotation is str:
            return str(raw_value)
        if annotation is bool:
            return cls._parse_env_bool(text)
        if annotation is int:
            return cls._parse_env_int(text)
        if annotation is float:
            return cls._parse_env_float(text)

        if origin in {list, List}:
            item_type = args[0] if args else str
            if text == "":
                raw_items: list[Any] = []
            elif text.startswith("["):
                parsed = json.loads(text)
                if not isinstance(parsed, list):
                    raise ValueError("必须是 JSON 数组")
                raw_items = parsed
            else:
                raw_items = [part.strip() for part in text.split(",") if part.strip()]

            parsed_items: list[Any] = []
            for item in raw_items:
                if item_type is int:
                    parsed_items.append(int(item))
                elif item_type is float:
                    parsed_items.append(float(item))
                elif item_type is bool:
                    if isinstance(item, bool):
                        parsed_items.append(item)
                    else:
                        parsed_items.append(cls._parse_env_bool(str(item)))
                else:
                    parsed_items.append(str(item))
            return parsed_items

        # 兜底：保持字符串，交给后续逻辑处理
        return str(raw_value)

    @model_validator(mode="before")
    @classmethod
    def _inject_mika_aliases_before_validation(cls, data: Any) -> Any:
        """在字段校验前注入 MIKA_* 环境变量到 mika_* 字段。"""
        if not isinstance(data, dict):
            return data

        payload = dict(data)
        for field_name in cls.__annotations__.keys():
            if not field_name.startswith("mika_"):
                continue

            current = payload.get(field_name)
            if current not in (None, "", [], {}):
                continue

            alias_env_name = f"MIKA_{field_name[len('mika_'):].upper()}"
            raw = os.getenv(alias_env_name)
            if raw is None or str(raw).strip() == "":
                continue

            try:
                payload[field_name] = cls._parse_env_value_for_field(field_name, raw)
            except Exception as exc:
                raise ValueError(f"{alias_env_name} 配置无效: {raw!r}") from exc

        return payload

    @staticmethod
    def _is_present(value: Any) -> bool:
        return value not in (None, "", [], {})

    @classmethod
    def _get_declared_field_default(cls, field_name: str) -> Any:
        missing = object()
        model_fields = getattr(cls, "model_fields", None)
        if isinstance(model_fields, dict):
            field_info = model_fields.get(field_name)
            if field_info is not None:
                default = getattr(field_info, "default", missing)
                if default is not missing:
                    return default
        return getattr(cls, field_name, missing)

    def _ensure_removed_legacy_inputs_blocked(self) -> None:
        for env_name, new_env_name in _REMOVED_LEGACY_ENV_KEYS.items():
            raw = os.getenv(env_name)
            if raw is None or str(raw).strip() == "":
                continue
            raise ValueError(
                f"检测到已移除的环境变量 {env_name}，请改用 {new_env_name}。"
            )

        for legacy_key, new_key in _REMOVED_LEGACY_KEYS:
            if not hasattr(self, legacy_key):
                continue
            raw = getattr(self, legacy_key, None)
            if not self._is_present(raw):
                continue
            raise ValueError(
                f"检测到已移除的配置键 {legacy_key}，请改用 {new_key}。"
            )

    def _apply_mika_aliases_fallback(self) -> None:
        """兜底注入 MIKA_* 别名（用于极简测试环境）。"""
        explicit_fields = set(getattr(self, "model_fields_set", set()) or set())
        for field_name in type(self).__annotations__.keys():
            if not field_name.startswith("mika_"):
                continue

            if field_name in explicit_fields:
                continue

            current = getattr(self, field_name, None)
            default_value = self._get_declared_field_default(field_name)
            if self._is_present(current) and current != default_value:
                continue

            alias_env_name = f"MIKA_{field_name[len('mika_'):].upper()}"
            raw = os.getenv(alias_env_name)
            if raw is None or str(raw).strip() == "":
                continue

            try:
                object.__setattr__(
                    self,
                    field_name,
                    self._parse_env_value_for_field(field_name, raw),
                )
            except Exception as exc:
                raise ValueError(f"{alias_env_name} 配置无效: {raw!r}") from exc

    def _apply_mika_observability_aliases(self) -> None:
        """Support `MIKA_*` observability env aliases."""
        _missing = object()
        explicit_fields = set(getattr(self, "model_fields_set", set()) or set())
        alias_specs = (
            ("mika_metrics_prometheus_enabled", "MIKA_METRICS_PROMETHEUS_ENABLED", self._parse_env_bool),
            ("mika_health_check_api_probe_enabled", "MIKA_HEALTH_CHECK_API_PROBE_ENABLED", self._parse_env_bool),
            (
                "mika_health_check_api_probe_timeout_seconds",
                "MIKA_HEALTH_CHECK_API_PROBE_TIMEOUT_SECONDS",
                self._parse_env_float,
            ),
            (
                "mika_health_check_api_probe_ttl_seconds",
                "MIKA_HEALTH_CHECK_API_PROBE_TTL_SECONDS",
                self._parse_env_int,
            ),
            ("mika_context_trace_enabled", "MIKA_CONTEXT_TRACE_ENABLED", self._parse_env_bool),
            ("mika_context_trace_sample_rate", "MIKA_CONTEXT_TRACE_SAMPLE_RATE", self._parse_env_float),
        )

        for field_name, env_name, parser in alias_specs:
            raw = os.getenv(env_name)
            if raw is None or str(raw).strip() == "":
                continue
            if field_name in explicit_fields:
                continue

            current = getattr(self, field_name)
            default_value: Any = _missing
            model_fields = getattr(type(self), "model_fields", None)
            if isinstance(model_fields, dict):
                field_info = model_fields.get(field_name)
                if field_info is not None:
                    default_value = getattr(field_info, "default", _missing)
            if default_value is _missing:
                default_value = getattr(type(self), field_name, _missing)
            if default_value is _missing:
                continue
            if current != default_value:
                continue

            try:
                object.__setattr__(self, field_name, parser(raw))
            except ValueError as exc:
                raise ValueError(f"{env_name} 配置无效: {raw!r}") from exc

        if self.mika_health_check_api_probe_timeout_seconds <= 0:
            raise ValueError("mika_health_check_api_probe_timeout_seconds 必须大于 0")
        if self.mika_health_check_api_probe_ttl_seconds < 1:
            raise ValueError("mika_health_check_api_probe_ttl_seconds 必须大于等于 1")
        if self.mika_context_trace_sample_rate < 0 or self.mika_context_trace_sample_rate > 1:
            raise ValueError("概率参数必须在 0.0 到 1.0 之间")
    
    @field_validator('mika_temperature', 'mika_proactive_temperature')
    @classmethod
    def validate_temperature(cls, v: float) -> float:
        """验证温度参数范围（0.0-2.0）"""
        if v < 0.0 or v > 2.0:
            raise ValueError(f"温度参数必须在 0.0 到 2.0 之间，当前值: {v}")
        return v

    @field_validator("mika_health_check_api_probe_timeout_seconds")
    @classmethod
    def validate_health_probe_timeout(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("mika_health_check_api_probe_timeout_seconds 必须大于 0")
        return v

    @field_validator("mika_health_check_api_probe_ttl_seconds")
    @classmethod
    def validate_health_probe_ttl(cls, v: int) -> int:
        if v < 1:
            raise ValueError("mika_health_check_api_probe_ttl_seconds 必须大于等于 1")
        return v

    @field_validator(
        "mika_active_reply_probability",
        "mika_context_trace_sample_rate",
        "mika_history_inline_threshold",
        "mika_history_two_stage_threshold",
    )
    @classmethod
    def validate_probability_ratio(cls, v: float) -> float:
        if v < 0 or v > 1:
            raise ValueError("概率参数必须在 0.0 到 1.0 之间")
        return v

    @field_validator("mika_quote_image_caption_timeout_seconds")
    @classmethod
    def validate_quote_caption_timeout(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("mika_quote_image_caption_timeout_seconds 必须大于 0")
        return v

    @field_validator("mika_message_split_threshold")
    @classmethod
    def validate_message_split_threshold(cls, v: int) -> int:
        if v < 60:
            raise ValueError("mika_message_split_threshold 必须大于等于 60")
        return v

    @field_validator("mika_message_split_max_chunks")
    @classmethod
    def validate_message_split_max_chunks(cls, v: int) -> int:
        if v < 2:
            raise ValueError("mika_message_split_max_chunks 必须大于等于 2")
        return v
    
    @field_validator('llm_api_key')
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        """验证 API Key 格式"""
        if not v:
            return v  # 允许为空，因为可能使用 api_key_list

        # 先去除首尾空白（允许用户在 env 里不小心写了空格）
        v = v.strip()
        
        # 检查是否为占位符值
        if _is_api_key_placeholder(v):
            raise ValueError("API Key 看起来是占位符，请配置真实的 API Key")
        
        # Mika API Key 通常以 'AI' 开头，长度约 39 字符
        # 测试/中转场景下 key 可能更短；这里保持最小长度校验但放宽至 25。
        if len(v) < 25:
            raise ValueError("API Key 长度不符合要求")
        
        # 检查是否包含空格（中间不允许有任何空白字符）
        if re.search(r'\s', v):
            raise ValueError("API Key 不应包含空格")

        return v
    
    @field_validator('llm_api_key_list')
    @classmethod
    def validate_api_key_list(cls, v: List[str]) -> List[str]:
        """验证 API Key 列表"""
        validated_keys = []
        for i, key in enumerate(v):
            key = key.strip()
            if not key:
                continue  # 跳过空字符串

            if _is_api_key_placeholder(key):
                raise ValueError(f"API Key #{i+1} 看起来是占位符，请配置真实的 API Key")

            if len(key) < 25:
                raise ValueError(f"API Key #{i+1} 长度过短（当前 {len(key)} 字符）")
            if re.search(r'\s', key):
                raise ValueError(f"API Key #{i+1} 不应包含空格")
            validated_keys.append(key)
        return validated_keys
    
    @field_validator('llm_base_url')
    @classmethod
    def validate_base_url(cls, v: str) -> str:
        """验证 Base URL 格式"""
        if not v:
            raise ValueError("Base URL 不能为空")
        if not v.startswith(('http://', 'https://')):
            raise ValueError("Base URL 必须以 http:// 或 https:// 开头")
        return v.rstrip('/')  # 统一去除尾部斜杠

    @field_validator("mika_context_mode")
    @classmethod
    def validate_context_mode(cls, v: str) -> str:
        """验证上下文模式。"""
        value = (v or "").strip().lower()
        if value == "plain":
            value = "legacy"
        if value not in {"legacy", "structured"}:
            raise ValueError("mika_context_mode 仅支持 structured 或 legacy（plain 兼容映射到 legacy）")
        return value

    @field_validator("mika_context_summary_max_chars")
    @classmethod
    def validate_context_summary_max_chars(cls, v: int) -> int:
        if v < 50:
            raise ValueError("mika_context_summary_max_chars 必须大于等于 50")
        return v

    @field_validator("mika_context_summary_trigger_turns")
    @classmethod
    def validate_context_summary_trigger_turns(cls, v: int) -> int:
        if v < 2:
            raise ValueError("mika_context_summary_trigger_turns 必须大于等于 2")
        return v

    @field_validator("mika_topic_summary_batch")
    @classmethod
    def validate_topic_summary_batch(cls, v: int) -> int:
        if v < 5:
            raise ValueError("mika_topic_summary_batch 必须大于等于 5")
        return v

    @field_validator("mika_dream_idle_minutes")
    @classmethod
    def validate_dream_idle_minutes(cls, v: int) -> int:
        if v < 1:
            raise ValueError("mika_dream_idle_minutes 必须大于等于 1")
        return v

    @field_validator("mika_dream_max_iterations")
    @classmethod
    def validate_dream_max_iterations(cls, v: int) -> int:
        if v < 1:
            raise ValueError("mika_dream_max_iterations 必须大于等于 1")
        return v

    @field_validator("mika_memory_retrieval_max_iterations")
    @classmethod
    def validate_memory_retrieval_iterations(cls, v: int) -> int:
        if v < 1:
            raise ValueError("mika_memory_retrieval_max_iterations 必须大于等于 1")
        return v

    @field_validator("mika_memory_retrieval_timeout")
    @classmethod
    def validate_memory_retrieval_timeout(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("mika_memory_retrieval_timeout 必须大于 0")
        return v
    
    @field_validator("mika_master_id", mode="before")
    @classmethod
    def validate_master_id(cls, v: Any) -> str:
        """验证 master_id（跨平台：统一字符串）"""
        candidate = str(v or "").strip()
        if not candidate:
            candidate = str(os.getenv("MIKA_MASTER_ID", "")).strip()
        if not candidate:
            raise ValueError(
                "MIKA_MASTER_ID 未配置或无效，请在 .env / .env.prod 中设置，例如：MIKA_MASTER_ID=123456789 或 tg_user_abc"
            )
        return candidate

    @field_validator("mika_group_whitelist", mode="before")
    @classmethod
    def validate_group_whitelist(cls, v: Any) -> List[str]:
        if v is None:
            return []

        raw = v
        if isinstance(raw, str):
            stripped = raw.strip()
            if not stripped:
                return []
            if stripped.startswith("[") and stripped.endswith("]"):
                try:
                    raw = json.loads(stripped)
                except Exception:
                    raw = [part.strip() for part in stripped[1:-1].split(",")]
            elif "," in stripped:
                raw = [part.strip() for part in stripped.split(",")]
            else:
                raw = [stripped]

        if isinstance(raw, (tuple, set, list)):
            cleaned: List[str] = []
            for item in raw:
                group_id = str(item or "").strip()
                if group_id:
                    cleaned.append(group_id)
            return cleaned

        candidate = str(raw or "").strip()
        return [candidate] if candidate else []

    @field_validator("llm_provider")
    @classmethod
    def validate_llm_provider(cls, v: str) -> str:
        value = (v or "").strip().lower()
        allowed = {"openai_compat", "anthropic", "google_genai", "azure_openai"}
        if value not in allowed:
            raise ValueError(
                "llm_provider 仅支持 openai_compat / anthropic / google_genai / azure_openai"
            )
        return value

    @field_validator("search_provider")
    @classmethod
    def validate_search_provider(cls, v: str) -> str:
        value = (v or "").strip().lower()
        allowed = {"serper", "tavily"}
        if value not in allowed:
            raise ValueError("search_provider 仅支持 serper / tavily")
        return value

    @field_validator("mika_core_runtime_mode")
    @classmethod
    def validate_core_runtime_mode(cls, v: str) -> str:
        value = (v or "").strip().lower()
        if value != "remote":
            raise ValueError("mika_core_runtime_mode 仅支持 remote")
        return value

    @field_validator("mika_core_remote_base_url")
    @classmethod
    def validate_core_remote_base_url(cls, v: str) -> str:
        value = (v or "").strip()
        if not value:
            return ""
        if not value.startswith(("http://", "https://")):
            raise ValueError("mika_core_remote_base_url 必须以 http:// 或 https:// 开头")
        return value.rstrip("/")

    @field_validator("mika_core_remote_timeout_seconds")
    @classmethod
    def validate_core_remote_timeout(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("mika_core_remote_timeout_seconds 必须大于 0")
        return v

    @field_validator("mika_react_max_rounds")
    @classmethod
    def validate_react_max_rounds(cls, v: int) -> int:
        if v < 1:
            raise ValueError("mika_react_max_rounds 必须大于等于 1")
        return v

    @field_validator("mika_tool_schema_mode")
    @classmethod
    def validate_tool_schema_mode(cls, v: str) -> str:
        value = (v or "").strip().lower()
        if value not in {"full", "light", "auto"}:
            raise ValueError("mika_tool_schema_mode 必须是 full / light / auto")
        return value

    @field_validator("mika_tool_schema_auto_threshold")
    @classmethod
    def validate_tool_schema_auto_threshold(cls, v: int) -> int:
        if v < 1:
            raise ValueError("mika_tool_schema_auto_threshold 必须大于等于 1")
        return v

    @field_validator("mika_tool_schema_fallback_ttl_seconds")
    @classmethod
    def validate_tool_schema_fallback_ttl_seconds(cls, v: int) -> int:
        if v < 1:
            raise ValueError("mika_tool_schema_fallback_ttl_seconds 必须大于等于 1")
        return v

    @field_validator("mika_prompt_injection_guard_action")
    @classmethod
    def validate_prompt_injection_guard_action(cls, v: str) -> str:
        value = (v or "").strip().lower()
        if value not in {"annotate", "strip"}:
            raise ValueError("mika_prompt_injection_guard_action 必须是 annotate 或 strip")
        return value

    @field_validator("mika_content_safety_action")
    @classmethod
    def validate_content_safety_action(cls, v: str) -> str:
        value = (v or "").strip().lower()
        if value not in {"replace", "drop"}:
            raise ValueError("mika_content_safety_action 必须是 replace 或 drop")
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
        if _is_api_key_placeholder(value):
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
            if _is_api_key_placeholder(item):
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
        self._ensure_removed_legacy_inputs_blocked()
        self._apply_mika_aliases_fallback()
        self._apply_mika_observability_aliases()

        llm_api_key = str(self.llm_api_key or "").strip()
        llm_api_key_list = [str(item or "").strip() for item in (self.llm_api_key_list or []) if str(item or "").strip()]
        object.__setattr__(self, "llm_api_key", llm_api_key)
        object.__setattr__(self, "llm_api_key_list", llm_api_key_list)
        object.__setattr__(self, "llm_base_url", str(self.llm_base_url or "").strip().rstrip("/"))
        object.__setattr__(self, "llm_model", str(self.llm_model or "").strip())
        object.__setattr__(self, "llm_fast_model", str(self.llm_fast_model or "").strip())
        object.__setattr__(self, "search_provider", str(self.search_provider or "serper").strip().lower())
        object.__setattr__(self, "search_api_key", str(self.search_api_key or "").strip())

        resolved_provider = (self.llm_provider or "openai_compat").strip().lower()
        resolved_base_url = (self.llm_base_url or "").strip()
        allow_keyless_ollama = (
            resolved_provider == "openai_compat" and _is_local_ollama_base_url(resolved_base_url)
        )

        # 确保至少配置了一个 API Key（本地 Ollama 可免 key）
        if (
            not allow_keyless_ollama
            and not llm_api_key
            and not llm_api_key_list
        ):
            raise ValueError(
                "必须至少配置 LLM_API_KEY 或 LLM_API_KEY_LIST 其中之一，例如："
                "LLM_API_KEY=\"你的Key\" 或 LLM_API_KEY_LIST=[\"key1\", \"key2\"]"
            )
        
        # 如果语义模型未配置，使用 fastembed 官方中文模型作为默认值
        if not self.mika_semantic_model:
            object.__setattr__(self, "mika_semantic_model", "BAAI/bge-small-zh-v1.5")
        
        # 当内置搜索或外置搜索功能可能启用时，验证 search_api_key
        # 注意：mika_enable_builtin_search 是内置搜索开关
        # 外置搜索默认启用，需要 search_api_key
        if self.search_api_key:
            # 验证 search_api_key 格式
            key = self.search_api_key.strip()
            placeholder_patterns = ['your_api_key', 'xxx', 'placeholder', 'test_key', 'api_key_here']
            if any(p in key.lower() for p in placeholder_patterns):
                raise ValueError("search_api_key 看起来是占位符，请配置真实的 API Key")
            if len(key) < 10:
                raise ValueError("search_api_key 长度不符合要求")

        if not self.mika_core_remote_base_url.strip():
            raise ValueError(
                "必须配置 mika_core_remote_base_url（remote core service 地址）"
            )
        
        return self
    
    def get_effective_api_keys(self) -> List[str]:
        """获取所有有效的 API Key 列表"""
        keys: list[str] = []
        if self.llm_api_key:
            keys.append(self.llm_api_key)
        keys.extend(self.llm_api_key_list)
        deduped: list[str] = []
        seen: set[str] = set()
        for key in keys:
            if key in seen:
                continue
            deduped.append(key)
            seen.add(key)
        return deduped

    def get_llm_config(self) -> Dict[str, Any]:
        """获取当前生效的 LLM provider 配置。"""
        provider = (self.llm_provider or "openai_compat").strip().lower()
        base_url = (self.llm_base_url or "").strip().rstrip("/")
        model = (self.llm_model or "").strip()
        fast_model = (self.llm_fast_model or "").strip()
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

    def resolve_task_model(
        self,
        task_name: str,
        llm_cfg: Optional[Dict[str, Any]] = None,
    ) -> str:
        """解析任务模型，优先 task-specific 字段，随后回退到 fast/model。"""
        task_key = str(task_name or "").strip().lower()
        task_overrides = {
            "filter": str(self.mika_task_filter_model or "").strip(),
            "summarizer": str(self.mika_task_summarizer_model or "").strip(),
            "memory": str(self.mika_task_memory_model or "").strip(),
        }
        selected = task_overrides.get(task_key, "")
        if selected:
            return selected

        effective_llm_cfg = llm_cfg if isinstance(llm_cfg, dict) else self.get_llm_config()
        fallback_fast = str(effective_llm_cfg.get("fast_model") or "").strip()
        if fallback_fast:
            return fallback_fast

        fallback_model = str(effective_llm_cfg.get("model") or "").strip()
        if fallback_model:
            return fallback_model

        return str(self.llm_fast_model or self.llm_model or "").strip()

    def get_task_model_config(self) -> Dict[str, str]:
        """返回当前任务模型解析结果。"""
        llm_cfg = self.get_llm_config()
        return {
            "filter": self.resolve_task_model("filter", llm_cfg=llm_cfg),
            "summarizer": self.resolve_task_model("summarizer", llm_cfg=llm_cfg),
            "memory": self.resolve_task_model("memory", llm_cfg=llm_cfg),
        }

    def get_search_provider_config(self) -> Dict[str, Any]:
        """获取当前生效的 Search provider 配置。"""
        provider = (self.search_provider or "serper").strip().lower()
        api_key = (self.search_api_key or "").strip()
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
        primary_api_key = llm_cfg["api_keys"][0] if llm_cfg["api_keys"] else ""
        return {
            "provider": llm_cfg["provider"],
            "api_key": primary_api_key,
            "api_key_list": list(llm_cfg["api_keys"]),
            "base_url": llm_cfg["base_url"],
            "model": llm_cfg["model"],
            "fast_model": llm_cfg["fast_model"],
            "extra_headers": dict(llm_cfg["extra_headers"]),
            "max_context": self.mika_max_context,
            "temperature": self.mika_temperature,
            "http_timeout_seconds": self.mika_http_client_timeout_seconds,
        }

    def get_search_config(self) -> dict:
        """搜索相关配置分层。"""
        provider_cfg = self.get_search_provider_config()
        return {
            "provider": provider_cfg["provider"],
            "api_key": provider_cfg["api_key"],
            "extra_headers": dict(provider_cfg["extra_headers"]),
            "cache_ttl_seconds": self.mika_search_cache_ttl_seconds,
            "cache_max_size": self.mika_search_cache_max_size,
            "classify_cache_ttl_seconds": self.mika_search_classify_cache_ttl_seconds,
            "classify_cache_max_size": self.mika_search_classify_cache_max_size,
            "llm_gate_enabled": self.mika_search_llm_gate_enabled,
            "llm_gate_fallback_mode": self.mika_search_llm_gate_fallback_mode,
            "allow_tool_refine": self.mika_search_allow_tool_refine,
            "tool_refine_max_rounds": self.mika_search_tool_refine_max_rounds,
        }

    def get_core_runtime_config(self) -> dict:
        """Core Runtime（remote-only）配置分层。"""
        return {
            "mode": "remote",
            "remote_base_url": (self.mika_core_remote_base_url or "").strip().rstrip("/"),
            "remote_timeout_seconds": float(self.mika_core_remote_timeout_seconds),
            "service_token": str(self.mika_core_service_token or "").strip(),
        }

    def get_image_config(self) -> dict:
        """图片处理与缓存配置分层。"""
        return {
            "max_images": self.mika_max_images,
            "require_keyword": self.mika_image_require_keyword,
            "download_concurrency": self.mika_image_download_concurrency,
            "cache_max_entries": self.mika_image_cache_max_entries,
            "keywords": list(self.mika_image_keywords),
        }

    def get_proactive_config(self) -> dict:
        """主动发言配置分层。"""
        return {
            "keywords": list(self.mika_proactive_keywords),
            "rate": self.mika_proactive_rate,
            "cooldown_seconds": self.mika_proactive_cooldown,
            "cooldown_messages": self.mika_proactive_cooldown_messages,
            "heat_threshold": self.mika_heat_threshold,
            "ignore_len": self.mika_proactive_ignore_len,
            "active_reply_ltm_enabled": self.mika_active_reply_ltm_enabled,
            "active_reply_probability": self.mika_active_reply_probability,
            "active_reply_whitelist": list(self.mika_active_reply_whitelist),
        }

    def get_observability_config(self) -> dict:
        """可观测性配置分层。"""
        return {
            "prometheus_enabled": self.mika_metrics_prometheus_enabled,
            "health_api_probe_enabled": self.mika_health_check_api_probe_enabled,
            "health_api_probe_timeout_seconds": self.mika_health_check_api_probe_timeout_seconds,
            "health_api_probe_ttl_seconds": self.mika_health_check_api_probe_ttl_seconds,
            "context_trace_enabled": self.mika_context_trace_enabled,
            "context_trace_sample_rate": self.mika_context_trace_sample_rate,
        }
    
    # ==================== 用户标识配置 ====================
    mika_master_id: str = ""             # Master 的平台用户 ID（跨平台字符串）
    mika_master_name: str = "Sensei"     # Master 的称呼
    mika_bot_display_name: str = "Mika"  # 机器人显示名称（用于转发消息等）
    
    # ==================== 提示词配置 ====================
    mika_prompt_file: str = "system.yaml"  # 外部提示词文件名（prompts/目录下）
    mika_system_prompt: str = ""           # 内置提示词（仅在文件为空时使用）
    
    # ==================== 上下文配置 ====================
    mika_max_context: int = 40       # 最大上下文轮数
    mika_history_count: int = 50     # 群历史消息查询数量
    # SQLiteContextStore 的 LRU 缓存条目数上限（越小越省内存，越大越高命中率）
    mika_context_cache_max_size: int = 200
    # 上下文存储模式：legacy=历史兼容，structured=结构化内容（推荐）
    mika_context_mode: str = "structured"
    # 上下文最大保留轮次（优先于按消息条数截断）
    mika_context_max_turns: int = 30
    # 软 token 上限（估算），超过后会逐轮裁剪旧上下文
    mika_context_max_tokens_soft: int = 12000
    # 是否启用摘要压缩（默认关闭，稳定优先）
    mika_context_summary_enabled: bool = False
    # 摘要文本最大字符数
    mika_context_summary_max_chars: int = 500
    # 触发摘要的最小轮次
    mika_context_summary_trigger_turns: int = 20
    # 话题化摘要（分主题整理群聊记忆）
    mika_topic_summary_enabled: bool = False
    # 每累计 N 条新消息触发一次话题摘要
    mika_topic_summary_batch: int = 25
    # Dream 离线整理（空闲后合并/清理话题摘要）
    mika_dream_enabled: bool = False
    mika_dream_idle_minutes: int = 30
    mika_dream_max_iterations: int = 5
    # 多模态严格模式：清理不合法的历史多模态块，避免接口报错
    mika_multimodal_strict: bool = True
    # 是否为引用消息中的图片注入简短说明（best-effort）
    mika_quote_image_caption_enabled: bool = True
    # 引用图片说明模板（仅用于构造提示文本，不触发额外模型调用）
    mika_quote_image_caption_prompt: str = "[引用图片共{count}张]"
    # 解析引用消息的 API 超时阈值（秒）
    mika_quote_image_caption_timeout_seconds: float = 3.0

    # ==================== OneBot 兼容性配置 ====================
    # 离线消息同步依赖非标准 API（如 get_group_msg_history），默认关闭以提升兼容性
    mika_offline_sync_enabled: bool = False
    
    # ==================== 触发配置 ====================
    mika_reply_private: bool = True  # 是否响应私聊
    mika_reply_at: bool = True       # 是否响应@消息
    mika_group_whitelist: List[str] = []  # 会话白名单（空=全部允许，跨平台字符串）
    
    # ==================== 主动发言配置 ====================
    mika_proactive_keywords: List[str] = ["Mika", "未花",]  # 强触发关键词
    mika_proactive_topics: List[str] = [  # 语义话题库 (扩充为短语以增强语义匹配)
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
    mika_proactive_rate: float = 0.2       # 触发概率 (0.0 - 1.0)
    mika_proactive_cooldown: int = 30       # 冷却时间 (秒)
    mika_proactive_cooldown_messages: int = 5  # 消息条数冷却 (上次主动发言后需要至少 N 条新消息)
    mika_heat_threshold: int = 10           # 热度阈值 (消息数/分钟)
    mika_proactive_ignore_len: int = 4     # 忽略短于此长度的消息

    # 主动发言判决（网络重试/超时）
    mika_proactive_judge_timeout_seconds: float = 20.0
    mika_proactive_judge_max_retries: int = 2
    mika_proactive_judge_retry_delay_seconds: float = 1.0
    mika_proactive_judge_max_images: int = 2
    # 群聊相关性过滤（轻量 LLM 判定是否值得回复）
    mika_relevance_filter_enabled: bool = False
    mika_relevance_filter_model: str = ""
    # Active Reply（LTM 风格）门控
    mika_active_reply_ltm_enabled: bool = True
    mika_active_reply_probability: float = 1.0
    mika_active_reply_whitelist: List[str] = []
    
    # ==================== 语义匹配配置 ====================
    # 是否启用语义匹配（fastembed/ONNX Runtime）。关闭可显著降低内存占用。
    mika_semantic_enabled: bool = True
    # 语义匹配后端：
    # - auto: 自动选择（当前等价于 fastembed）
    # - fastembed: 使用 fastembed（更省内存，CPU 推理；首次会下载/缓存模型）
    mika_semantic_backend: str = "auto"
    mika_semantic_model: str = ""          # 模型名 (env: MIKA_SEMANTIC_MODEL)
    # 可选：自定义 ONNX 模型目录（如 e5-small INT8）
    mika_semantic_onnx_path: str = ""      # env: MIKA_SEMANTIC_ONNX_PATH
    # E5 系模型建议使用 query:/passage: 前缀；非 E5（如 multilingual MiniLM）通常不需要。
    mika_semantic_use_e5_prefixes: bool = True  # env: MIKA_SEMANTIC_USE_E5_PREFIXES
    # fastembed 的模型缓存目录（可选）。为空则使用 fastembed 默认缓存路径（通常在 ~/.cache）。
    mika_fastembed_cache_dir: str = ""  # env: MIKA_FASTEMBED_CACHE_DIR
    # fastembed 的本地模型目录（可选）。设置后将跳过在线下载，直接从该目录加载 ONNX 模型文件。
    mika_fastembed_model_dir: str = ""  # env: MIKA_FASTEMBED_MODEL_DIR
    mika_semantic_threshold: float = 0.4   # 匹配阈值 (0.0 - 1.0)

    @field_validator("mika_semantic_backend")
    @classmethod
    def validate_semantic_backend(cls, v: str) -> str:
        allowed = {"auto", "fastembed"}
        normalized = (v or "").strip().lower()
        # 兼容旧配置：sentence-transformers -> fastembed
        if normalized in {"sentence-transformers", "sentence_transformers"}:
            return "fastembed"
        if normalized not in allowed:
            raise ValueError("mika_semantic_backend 必须是 auto / fastembed")
        return normalized

    # ==================== 视觉与图片配置 ====================
    mika_max_images: int = 10              # 单条消息最大处理图片数
    mika_image_cache_max_gap: int = 10     # [已废弃] 由 lifecycle 强制覆盖为 max_context * 2
    mika_image_require_keyword: bool = True  # 是否需要关键词触发缓存读取
    
    # ==================== 消息处理配置 ====================
    mika_forward_threshold: int = 300      # 合并转发阈值 (字符数)
    # 回复流式发送（端到端能力，平台不支持时自动回退）
    mika_reply_stream_enabled: bool = False
    mika_reply_stream_mode: str = "chunked"  # chunked | final_only
    mika_reply_stream_min_chars: int = 120
    mika_reply_stream_chunk_chars: int = 80
    mika_reply_stream_delay_ms: int = 0
    # 长回复分段发送（提升 IM 可读性）
    mika_message_split_enabled: bool = False
    mika_message_split_threshold: int = 300
    mika_message_split_max_chunks: int = 6
    # 长回复发送失败时，是否启用“渲染图片并发送”兜底
    mika_long_reply_image_fallback_enabled: bool = True
    # 长回复渲染图片时最多处理的字符数（超出会截断）
    mika_long_reply_image_max_chars: int = 12000
    # 长回复渲染图片最大宽度（像素）
    mika_long_reply_image_max_width: int = 960
    # 长回复渲染图片字号
    mika_long_reply_image_font_size: int = 24
    # 兼容保留：历史分片配置，当前主链路不再使用
    mika_long_message_chunk_size: int = 800

    # 空回复本地收敛策略（传输层）
    # 在不重跑整条业务链路（分类/构建/上下文降级）的前提下，做有限次快速重试
    mika_empty_reply_local_retries: int = 1
    mika_empty_reply_local_retry_delay_seconds: float = 0.4
    # 传输层超时本地重试（仅针对 TimeoutException）
    mika_transport_timeout_retries: int = 1
    mika_transport_timeout_retry_delay_seconds: float = 0.6
    # 是否允许空回复触发业务级上下文降级重试（默认关闭，便于排障）
    mika_empty_reply_context_degrade_enabled: bool = False
    mika_empty_reply_context_degrade_max_level: int = 2

    # ==================== 搜索缓存配置 ====================
    mika_search_cache_ttl_seconds: int = 60
    mika_search_cache_max_size: int = 100

    # ==================== 外置搜索 P0 优化配置 ====================
    # 外置搜索触发的最低有效 query 长度（清洗后过短将跳过搜索）
    mika_search_min_query_length: int = 4
    # 注入到 System 的搜索结果条数上限（过滤低质条目后截断）
    mika_search_max_injection_results: int = 6

    # ==================== 外置搜索 LLM Gate 配置 ====================
    # 是否启用“全量 LLM 判定 gate”：低信号/本地时间过滤后，每条消息都先调用 LLM 判 needs_search
    mika_search_llm_gate_enabled: bool = False
    # LLM 判定失败时回退策略：
    # - none: 不回退外搜
    # - strong_timeliness: 仅当命中强时效词时回退外搜
    mika_search_llm_gate_fallback_mode: str = "strong_timeliness"
    # 分类请求参数（稳定性优先，默认 temperature=0）
    mika_search_classify_temperature: float = 0.0
    mika_search_classify_max_tokens: int = 256
    # 分类判定缓存（避免短时间内重复调用 LLM）
    mika_search_classify_cache_ttl_seconds: int = 60
    mika_search_classify_cache_max_size: int = 200
    # 预搜索命中后，是否允许模型再发起一次工具补搜
    mika_search_allow_tool_refine: bool = True
    # 单轮对话最多允许补搜几次（仅对 web_search 生效）
    mika_search_tool_refine_max_rounds: int = 1

    # ==================== 内置搜索配置 ====================
    mika_enable_builtin_search: bool = False

    # ==================== 图片处理性能 ====================
    mika_image_download_concurrency: int = 3
    mika_image_cache_max_entries: int = 200
    mika_image_keywords: List[str] = []

    # ==================== 历史图片上下文增强配置 ====================
    # 模式: off=关闭, inline=仅回注原图, two_stage=仅两阶段, hybrid=混合(推荐)
    mika_history_image_mode: str = "hybrid"
    # 历史上下文快照是否保存多模态图片 part（默认关闭，改为文本占位）
    mika_history_store_multimodal: bool = False
    # 单次请求直接回注的历史原图数量上限
    mika_history_image_inline_max: int = 1
    # hybrid 模式下触发 inline 的最低置信度阈值
    mika_history_inline_threshold: float = 0.85
    # 两阶段补图工具最多补几张
    mika_history_image_two_stage_max: int = 2
    # 触发 two-stage 的最低置信度阈值
    mika_history_two_stage_threshold: float = 0.5
    # 是否启用连续图片拼图
    mika_history_collage_enabled: bool = False
    # 拼图最多合成几张图片
    mika_history_image_collage_max: int = 4
    # 拼图目标最大边长(px)，用于控制 token 成本
    mika_history_image_collage_target_px: int = 768
    # 历史图片触发关键词（空则使用默认集合）
    mika_history_image_trigger_keywords: List[str] = []

    # ==================== 工具调用安全控制 ====================
    # 输入防护：基础 prompt injection 检测（用于用户输入/外部检索结果）
    mika_prompt_injection_guard_enabled: bool = True
    # annotate: 注入安全前缀；strip: 过滤可疑指令片段
    mika_prompt_injection_guard_action: str = "annotate"
    # 自定义规则（正则）。为空时使用内置默认规则。
    mika_prompt_injection_guard_patterns: List[str] = []
    # 日志敏感信息脱敏（token/api_key/query key）
    mika_log_redaction_enabled: bool = True

    mika_tool_allowlist: List[str] = ["web_search", "search_group_history", "fetch_history_images", "search_knowledge"]
    # allowlist 非空时，是否自动放行动态注册工具（source=mcp/plugin）
    mika_tool_allow_dynamic_registered: bool = True
    # 工具 schema 暴露策略：full（完整）/light（轻量）/auto（工具数量超过阈值时轻量）
    mika_tool_schema_mode: str = "full"
    mika_tool_schema_auto_threshold: int = 10
    # 轻量 schema 是否保留参数级 description（会增加 token）
    mika_tool_schema_light_keep_param_description: bool = False
    # 检测到工具参数/工具名疑似不匹配时，是否按会话暂时回退 full schema
    mika_tool_schema_auto_fallback_full: bool = True
    # 回退 full schema 的会话级持续时间（秒）
    mika_tool_schema_fallback_ttl_seconds: int = 600
    mika_tool_result_max_chars: int = 4000

    # 出站内容安全（发送前）
    mika_content_safety_enabled: bool = False
    mika_content_safety_action: str = "replace"
    mika_content_safety_block_keywords: List[str] = []
    mika_content_safety_replacement: str = "抱歉，这条回复不适合直接发送，我换个说法。"

    # ==================== 工具调用 Loop 配置 ====================
    # 单次对话允许模型触发工具调用的最大轮数（每轮可包含多个 tool_calls）
    mika_tool_max_rounds: int = 5
    # 单个工具 handler 的超时时间（秒）
    mika_tool_timeout_seconds: float = 20.0
    # 达到上限后是否强制模型停止使用工具并给出最终答复
    mika_tool_force_final_on_max_rounds: bool = True
    # ReAct 显式推理模式（默认关闭）
    mika_react_enabled: bool = False
    # ReAct 模式下工具循环最大轮次（可高于 mika_tool_max_rounds）
    mika_react_max_rounds: int = 8
    # ==================== 长期记忆配置 ====================
    mika_memory_enabled: bool = False
    mika_memory_search_top_k: int = 5
    mika_memory_min_similarity: float = 0.5
    mika_memory_max_age_days: int = 90
    mika_memory_max_facts_per_extract: int = 5
    mika_memory_extract_interval: int = 3
    # ReAct 记忆检索 Agent（多源查询 topic/profile/memory/knowledge）
    mika_memory_retrieval_enabled: bool = False
    mika_memory_retrieval_max_iterations: int = 3
    mika_memory_retrieval_timeout: float = 15.0
    # ==================== 知识库 RAG 配置 ====================
    mika_knowledge_enabled: bool = False
    # 默认知识库（可按群/场景在工具调用中覆盖 corpus_id）
    mika_knowledge_default_corpus: str = "default"
    # 向量检索默认 Top-K 与最低相似度
    mika_knowledge_search_top_k: int = 5
    mika_knowledge_min_similarity: float = 0.5
    # 自动注入模式（人设/固定知识）
    mika_knowledge_auto_inject: bool = False
    mika_knowledge_auto_inject_top_k: int = 3
    # 文档切片参数（ingest_knowledge）
    mika_knowledge_chunk_max_chars: int = 450
    mika_knowledge_chunk_overlap_chars: int = 80
    # MCP 服务端配置（通过 runtime dep hook 的 mcp_backend 驱动）
    # 示例：
    # [{"name":"weather","command":"npx","args":["-y","@mcp/weather"]}]
    mika_mcp_servers: List[Dict[str, Any]] = []
    # 自定义工具插件模块（支持 module.path 或 module.path:ClassName）
    mika_tool_plugins: List[str] = []

    # ==================== WebUI 配置 ====================
    mika_webui_enabled: bool = False
    # WebUI 访问令牌（为空时仅允许 loopback 访问）
    mika_webui_token: str = ""
    # WebUI 路径前缀（示例：/webui）
    mika_webui_base_path: str = "/webui"

    # ==================== 主动发言策略 ====================
    mika_proactive_keyword_cooldown: int = 5

    # ==================== 主动发言 Chatroom 模式 ====================
    # 借鉴 AstrBot：主动发言时将群聊记录拼成 transcript 注入，并清空上下文 contexts，减少“已读乱回”
    mika_proactive_chatroom_enabled: bool = True
    mika_proactive_chatroom_history_lines: int = 30
    
    # ==================== 用户档案 LLM 抽取配置 ====================
    # 基础开关
    profile_extract_enabled: bool = True              # 是否启用 LLM 档案抽取（群聊）
    profile_extract_enable_private: bool = True       # 私聊是否启用
    
    # 模型配置（默认使用快速模型）
    profile_extract_model: str = ""                   # 空则使用 llm_fast_model
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
    mika_user_profile_cache_max_size: int = 256


from .runtime import config_proxy as plugin_config
