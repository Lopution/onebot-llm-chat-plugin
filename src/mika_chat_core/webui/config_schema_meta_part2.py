"""WebUI config schema metadata (part 2)."""

from __future__ import annotations

from typing import Any, Dict


CONFIG_FIELD_META_PART2: Dict[str, Dict[str, Any]] = {
    # ---- 消息发送 ----
    "mika_forward_threshold": {"description": "长消息阈值", "hint": "达到该长度时优先使用长消息策略（转发/图片兜底）。"},
    "mika_message_split_enabled": {"description": "启用消息分段", "hint": "长回复拆分为多条发送，提升 IM 阅读体验。"},
    "mika_message_split_threshold": {"description": "分段阈值", "hint": "达到该长度后执行分段发送。"},
    "mika_message_split_max_chunks": {"description": "最多分段条数", "hint": "最多拆分为多少条消息；超出的内容会并入最后一条。"},
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
    "mika_reply_stream_min_chars": {"description": "流式最小长度（高级）", "hint": "回复长度达到该值才启用流式发送。", "advanced": True},
    "mika_reply_stream_chunk_chars": {"description": "流式分段长度（高级）", "hint": "每段发送的目标字符数。", "advanced": True},
    "mika_reply_stream_delay_ms": {"description": "流式段间延迟毫秒（高级）", "hint": "每段发送间隔延迟，0 表示无延迟。", "advanced": True},
    "mika_long_reply_image_fallback_enabled": {"description": "启用图片兜底", "hint": "长消息发送失败时渲染为图片发送。"},
    # ---- 主动发言 ----
    "mika_proactive_keywords": {
        "description": "触发关键词（高级）",
        "hint": "包含这些关键词时触发主动发言，逗号分隔或 JSON 数组。",
        "advanced": True,
    },
    "mika_proactive_topics": {"description": "话题关键词（高级）", "hint": "当群聊讨论这些话题时触发主动发言。", "advanced": True},
    "mika_proactive_rate": {"description": "随机触发概率（高级）", "hint": "每条群消息的随机触发概率，范围 0.0 ~ 1.0。", "advanced": True},
    "mika_proactive_cooldown": {"description": "冷却时间（秒）（高级）", "hint": "同一群内两次主动发言的最短间隔。", "advanced": True},
    "mika_relevance_filter_enabled": {"description": "启用相关性过滤（高级）", "hint": "群聊回复前先判断是否值得回复，降低无意义输出。", "advanced": True},
    "mika_relevance_filter_model": {
        "description": "相关性过滤模型（高级）",
        "hint": "过滤器专用模型，留空回退到任务模型配置。",
        "advanced": True,
    },
    # ---- 搜索 ----
    "search_provider": {
        "description": "搜索引擎",
        "hint": "网络搜索使用的服务提供商。",
        "options": ["serper", "tavily"],
        "labels": ["Serper (Google)", "Tavily"],
    },
    "search_api_key": {"description": "搜索 API Key", "hint": "搜索引擎服务的认证密钥。", "secret": True},
    "mika_search_llm_gate_enabled": {
        "description": "LLM 搜索守门（高级）",
        "hint": "由 LLM 判断是否需要搜索，而非每次都搜索。",
        "advanced": True,
    },
    # ---- WebUI ----
    "mika_webui_enabled": {"description": "启用 WebUI", "hint": "开启后可通过浏览器访问管理界面。"},
    "mika_webui_token": {
        "description": "访问令牌",
        "hint": "WebUI 认证令牌，为空时仅允许本机 (127.0.0.1) 访问。",
        "secret": True,
    },
    "mika_webui_base_path": {
        "description": "URL 路径前缀（高级）",
        "hint": "WebUI 的 URL 路径前缀，如 /webui。",
        "advanced": True,
    },
}


__all__ = ["CONFIG_FIELD_META_PART2"]
