"""搜索分类器 — 配置读取与缓存管理。"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import hashlib
import time

from ..infra.logging import logger as log

from ..config import plugin_config
from . import prompt_loader as _prompt_loader


# ==================== Magic-number constants ====================
CLASSIFY_CONTEXT_FINGERPRINT_TAIL_COUNT = 2
CLASSIFY_CONTEXT_FINGERPRINT_ITEM_PREVIEW_CHARS = 80

CLASSIFY_MIN_CACHE_TTL_SECONDS = 5
CLASSIFY_DEFAULT_CACHE_TTL_SECONDS = 60
CLASSIFY_MIN_CACHE_MAX_SIZE = 10
CLASSIFY_DEFAULT_CACHE_MAX_SIZE = 200

CLASSIFY_TEMPERATURE_MIN = 0.0
CLASSIFY_TEMPERATURE_MAX = 2.0

CLASSIFY_MIN_MAX_TOKENS = 64
CLASSIFY_DEFAULT_MAX_TOKENS = 256
CLASSIFY_MAX_MAX_TOKENS = 1024

CLASSIFY_DEFAULT_MAX_QUERY_LENGTH = 64
CLASSIFY_MIN_MAX_QUERY_LENGTH = 16
CLASSIFY_MAX_MAX_QUERY_LENGTH = 256

MIN_QUERY_LENGTH_FLOOR = 2
MIN_QUERY_LENGTH_DEFAULT = 4

SHOULD_FALLBACK_MSG_PREVIEW_CHARS = 30
SHOULD_FALLBACK_CLEAN_PREVIEW_CHARS = 50

PRONOUN_CONTEXT_TAIL_COUNT = 6
PRONOUN_ENTITY_MAX_COUNT = 3

CLASSIFY_CONTEXT_ITEM_PREVIEW_CHARS = 100
CLASSIFY_LOG_MESSAGE_PREVIEW_CHARS = 50
CLASSIFY_LOG_USER_MSG_PREVIEW_CHARS = 80
CLASSIFY_LOG_RESPONSE_PREVIEW_CHARS = 200
CLASSIFY_LOG_BODY_CONTENT_PREVIEW_CHARS = 200
CLASSIFY_LOG_RAW_CONTENT_LONG_PREVIEW_CHARS = 300

CLASSIFY_HTTP_TIMEOUT_SECONDS = 15
RESPONSE_FORMAT_DOWNGRADE_ERROR_PREVIEW_CHARS = 200

MIN_VALID_RESPONSE_LEN = 50


CLASSIFY_PROMPT_DEFAULT = """
当前时间: {current_time} ({current_year})

{context_section}

用户问题: {question}

请判断用户的问题是否需要实时联网搜索才能回答。
如果不仅仅是闲聊或已有知识能回答的，请标记需要搜索，并提取核心搜索词。

请以 JSON 格式返回结果：
{{
    "needs_search": true/false,
    "topic": "主题分类(如: 实时新闻/科技动态/体育赛事/天气/百科/闲聊)",
    "search_query": "优化后的搜索关键词(如果不需要搜索则留空)"
}}
"""


def _get_classify_topic_config() -> Dict[str, object]:
    """读取并校验 classify_topic 配置段。"""
    config = _prompt_loader.load_search_prompt()
    if not isinstance(config, dict):
        log.warning(
            f"[SearchClassifier] search.yaml root 应为 dict，实际为 {type(config).__name__}，已降级到默认配置"
        )
        return {}

    classify_config = config.get("classify_topic", {})
    if not isinstance(classify_config, dict):
        log.warning(
            f"[SearchClassifier] classify_topic 应为 dict，实际为 {type(classify_config).__name__}，已降级到默认配置"
        )
        return {}

    return classify_config


def _get_classify_prompt() -> str:
    """获取分类提示词模板（从 `search.yaml` 读取）。"""
    classify_config = _get_classify_topic_config()
    template = classify_config.get("template", "")
    return template if isinstance(template, str) else ""


def _get_must_search_topics() -> list:
    """获取必须搜索的主题列表。"""
    classify_config = _get_classify_topic_config()
    topics = classify_config.get("must_search_topics", [])
    if isinstance(topics, list):
        return [str(x) for x in topics if isinstance(x, (str, int, float))]
    return []


MUST_SEARCH_TOPICS = _get_must_search_topics()


# 分类判定缓存（避免短时间内重复调用 LLM）
# 格式: {key_hash: ((needs_search, topic, search_query), timestamp)}
_classify_cache: Dict[str, Tuple[Tuple[bool, str, str], float]] = {}


def clear_classify_cache() -> None:
    """清空分类判定缓存。"""

    global _classify_cache
    _classify_cache = {}
    log.debug("分类判定缓存已清空")


def _get_classify_cache_key(message: str, context: Optional[list] = None) -> str:
    """生成分类判定缓存键（消息 + 轻量上下文指纹）。"""

    base = (message or "").strip()
    ctx_fingerprint = ""
    try:
        if context:
            parts = []
            for msg in context[-CLASSIFY_CONTEXT_FINGERPRINT_TAIL_COUNT:]:
                c = msg.get("content", "")
                if isinstance(c, str) and c:
                    parts.append(c[:CLASSIFY_CONTEXT_FINGERPRINT_ITEM_PREVIEW_CHARS])
            ctx_fingerprint = "|".join(parts)
    except Exception:
        ctx_fingerprint = ""

    raw = f"{base}||{ctx_fingerprint}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _get_cached_classify_result(key: str, ttl_seconds: int) -> Optional[Tuple[bool, str, str]]:
    """读取分类判定缓存。"""

    if not key:
        return None
    item = _classify_cache.get(key)
    if not item:
        return None
    value, ts = item
    if time.monotonic() - ts <= ttl_seconds:
        return value
    try:
        del _classify_cache[key]
    except KeyError:
        pass
    return None


def _set_classify_cache(key: str, value: Tuple[bool, str, str], max_size: int) -> None:
    """写入分类判定缓存（简单 LRU：淘汰最旧）。"""

    global _classify_cache
    if not key:
        return
    if len(_classify_cache) >= max_size:
        oldest_key = min(_classify_cache.keys(), key=lambda k: _classify_cache[k][1])
        del _classify_cache[oldest_key]
    _classify_cache[key] = (value, time.monotonic())


def _get_classify_cache_ttl_seconds() -> int:
    try:
        value = int(
            getattr(plugin_config, "mika_search_classify_cache_ttl_seconds", CLASSIFY_DEFAULT_CACHE_TTL_SECONDS)
        )
        return max(CLASSIFY_MIN_CACHE_TTL_SECONDS, value)
    except Exception:
        return CLASSIFY_DEFAULT_CACHE_TTL_SECONDS


def _get_classify_cache_max_size() -> int:
    try:
        value = int(getattr(plugin_config, "mika_search_classify_cache_max_size", CLASSIFY_DEFAULT_CACHE_MAX_SIZE))
        return max(CLASSIFY_MIN_CACHE_MAX_SIZE, value)
    except Exception:
        return CLASSIFY_DEFAULT_CACHE_MAX_SIZE


def _get_classify_temperature() -> float:
    try:
        value = float(getattr(plugin_config, "mika_search_classify_temperature", CLASSIFY_TEMPERATURE_MIN))
        return max(CLASSIFY_TEMPERATURE_MIN, min(CLASSIFY_TEMPERATURE_MAX, value))
    except Exception:
        return CLASSIFY_TEMPERATURE_MIN


def _get_classify_max_tokens() -> int:
    try:
        value = int(getattr(plugin_config, "mika_search_classify_max_tokens", CLASSIFY_DEFAULT_MAX_TOKENS))
        return max(CLASSIFY_MIN_MAX_TOKENS, min(CLASSIFY_MAX_MAX_TOKENS, value))
    except Exception:
        return CLASSIFY_DEFAULT_MAX_TOKENS


def _get_classify_max_query_length() -> int:
    """分类器生成的 search_query 最大长度（防注入/降噪）。"""

    try:
        value = int(
            getattr(plugin_config, "mika_search_classify_max_query_length", CLASSIFY_DEFAULT_MAX_QUERY_LENGTH)
        )
        return max(CLASSIFY_MIN_MAX_QUERY_LENGTH, min(CLASSIFY_MAX_MAX_QUERY_LENGTH, value))
    except Exception:
        return CLASSIFY_DEFAULT_MAX_QUERY_LENGTH


def _get_query_normalize_bot_names() -> List[str]:
    """用于 `normalize_search_query` 的机器人名列表（用于去除用户 @/称呼 等噪声）。"""

    names: List[str] = []
    try:
        display_name = getattr(plugin_config, "mika_bot_display_name", "")
        if isinstance(display_name, str) and display_name.strip():
            names.append(display_name.strip())
    except Exception:
        pass

    names.extend(["Mika", "mika"])

    deduped: List[str] = []
    seen = set()
    for n in names:
        if n and n not in seen:
            seen.add(n)
            deduped.append(n)
    return deduped


def _get_min_query_length() -> int:
    """从配置读取最小 query 长度（提供安全兜底）。"""

    try:
        value = int(getattr(plugin_config, "mika_search_min_query_length", MIN_QUERY_LENGTH_DEFAULT))
        return max(MIN_QUERY_LENGTH_FLOOR, value)
    except Exception:
        return MIN_QUERY_LENGTH_DEFAULT
