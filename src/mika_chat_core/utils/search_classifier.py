"""搜索意图分类与 query 规范化模块 — 向后兼容外观。

实际实现已拆分为：
- search_classifier_cache: 配置读取与缓存管理
- search_classifier_rules: 关键词列表、规则函数与 query 规范化
- search_classifier_parse: JSON 解析工具
- search_classifier_llm: LLM 主题分类主流程

本文件作为外观（facade）重新导出全部公共符号，
对外接口保持不变（包括 `search_engine.py` 的 re-export 链）。
"""

# --- cache layer ---
from .search_classifier_cache import (  # noqa: F401
    CLASSIFY_CONTEXT_FINGERPRINT_TAIL_COUNT,
    CLASSIFY_CONTEXT_FINGERPRINT_ITEM_PREVIEW_CHARS,
    CLASSIFY_CONTEXT_ITEM_PREVIEW_CHARS,
    CLASSIFY_DEFAULT_CACHE_MAX_SIZE,
    CLASSIFY_DEFAULT_CACHE_TTL_SECONDS,
    CLASSIFY_DEFAULT_MAX_QUERY_LENGTH,
    CLASSIFY_DEFAULT_MAX_TOKENS,
    CLASSIFY_HTTP_TIMEOUT_SECONDS,
    CLASSIFY_LOG_BODY_CONTENT_PREVIEW_CHARS,
    CLASSIFY_LOG_MESSAGE_PREVIEW_CHARS,
    CLASSIFY_LOG_RAW_CONTENT_LONG_PREVIEW_CHARS,
    CLASSIFY_LOG_RESPONSE_PREVIEW_CHARS,
    CLASSIFY_LOG_USER_MSG_PREVIEW_CHARS,
    CLASSIFY_MAX_MAX_QUERY_LENGTH,
    CLASSIFY_MAX_MAX_TOKENS,
    CLASSIFY_MIN_CACHE_MAX_SIZE,
    CLASSIFY_MIN_CACHE_TTL_SECONDS,
    CLASSIFY_MIN_MAX_QUERY_LENGTH,
    CLASSIFY_MIN_MAX_TOKENS,
    CLASSIFY_PROMPT_DEFAULT,
    CLASSIFY_TEMPERATURE_MAX,
    CLASSIFY_TEMPERATURE_MIN,
    MIN_QUERY_LENGTH_DEFAULT,
    MIN_QUERY_LENGTH_FLOOR,
    MIN_VALID_RESPONSE_LEN,
    MUST_SEARCH_TOPICS,
    PRONOUN_CONTEXT_TAIL_COUNT,
    PRONOUN_ENTITY_MAX_COUNT,
    RESPONSE_FORMAT_DOWNGRADE_ERROR_PREVIEW_CHARS,
    SHOULD_FALLBACK_MSG_PREVIEW_CHARS,
    _get_cached_classify_result,
    _get_classify_cache_key,
    _get_classify_cache_max_size,
    _get_classify_cache_ttl_seconds,
    _get_classify_max_query_length,
    _get_classify_max_tokens,
    _get_classify_prompt,
    _get_classify_temperature,
    _get_classify_topic_config,
    _get_min_query_length,
    _get_must_search_topics,
    _get_query_normalize_bot_names,
    _set_classify_cache,
    clear_classify_cache,
)

# --- rules layer ---
from .search_classifier_rules import (  # noqa: F401
    AI_KEYWORDS,
    BEST_KEYWORDS,
    LOW_SIGNAL_TOKENS,
    QUESTION_KEYWORDS,
    TIMELINESS_KEYWORDS,
    WEAK_TIME_KEYWORDS,
    _has_question_signal,
    _is_overcompressed_query,
    _resolve_pronoun_query,
    is_local_datetime_query,
    is_low_signal_query,
    normalize_search_query,
    should_fallback_strong_timeliness,
    should_search,
)

# --- parse layer ---
from .search_classifier_parse import _extract_json_object  # noqa: F401

# --- llm layer ---
from .search_classifier_llm import classify_topic_for_search  # noqa: F401

# Keep load_search_prompt and plugin_config importable from here for tests that patch them
from .prompt_loader import load_search_prompt  # noqa: F401
from ..config import plugin_config  # noqa: F401
