"""WebUI config APIs."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Union, get_args, get_origin

_log = logging.getLogger(__name__)

from fastapi import APIRouter, Depends

from ..config import Config
from ..runtime import (
    get_config as get_runtime_config,
    set_config as set_runtime_config,
)
from .auth import create_webui_auth_dependency
from .base_route import BaseRouteHelper

# ---------------------------------------------------------------------------
# 字段元数据：description / hint / options / secret
# 参考 AstrBot config-metadata 设计，驱动前端自动渲染合适的控件。
# ---------------------------------------------------------------------------
_CONFIG_FIELD_META_RAW: Dict[str, Dict[str, Any]] = {
    # ---- LLM 提供商 ----
    "llm_provider": {
        "description": "LLM 提供商",
        "hint": "与 LLM API 通信的适配器类型。",
        "options": ["openai_compat", "anthropic", "google_genai", "azure_openai"],
        "labels": ["OpenAI 兼容", "Anthropic", "Google GenAI", "Azure OpenAI"],
    },
    "llm_base_url": {
        "description": "API Base URL",
        "hint": "LLM 服务的 API 地址。OpenAI 兼容模式支持第三方中转。",
    },
    "llm_api_key": {
        "description": "API Key",
        "hint": "LLM 服务的认证密钥。",
        "secret": True,
    },
    "llm_model": {
        "description": "主模型",
        "hint": "默认对话使用的模型名称（如 gpt-4o、claude-sonnet-4-20250514）。",
    },
    "llm_fast_model": {
        "description": "快速模型",
        "hint": "用于记忆抽取、摘要等轻量任务的模型，留空则使用主模型。",
    },
    "mika_task_filter_model": {
        "description": "任务模型：过滤",
        "hint": "用于相关性过滤/轻量判定；留空则回退到快速模型。",
    },
    "mika_task_summarizer_model": {
        "description": "任务模型：摘要",
        "hint": "用于上下文摘要；留空则回退到快速模型。",
    },
    "mika_task_memory_model": {
        "description": "任务模型：记忆",
        "hint": "用于长期记忆提取；留空则回退到快速模型。",
    },
    "llm_extra_headers_json": {
        "description": "额外请求头",
        "hint": "JSON 格式的额外 HTTP 头，例如 {\"X-Custom\": \"value\"}。",
    },
    # ---- 身份与权限 ----
    "mika_master_id": {
        "description": "管理员 QQ 号",
        "hint": "Bot 主人的 QQ 号，拥有最高权限。",
    },
    "mika_master_name": {
        "description": "管理员昵称",
        "hint": "在对话中称呼管理员的名字。",
    },
    "mika_bot_display_name": {
        "description": "Bot 显示名称",
        "hint": "Bot 在对话中的自称。",
    },
    "mika_group_whitelist": {
        "description": "群白名单",
        "hint": "允许 Bot 响应的群号列表，为空则响应所有群。逗号分隔或 JSON 数组。",
    },
    # ---- 对话上下文 ----
    "mika_max_context": {
        "description": "最大上下文消息数",
        "hint": "单次请求携带的最大历史消息条数。",
    },
    "mika_context_mode": {
        "description": "上下文模式",
        "hint": "structured: 结构化消息列表; legacy: 纯文本拼接（兼容 plain）。",
        "options": ["structured", "legacy"],
        "labels": ["结构化消息", "纯文本拼接（兼容 plain）"],
    },
    "mika_context_max_turns": {
        "description": "最大对话轮数",
        "hint": "上下文中保留的最大对话轮数。",
    },
    "mika_context_max_tokens_soft": {
        "description": "上下文软 Token 上限",
        "hint": "超过此值时自动截断旧消息（估算值）。",
    },
    "mika_context_summary_enabled": {
        "description": "启用上下文摘要",
        "hint": "超出轮数限制时用 LLM 生成摘要代替截断。",
    },
    "mika_topic_summary_enabled": {
        "description": "启用话题摘要",
        "hint": "按批次将群聊消息整理为结构化话题摘要。",
    },
    "mika_topic_summary_batch": {
        "description": "话题摘要批次大小",
        "hint": "每累计 N 条新消息触发一次话题摘要。",
    },
    "mika_dream_enabled": {
        "description": "启用 Dream 整理",
        "hint": "会话空闲达到阈值后，后台自动整理/合并话题摘要。",
    },
    "mika_dream_idle_minutes": {
        "description": "Dream 空闲阈值（分钟）",
        "hint": "会话空闲超过该值时触发一次 Dream 整理。",
    },
    "mika_dream_max_iterations": {
        "description": "Dream 最大迭代次数",
        "hint": "单次 Dream 运行最多执行的整理步骤数。",
    },
    # ---- 语义匹配 ----
    "mika_semantic_enabled": {
        "description": "启用语义匹配",
        "hint": "使用 embedding 模型对触发词做语义相似度匹配。",
    },
    "mika_semantic_model": {
        "description": "Embedding 模型",
        "hint": "本地 embedding 模型名称，首次使用时自动下载。",
        "options": [
            "BAAI/bge-small-zh-v1.5",
            "jinaai/jina-embeddings-v2-small-en",
            "sentence-transformers/all-MiniLM-L6-v2",
        ],
    },
    "mika_semantic_backend": {
        "description": "推理后端",
        "hint": "auto: 自动选择（当前等价于 fastembed）; fastembed: CPU 推理，首次自动下载模型。",
        "options": ["auto", "fastembed"],
        "labels": ["自动选择", "FastEmbed"],
    },
    "mika_semantic_threshold": {
        "description": "匹配阈值",
        "hint": "语义相似度超过此值才触发匹配，范围 0.0 ~ 1.0。",
    },
    # ---- 长期记忆 ----
    "mika_memory_enabled": {
        "description": "启用长期记忆",
        "hint": "自动从对话中抽取事实并存储，后续对话中召回相关记忆。",
    },
    "mika_memory_search_top_k": {
        "description": "召回 Top-K",
        "hint": "每次对话最多召回的记忆条数。",
    },
    "mika_memory_min_similarity": {
        "description": "最低相似度",
        "hint": "低于此相似度的记忆不会被召回，范围 0.0 ~ 1.0。",
    },
    "mika_memory_max_age_days": {
        "description": "记忆保留天数",
        "hint": "超过此天数且召回次数少于 3 次的记忆会被自动清理。",
    },
    "mika_memory_extract_interval": {
        "description": "抽取间隔（消息数）",
        "hint": "每隔多少条消息触发一次记忆抽取。",
    },
    "mika_memory_retrieval_enabled": {
        "description": "启用 ReAct 记忆检索",
        "hint": "回复前执行多源检索（话题摘要/档案/长期记忆/知识库）。",
    },
    "mika_memory_retrieval_max_iterations": {
        "description": "ReAct 最大轮次",
        "hint": "记忆检索 Agent 的最大迭代次数。",
    },
    "mika_memory_retrieval_timeout": {
        "description": "ReAct 超时（秒）",
        "hint": "记忆检索 Agent 总超时，超时后使用当前观察结果。",
    },
    # ---- 知识库 RAG ----
    "mika_knowledge_enabled": {
        "description": "启用知识库",
        "hint": "开启 RAG 知识库功能，支持文档上传和向量检索。",
    },
    "mika_knowledge_default_corpus": {
        "description": "默认语料库 ID",
        "hint": "默认使用的知识库语料库标识。",
    },
    "mika_knowledge_auto_inject": {
        "description": "自动注入知识",
        "hint": "每次对话自动检索并注入相关知识片段到上下文。",
    },
    "mika_knowledge_search_top_k": {
        "description": "检索 Top-K",
        "hint": "知识库检索返回的最大结果数。",
    },
    "mika_knowledge_min_similarity": {
        "description": "最低相似度",
        "hint": "低于此值的知识片段不会被返回，范围 0.0 ~ 1.0。",
    },
    # ---- 工具与 ReAct ----
    "mika_tool_allowlist": {
        "description": "工具白名单",
        "hint": "允许 Bot 调用的工具名称列表，为空则允许所有已注册工具。",
    },
    "mika_tool_max_rounds": {
        "description": "工具调用轮数上限",
        "hint": "单次请求中最大工具调用轮次。",
    },
    "mika_react_enabled": {
        "description": "启用 ReAct 推理",
        "hint": "让 Bot 使用思考-行动-观察循环来处理复杂问题。",
    },
    "mika_react_max_rounds": {
        "description": "ReAct 最大轮数",
        "hint": "ReAct 推理循环的最大迭代次数。",
    },
    # ---- 消息发送 ----
    "mika_forward_threshold": {
        "description": "长消息阈值",
        "hint": "达到该长度时优先使用长消息策略（转发/图片兜底）。",
    },
    "mika_message_split_enabled": {
        "description": "启用消息分段",
        "hint": "长回复拆分为多条发送，提升 IM 阅读体验。",
    },
    "mika_message_split_threshold": {
        "description": "分段阈值",
        "hint": "达到该长度后执行分段发送。",
    },
    "mika_message_split_max_chunks": {
        "description": "最多分段条数",
        "hint": "最多拆分为多少条消息；超出的内容会并入最后一条。",
    },
    "mika_reply_stream_enabled": {
        "description": "启用流式发送（高级）",
        "hint": "逐段发送模型输出；平台不支持时自动回退。",
        "advanced": True,
    },
    "mika_reply_stream_mode": {
        "description": "流式模式（高级）",
        "hint": "chunked: 分段发送；final_only: 仅发送最终文本。",
        "options": ["chunked", "final_only"],
        "labels": ["分段发送", "仅最终文本"],
        "advanced": True,
    },
    "mika_reply_stream_min_chars": {
        "description": "流式最小长度（高级）",
        "hint": "回复长度达到该值才启用流式发送。",
        "advanced": True,
    },
    "mika_reply_stream_chunk_chars": {
        "description": "流式分段长度（高级）",
        "hint": "每段发送的目标字符数。",
        "advanced": True,
    },
    "mika_reply_stream_delay_ms": {
        "description": "流式段间延迟毫秒（高级）",
        "hint": "每段发送间隔延迟，0 表示无延迟。",
        "advanced": True,
    },
    "mika_long_reply_image_fallback_enabled": {
        "description": "启用图片兜底",
        "hint": "长消息发送失败时渲染为图片发送。",
    },
    # ---- 主动发言 ----
    "mika_proactive_keywords": {
        "description": "触发关键词",
        "hint": "包含这些关键词时触发主动发言，逗号分隔或 JSON 数组。",
    },
    "mika_proactive_topics": {
        "description": "话题关键词",
        "hint": "当群聊讨论这些话题时触发主动发言。",
    },
    "mika_proactive_rate": {
        "description": "随机触发概率",
        "hint": "每条群消息的随机触发概率，范围 0.0 ~ 1.0。",
    },
    "mika_proactive_cooldown": {
        "description": "冷却时间（秒）",
        "hint": "同一群内两次主动发言的最短间隔。",
    },
    "mika_relevance_filter_enabled": {
        "description": "启用相关性过滤",
        "hint": "群聊回复前先判断是否值得回复，降低无意义输出。",
    },
    "mika_relevance_filter_model": {
        "description": "相关性过滤模型",
        "hint": "过滤器专用模型，留空回退到任务模型配置。",
    },
    # ---- 搜索 ----
    "search_provider": {
        "description": "搜索引擎",
        "hint": "网络搜索使用的服务提供商。",
        "options": ["serper", "tavily"],
        "labels": ["Serper (Google)", "Tavily"],
    },
    "search_api_key": {
        "description": "搜索 API Key",
        "hint": "搜索引擎服务的认证密钥。",
        "secret": True,
    },
    "mika_search_llm_gate_enabled": {
        "description": "LLM 搜索守门",
        "hint": "由 LLM 判断是否需要搜索，而非每次都搜索。",
    },
    # ---- WebUI ----
    "mika_webui_enabled": {
        "description": "启用 WebUI",
        "hint": "开启后可通过浏览器访问管理界面。",
    },
    "mika_webui_token": {
        "description": "访问令牌",
        "hint": "WebUI 认证令牌，为空时仅允许本机 (127.0.0.1) 访问。",
        "secret": True,
    },
    "mika_webui_base_path": {
        "description": "URL 路径前缀",
        "hint": "WebUI 的 URL 路径前缀，如 /webui。",
    },
}

_CONFIG_SECTIONS_RAW: List[Dict[str, Any]] = [
    {
        "name": "LLM 提供商",
        "keys": [
            "llm_provider",
            "llm_base_url",
            "llm_api_key",
            "llm_model",
            "llm_fast_model",
            "mika_task_filter_model",
            "mika_task_summarizer_model",
            "mika_task_memory_model",
            "llm_extra_headers_json",
        ],
    },
    {
        "name": "身份与权限",
        "keys": [
            "mika_master_id",
            "mika_master_name",
            "mika_bot_display_name",
            "mika_group_whitelist",
        ],
    },
    {
        "name": "对话上下文",
        "keys": [
            "mika_max_context",
            "mika_context_mode",
            "mika_context_max_turns",
            "mika_context_max_tokens_soft",
            "mika_context_summary_enabled",
            "mika_topic_summary_enabled",
            "mika_topic_summary_batch",
        ],
    },
    {
        "name": "语义匹配",
        "keys": [
            "mika_semantic_enabled",
            "mika_semantic_model",
            "mika_semantic_backend",
            "mika_semantic_threshold",
        ],
    },
    {
        "name": "长期记忆",
        "keys": [
            "mika_memory_enabled",
            "mika_memory_search_top_k",
            "mika_memory_min_similarity",
            "mika_memory_max_age_days",
            "mika_memory_extract_interval",
            "mika_memory_retrieval_enabled",
            "mika_memory_retrieval_max_iterations",
            "mika_memory_retrieval_timeout",
        ],
    },
    {
        "name": "知识库 RAG",
        "keys": [
            "mika_knowledge_enabled",
            "mika_knowledge_default_corpus",
            "mika_knowledge_auto_inject",
            "mika_knowledge_search_top_k",
            "mika_knowledge_min_similarity",
        ],
    },
    {
        "name": "工具与 ReAct",
        "keys": [
            "mika_tool_allowlist",
            "mika_tool_max_rounds",
            "mika_react_enabled",
            "mika_react_max_rounds",
        ],
    },
    {
        "name": "消息发送",
        "keys": [
            "mika_forward_threshold",
            "mika_message_split_enabled",
            "mika_message_split_threshold",
            "mika_message_split_max_chunks",
            "mika_reply_stream_enabled",
            "mika_reply_stream_mode",
            "mika_reply_stream_min_chars",
            "mika_reply_stream_chunk_chars",
            "mika_reply_stream_delay_ms",
            "mika_long_reply_image_fallback_enabled",
        ],
    },
    {
        "name": "主动发言",
        "keys": [
            "mika_proactive_keywords",
            "mika_proactive_topics",
            "mika_proactive_rate",
            "mika_proactive_cooldown",
            "mika_relevance_filter_enabled",
            "mika_relevance_filter_model",
        ],
    },
    {
        "name": "搜索",
        "keys": [
            "search_provider",
            "search_api_key",
            "mika_search_llm_gate_enabled",
        ],
    },
    {
        "name": "WebUI",
        "keys": [
            "mika_webui_enabled",
            "mika_webui_token",
            "mika_webui_base_path",
        ],
    },
]


def _build_config_ui_schema() -> List[Dict[str, Any]]:
    """Build single-source UI schema and derive section/meta views from it."""
    schema: List[Dict[str, Any]] = []
    covered: set[str] = set()

    for section in _CONFIG_SECTIONS_RAW:
        section_fields: List[Dict[str, Any]] = []
        for key in section["keys"]:
            meta = dict(_CONFIG_FIELD_META_RAW.get(key, {}))
            section_fields.append({"key": key, **meta})
            covered.add(key)
        schema.append({"name": section["name"], "fields": section_fields})

    extras = [key for key in _CONFIG_FIELD_META_RAW.keys() if key not in covered]
    if extras:
        schema.append(
            {
                "name": "其他",
                "fields": [{"key": key, **dict(_CONFIG_FIELD_META_RAW.get(key, {}))} for key in extras],
            }
        )
    return schema


CONFIG_UI_SCHEMA: List[Dict[str, Any]] = _build_config_ui_schema()
CONFIG_FIELD_META: Dict[str, Dict[str, Any]] = {
    field["key"]: {meta_key: meta_val for meta_key, meta_val in field.items() if meta_key != "key"}
    for section in CONFIG_UI_SCHEMA
    for field in section.get("fields", [])
}
CONFIG_SECTIONS: List[Dict[str, Any]] = [
    {"name": section["name"], "keys": [field["key"] for field in section.get("fields", [])]}
    for section in CONFIG_UI_SCHEMA
]

_ENV_LINE_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")

# secret 字段在 GET 时返回此占位符，PUT 时若值未变则跳过。
_SECRET_PLACEHOLDER = "••••••••"
_SECRET_KEYS: frozenset[str] = frozenset(
    k for k, v in CONFIG_FIELD_META.items() if v.get("secret")
)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_env_path() -> Path:
    dotenv_path = str(os.getenv("DOTENV_PATH") or "").strip()
    if dotenv_path:
        path = Path(dotenv_path).expanduser()
        if not path.is_absolute():
            path = _project_root() / path
        return path
    return _project_root() / ".env"


def _env_key_for_field(field_name: str) -> str:
    if field_name.startswith("mika_"):
        return f"MIKA_{field_name[len('mika_'):].upper()}"
    return field_name.upper()


def _unwrap_optional(annotation: Any) -> Any:
    origin = get_origin(annotation)
    if origin is Union:
        args = [arg for arg in get_args(annotation) if arg is not type(None)]
        if len(args) == 1:
            return args[0]
    return annotation


def _field_kind(field_name: str) -> str:
    annotation = _unwrap_optional(Config.__annotations__.get(field_name))
    origin = get_origin(annotation)
    if annotation is bool:
        return "boolean"
    if annotation is int:
        return "integer"
    if annotation is float:
        return "number"
    if origin in {list, List}:
        return "array"
    if origin in {dict, Dict}:
        return "object"
    return "string"


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value}")


def _coerce_value(field_name: str, raw_value: Any) -> Any:
    annotation = _unwrap_optional(Config.__annotations__.get(field_name))
    origin = get_origin(annotation)
    if annotation is bool:
        return _coerce_bool(raw_value)
    if annotation is int:
        return int(raw_value)
    if annotation is float:
        return float(raw_value)
    if origin in {list, List}:
        if isinstance(raw_value, list):
            return raw_value
        text = str(raw_value or "").strip()
        if not text:
            return []
        if text.startswith("["):
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return parsed
            raise ValueError(f"invalid list value for {field_name}")
        return [item.strip() for item in text.split(",") if item.strip()]
    if origin in {dict, Dict}:
        if isinstance(raw_value, dict):
            return raw_value
        text = str(raw_value or "").strip()
        if not text:
            return {}
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
        raise ValueError(f"invalid object value for {field_name}")
    if raw_value is None:
        return ""
    return str(raw_value)


def _encode_env_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return json.dumps(str(value), ensure_ascii=False)


def _write_env_updates(env_path: Path, updates: Dict[str, Any]) -> None:
    env_path.parent.mkdir(parents=True, exist_ok=True)
    lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True) if env_path.exists() else []

    env_updates: Dict[str, str] = {
        _env_key_for_field(field_name): _encode_env_value(value) for field_name, value in updates.items()
    }
    seen = set()
    updated_lines: List[str] = []
    for line in lines:
        matched = _ENV_LINE_RE.match(line)
        if not matched:
            updated_lines.append(line)
            continue
        env_key = matched.group(1)
        if env_key not in env_updates:
            updated_lines.append(line)
            continue
        updated_lines.append(f"{env_key}={env_updates[env_key]}\n")
        seen.add(env_key)

    for env_key, encoded in env_updates.items():
        if env_key in seen:
            continue
        updated_lines.append(f"{env_key}={encoded}\n")

    env_path.write_text("".join(updated_lines), encoding="utf-8")


def _collect_updates(payload: Dict[str, Any]) -> tuple[Dict[str, Any], str | None]:
    updates: Dict[str, Any] = {}
    for key, value in payload.items():
        if key not in Config.__annotations__:
            return {}, f"unsupported config key: {key}"
        # secret 字段：占位符或空值表示用户未修改，跳过
        if key in _SECRET_KEYS:
            str_val = str(value or "").strip()
            if str_val in ("", _SECRET_PLACEHOLDER):
                continue
        try:
            updates[key] = _coerce_value(key, value)
        except Exception as exc:
            return {}, f"invalid value for {key}: {exc}"
    return updates, None


def _parse_env_file(env_path: Path) -> Dict[str, str]:
    if not env_path.exists():
        return {}
    values: Dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        matched = _ENV_LINE_RE.match(line)
        if not matched:
            continue
        env_key = matched.group(1)
        _, _, rhs = line.partition("=")
        values[env_key] = rhs.strip()
    return values


def _decode_env_raw_value(raw_value: str) -> Any:
    text = str(raw_value or "").strip()
    if not text:
        return ""
    if text.startswith('"') and text.endswith('"'):
        try:
            return json.loads(text)
        except Exception:
            return text[1:-1]
    if text.startswith("'") and text.endswith("'"):
        return text[1:-1]
    if text.startswith("[") or text.startswith("{"):
        try:
            return json.loads(text)
        except Exception:
            return text
    return text


def _build_config_from_env_file(env_path: Path, current_config: Config) -> Config:
    payload = dict(current_config.model_dump())
    env_values = _parse_env_file(env_path)
    for field_name in Config.__annotations__.keys():
        env_key = _env_key_for_field(field_name)
        if env_key not in env_values:
            continue
        try:
            payload[field_name] = _coerce_value(
                field_name,
                _decode_env_raw_value(env_values[env_key]),
            )
        except Exception:
            continue
    return Config(**payload)


def _sync_config_instance(target: Config, source: Config) -> None:
    """Copy validated values from source config into target config object."""
    for field_name in Config.__annotations__.keys():
        value = getattr(source, field_name, None)
        try:
            setattr(target, field_name, value)
        except Exception:
            object.__setattr__(target, field_name, value)


def _export_config_values(config: Config, *, include_secrets: bool) -> Dict[str, Any]:
    exported: Dict[str, Any] = {}
    for key in Config.__annotations__.keys():
        value = getattr(config, key, None)
        if key in _SECRET_KEYS and not include_secrets:
            exported[key] = _SECRET_PLACEHOLDER if str(value or "").strip() else ""
        else:
            exported[key] = value
    return exported


def create_config_router(
    *,
    settings_getter: Callable[[], Config] = get_runtime_config,
) -> APIRouter:
    auth_dependency = create_webui_auth_dependency(settings_getter=settings_getter)
    router = APIRouter(
        prefix="/config",
        tags=["mika-webui-config"],
        dependencies=[Depends(auth_dependency)],
    )

    @router.get("/env-path")
    async def config_env_path() -> Dict[str, str]:
        return BaseRouteHelper.ok({"path": str(_resolve_env_path())})

    @router.get("")
    async def get_config_values() -> Dict[str, Any]:
        config = settings_getter()
        sections: List[Dict[str, Any]] = []
        for section in CONFIG_UI_SCHEMA:
            fields: List[Dict[str, Any]] = []
            for field_schema in section.get("fields", []):
                key = str(field_schema.get("key") or "")
                if not key:
                    continue
                if key not in Config.__annotations__:
                    continue
                meta = {k: v for k, v in field_schema.items() if k != "key"}
                raw_value = getattr(config, key, None)
                # secret 字段：只告诉前端是否已设置，不回传明文
                if meta.get("secret"):
                    display_value = _SECRET_PLACEHOLDER if str(raw_value or "").strip() else ""
                else:
                    display_value = raw_value
                field_info: Dict[str, Any] = {
                    "key": key,
                    "value": display_value,
                    "type": _field_kind(key),
                    "description": meta.get("description", ""),
                    "hint": meta.get("hint", ""),
                }
                if "options" in meta:
                    field_info["options"] = meta["options"]
                if "labels" in meta:
                    field_info["labels"] = meta["labels"]
                if meta.get("secret"):
                    field_info["secret"] = True
                if meta.get("advanced"):
                    field_info["advanced"] = True
                fields.append(field_info)
            sections.append({"name": section["name"], "fields": fields})
        return BaseRouteHelper.ok({"sections": sections})

    @router.put("")
    async def update_config_values(payload: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            return BaseRouteHelper.error_response("payload must be an object")
        updates, error = _collect_updates(payload)
        if error:
            return BaseRouteHelper.error_response(error)

        if not updates:
            return BaseRouteHelper.ok(
                {"ok": True, "updated_keys": [], "restart_required": False},
            )

        env_path = _resolve_env_path()
        _write_env_updates(env_path, updates)

        config = settings_getter()
        for key, value in updates.items():
            try:
                setattr(config, key, value)
            except Exception:
                _log.debug("setattr(%s, %s) failed, skipping", type(config).__name__, key, exc_info=True)
        set_runtime_config(config)

        return BaseRouteHelper.ok(
            {
                "ok": True,
                "updated_keys": sorted(updates.keys()),
                "restart_required": True,
            }
        )

    @router.post("/reload")
    async def reload_config_values() -> Dict[str, Any]:
        env_path = _resolve_env_path()
        current_config = settings_getter()
        try:
            new_config = _build_config_from_env_file(env_path, current_config)
        except Exception as exc:
            return BaseRouteHelper.error_response(f"reload failed: {exc}")
        _sync_config_instance(current_config, new_config)
        set_runtime_config(current_config)
        return BaseRouteHelper.ok(
            {
                "ok": True,
                "env_path": str(env_path),
                "reloaded": True,
            }
        )

    @router.get("/export")
    async def export_config_values(include_secrets: bool = False) -> Dict[str, Any]:
        config = settings_getter()
        return BaseRouteHelper.ok(
            {
                "config": _export_config_values(config, include_secrets=bool(include_secrets)),
                "env_path": str(_resolve_env_path()),
                "include_secrets": bool(include_secrets),
            }
        )

    @router.post("/import")
    async def import_config_values(payload: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            return BaseRouteHelper.error_response("payload must be an object")

        if isinstance(payload.get("config"), dict):
            config_payload = dict(payload.get("config") or {})
            apply_runtime = bool(payload.get("apply_runtime", True))
        else:
            config_payload = dict(payload)
            apply_runtime = True

        updates, error = _collect_updates(config_payload)
        if error:
            return BaseRouteHelper.error_response(error)

        if not updates:
            return BaseRouteHelper.ok({"ok": True, "updated_keys": [], "applied_runtime": False})

        env_path = _resolve_env_path()
        _write_env_updates(env_path, updates)

        if apply_runtime:
            config = settings_getter()
            for key, value in updates.items():
                try:
                    setattr(config, key, value)
                except Exception:
                    pass
            set_runtime_config(config)

        return BaseRouteHelper.ok(
            {
                "ok": True,
                "updated_keys": sorted(updates.keys()),
                "applied_runtime": bool(apply_runtime),
                "restart_required": True,
            }
        )

    return router


__all__ = ["CONFIG_UI_SCHEMA", "CONFIG_FIELD_META", "CONFIG_SECTIONS", "create_config_router"]
