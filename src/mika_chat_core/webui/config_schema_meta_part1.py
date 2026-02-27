"""WebUI config schema metadata (part 1).

This file intentionally contains mostly data (field -> UI meta). It is split
into parts to keep each file small and easy to review.
"""

from __future__ import annotations

from typing import Any, Dict


CONFIG_FIELD_META_PART1: Dict[str, Dict[str, Any]] = {
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
    "llm_api_key": {"description": "API Key", "hint": "LLM 服务的认证密钥。", "secret": True},
    "llm_api_key_list": {
        "description": "API Key 列表（可选）",
        "hint": "用于 Key 轮换的列表（JSON 数组或逗号分隔）。与 LLM_API_KEY 二选一即可。",
        "secret": True,
        "advanced": True,
    },
    "llm_model": {
        "description": "主模型",
        "hint": "默认对话使用的模型名称（如 gpt-4o、claude-sonnet-4-20250514）。",
    },
    "llm_fast_model": {"description": "快速模型", "hint": "用于记忆抽取、摘要等轻量任务的模型，留空则使用主模型。"},
    "mika_task_filter_model": {
        "description": "任务模型：过滤（高级）",
        "hint": "用于相关性过滤/轻量判定；留空则回退到快速模型。",
        "advanced": True,
    },
    "mika_task_summarizer_model": {
        "description": "任务模型：摘要（高级）",
        "hint": "用于上下文摘要；留空则回退到快速模型。",
        "advanced": True,
    },
    "mika_task_memory_model": {
        "description": "任务模型：记忆（高级）",
        "hint": "用于长期记忆提取；留空则回退到快速模型。",
        "advanced": True,
    },
    "llm_extra_headers_json": {
        "description": "额外请求头（高级）",
        "hint": "JSON 格式的额外 HTTP 头，例如 {\"X-Custom\": \"value\"}。",
        "advanced": True,
    },
    # ---- 身份与权限 ----
    "mika_master_id": {"description": "管理员 QQ 号", "hint": "Bot 主人的 QQ 号，拥有最高权限。"},
    "mika_master_name": {"description": "管理员昵称", "hint": "在对话中称呼管理员的名字。"},
    "mika_bot_display_name": {"description": "Bot 显示名称", "hint": "Bot 在对话中的自称。"},
    "mika_group_whitelist": {
        "description": "群白名单",
        "hint": "允许 Bot 响应的群号列表，为空则响应所有群。逗号分隔或 JSON 数组。",
    },
    # ---- 对话上下文 ----
    "mika_max_context": {"description": "最大上下文消息数（高级）", "hint": "单次请求携带的最大历史消息条数。", "advanced": True},
    "mika_context_mode": {
        "description": "上下文模式（高级）",
        "hint": "structured: 结构化消息列表; legacy: 纯文本拼接（兼容 plain）。",
        "options": ["structured", "legacy"],
        "labels": ["结构化消息", "纯文本拼接（兼容 plain）"],
        "advanced": True,
    },
    "mika_context_max_turns": {"description": "最大对话轮数（高级）", "hint": "上下文中保留的最大对话轮数。", "advanced": True},
    "mika_context_max_tokens_soft": {
        "description": "上下文软 Token 上限（高级）",
        "hint": "超过此值时自动截断旧消息（估算值）。",
        "advanced": True,
    },
    "mika_context_summary_enabled": {
        "description": "启用上下文摘要（高级）",
        "hint": "超出轮数限制时用 LLM 生成摘要代替截断。",
        "advanced": True,
    },
    "mika_topic_summary_enabled": {
        "description": "启用话题摘要（高级）",
        "hint": "按批次将群聊消息整理为结构化话题摘要。",
        "advanced": True,
    },
    "mika_topic_summary_batch": {"description": "话题摘要批次大小（高级）", "hint": "每累计 N 条新消息触发一次话题摘要。", "advanced": True},
    "mika_dream_enabled": {"description": "启用 Dream 整理（高级）", "hint": "会话空闲达到阈值后，后台自动整理/合并话题摘要。", "advanced": True},
    "mika_dream_idle_minutes": {"description": "Dream 空闲阈值（分钟）（高级）", "hint": "会话空闲超过该值时触发一次 Dream 整理。", "advanced": True},
    "mika_dream_max_iterations": {"description": "Dream 最大迭代次数（高级）", "hint": "单次 Dream 运行最多执行的整理步骤数。", "advanced": True},
    # ---- 语义匹配 ----
    "mika_semantic_enabled": {"description": "启用语义匹配（高级）", "hint": "使用 embedding 模型对触发词做语义相似度匹配。", "advanced": True},
    "mika_semantic_model": {
        "description": "Embedding 模型（高级）",
        "hint": "本地 embedding 模型名称，首次使用时自动下载。",
        "options": [
            "BAAI/bge-small-zh-v1.5",
            "jinaai/jina-embeddings-v2-small-en",
            "sentence-transformers/all-MiniLM-L6-v2",
        ],
        "advanced": True,
    },
    "mika_semantic_backend": {
        "description": "推理后端（高级）",
        "hint": "auto: 自动选择（当前等价于 fastembed）; fastembed: CPU 推理，首次自动下载模型。",
        "options": ["auto", "fastembed"],
        "labels": ["自动选择", "FastEmbed"],
        "advanced": True,
    },
    "mika_semantic_threshold": {
        "description": "匹配阈值（高级）",
        "hint": "语义相似度超过此值才触发匹配，范围 0.0 ~ 1.0。",
        "advanced": True,
    },
    # ---- 长期记忆 ----
    "mika_memory_enabled": {
        "description": "启用长期记忆（高级）",
        "hint": "自动从对话中抽取事实并存储，后续对话中召回相关记忆。",
        "advanced": True,
    },
    "mika_memory_search_top_k": {"description": "召回 Top-K（高级）", "hint": "每次对话最多召回的记忆条数。", "advanced": True},
    "mika_memory_min_similarity": {
        "description": "最低相似度（高级）",
        "hint": "低于此相似度的记忆不会被召回，范围 0.0 ~ 1.0。",
        "advanced": True,
    },
    "mika_memory_max_age_days": {"description": "记忆保留天数（高级）", "hint": "超过此天数且召回次数少于 3 次的记忆会被自动清理。", "advanced": True},
    "mika_memory_extract_interval": {"description": "抽取间隔（消息数）（高级）", "hint": "每隔多少条消息触发一次记忆抽取。", "advanced": True},
    "mika_memory_retrieval_enabled": {
        "description": "启用 ReAct 记忆检索（高级）",
        "hint": "回复前执行多源检索（话题摘要/档案/长期记忆/知识库）。",
        "advanced": True,
    },
    "mika_memory_retrieval_max_iterations": {"description": "ReAct 最大轮次（高级）", "hint": "记忆检索 Agent 的最大迭代次数。", "advanced": True},
    "mika_memory_retrieval_timeout": {"description": "ReAct 超时（秒）（高级）", "hint": "记忆检索 Agent 总超时，超时后使用当前观察结果。", "advanced": True},
    # ---- 知识库 RAG ----
    "mika_knowledge_enabled": {"description": "启用知识库（高级）", "hint": "开启 RAG 知识库功能，支持文档上传和向量检索。", "advanced": True},
    "mika_knowledge_default_corpus": {"description": "默认语料库 ID（高级）", "hint": "默认使用的知识库语料库标识。", "advanced": True},
    "mika_knowledge_auto_inject": {"description": "自动注入知识（高级）", "hint": "每次对话自动检索并注入相关知识片段到上下文。", "advanced": True},
    "mika_knowledge_search_top_k": {"description": "检索 Top-K（高级）", "hint": "知识库检索返回的最大结果数。", "advanced": True},
    "mika_knowledge_min_similarity": {
        "description": "最低相似度（高级）",
        "hint": "低于此值的知识片段不会被返回，范围 0.0 ~ 1.0。",
        "advanced": True,
    },
    # ---- 工具与 ReAct ----
    "mika_tool_allowlist": {
        "description": "工具白名单（高级）",
        "hint": "允许 Bot 调用的工具名称列表，为空则允许所有已注册工具。",
        "advanced": True,
    },
    "mika_tool_max_rounds": {"description": "工具调用轮数上限（高级）", "hint": "单次请求中最大工具调用轮次。", "advanced": True},
    "mika_react_enabled": {"description": "启用 ReAct 推理（高级）", "hint": "让 Bot 使用思考-行动-观察循环来处理复杂问题。", "advanced": True},
    "mika_react_max_rounds": {"description": "ReAct 最大轮数（高级）", "hint": "ReAct 推理循环的最大迭代次数。", "advanced": True},
}


__all__ = ["CONFIG_FIELD_META_PART1"]
