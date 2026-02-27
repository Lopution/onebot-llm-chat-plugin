"""WebUI config schema sections (ordering)."""

from __future__ import annotations

from typing import Any, Dict, List


CONFIG_SECTIONS_RAW: List[Dict[str, Any]] = [
    {
        "name": "LLM 提供商",
        "keys": [
            "llm_provider",
            "llm_base_url",
            "llm_api_key",
            "llm_api_key_list",
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
        "keys": ["mika_master_id", "mika_master_name", "mika_bot_display_name", "mika_group_whitelist"],
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
        "keys": ["mika_semantic_enabled", "mika_semantic_model", "mika_semantic_backend", "mika_semantic_threshold"],
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
        "keys": ["mika_tool_allowlist", "mika_tool_max_rounds", "mika_react_enabled", "mika_react_max_rounds"],
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
    {"name": "搜索", "keys": ["search_provider", "search_api_key", "mika_search_llm_gate_enabled"]},
    {"name": "WebUI", "keys": ["mika_webui_enabled", "mika_webui_token", "mika_webui_base_path"]},
]


__all__ = ["CONFIG_SECTIONS_RAW"]

