"""搜索分类器 — 关键词列表、规则函数与 query 规范化。"""

from __future__ import annotations

from typing import List, Optional

import re

from ..infra.logging import logger as log

from .search_classifier_cache import (
    MIN_QUERY_LENGTH_FLOOR,
    MIN_QUERY_LENGTH_DEFAULT,
    PRONOUN_CONTEXT_TAIL_COUNT,
    PRONOUN_ENTITY_MAX_COUNT,
    SHOULD_FALLBACK_MSG_PREVIEW_CHARS,
    _get_min_query_length,
)


# ==================== Keyword lists ====================

# 时效性关键词列表（快速过滤，触发搜索）
TIMELINESS_KEYWORDS = [
    "最新",
    "今天",
    "现在",
    "目前",
    "刚刚",
    "最近",
    "近期",
    "今年",
    "本周",
    "本月",
    "昨天",
    "前几天",
    "新闻",
    "热点",
    "热搜",
    "比赛",
    "赛事",
    "战绩",
    "结果",
    "比分",
    "赛程",
    "排名",
    "价格",
    "多少钱",
    "股价",
    "汇率",
    "天气",
    "转会",
    "怎么了",
    "发生了什么",
    "出什么事",
    "模型",
    "版本",
    "发布",
]


# AI 相关关键词（配合"最好"、"最强"等词触发搜索）
AI_KEYWORDS = [
    "gpt",
    "mika",
    "claude",
    "llama",
    "glm",
    "qwen",
    "minimax",
    "openai",
    "anthropic",
    "google",
    "deepseek",
    "智谱",
    "通义",
    "文心",
    "讯飞",
    "abab",
    "kimi",
    "moonshot",
]


BEST_KEYWORDS = ["最好", "最强", "最厉害", "最新", "哪个好", "推荐"]


QUESTION_KEYWORDS = [
    "什么",
    "怎么",
    "为何",
    "为什么",
    "为啥",
    "多少",
    "几",
    "几号",
    "几月",
    "多久",
    "哪里",
    "哪儿",
    "哪个",
    "哪家",
    "哪位",
    "谁",
    "是否",
    "是不是",
    "能否",
    "可否",
    "吗",
    "么",
    "咋",
    "咋样",
    "如何",
]


LOW_SIGNAL_TOKENS = {
    "嗯",
    "嗯嗯",
    "哦",
    "哦哦",
    "啊",
    "呀",
    "哎",
    "哈",
    "哈哈",
    "哈哈哈",
    "呵",
    "呵呵",
    "好",
    "好的",
    "收到",
    "ok",
    "okay",
    "okey",
    "thanks",
    "thx",
    "在吗",
    "在么",
    "?",
    "？",
    "!",
    "！",
    "…",
    "……",
    "今天",
    "现在",
    "目前",
    "最新",
    "刚刚",
    "最近",
}


# 弱时间词：单独出现时容易误触发（如"我今天好累"）
WEAK_TIME_KEYWORDS = {
    "今天",
    "现在",
    "目前",
    "刚刚",
    "最近",
    "近期",
    "今年",
    "本周",
    "本月",
    "昨天",
    "前几天",
}


# ==================== Rule functions ====================


def is_local_datetime_query(message: str) -> bool:
    """判断是否为本地时间/日期问题，避免不可靠的网页结果。"""

    if not message:
        return False

    text = message.strip()
    if not text:
        return False

    negative_keywords = [
        "新闻",
        "热点",
        "热搜",
        "比赛",
        "结果",
        "比分",
        "赛程",
        "价格",
        "股价",
        "汇率",
        "天气",
        "发布",
        "版本",
        "模型",
    ]
    if any(k in text for k in negative_keywords):
        return False

    compact = re.sub(r"\s+", "", text)

    time_pat = r"(?:现在|当前|此刻|目前)?(?:北京时间|中国时间|本地时间|当地时间)?(?:是)?(?:几点|几时|什么时间|啥时间|几点钟)(?:了)?(?:北京时间|中国时间|本地时间|当地时间)?"
    date_pat = r"(?:今天|现在|当前)?(?:是)?(?:几号|几月几号|什么日期|日期|几号了)"
    weekday_pat = r"(?:今天|现在|当前)?(?:是)?(?:星期几|周几|礼拜几)"

    return bool(
        re.fullmatch(time_pat, compact)
        or re.fullmatch(date_pat, compact)
        or re.fullmatch(weekday_pat, compact)
    )


def normalize_search_query(message: str, bot_names: Optional[List[str]] = None) -> str:
    """规范化搜索 query，去除噪声并保留核心语义。"""

    if not message:
        return ""

    text = str(message).replace("\r\n", "\n").replace("\r", "\n").strip()

    text = re.sub(r"^\s*\[[^\]]+]\s*[:：]\s*", "", text)
    text = re.sub(r"\[CQ:[^\]]+]", " ", text)
    text = re.sub(r"<CQ:[^>]+>", " ", text)
    text = re.sub(r"@\S+\s*", " ", text)

    for _ in range(2):
        new_text = re.sub(r"^\s*\[[^\]]+]\s*[:：]\s*", "", text)
        if new_text == text:
            break
        text = new_text

    filtered_lines = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(">") or stripped.startswith("》"):
            continue
        if re.match(r"^(引用|回复)[:：]", stripped):
            continue
        filtered_lines.append(line)
    text = "\n".join(filtered_lines)

    name_list = [name.strip() for name in (bot_names or []) if isinstance(name, str) and name.strip()]
    if name_list:
        name_pattern = r"^\s*(?:%s)[,，:：\s]+" % "|".join(re.escape(name) for name in name_list)
        text = re.sub(name_pattern, "", text, flags=re.IGNORECASE)

    text = re.sub(
        r"^\s*(?:assistant|bot|ai|机器人|助手|系统|system)[,，:：\s]+",
        "",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"^\s*(?:请问|请|麻烦|麻烦你|帮我|帮忙|帮一下|帮忙查下|帮忙看下|帮忙查一下|能否|可以|想问|想了解)\s*",
        "",
        text,
    )

    text = re.sub(r"(?:谢谢|谢啦|谢了|thanks|thx)\s*$", "", text, flags=re.IGNORECASE)

    text = re.sub(r"[`~^|\\\\]+", " ", text)
    text = re.sub(r"([!?！？。，,；;:：])\1+", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.strip(" \t\n\r,.!?，。！？；;:：-—~`")

    return text


def _has_question_signal(text: str) -> bool:
    if not text:
        return False
    if "?" in text or "？" in text:
        return True
    return any(keyword in text for keyword in QUESTION_KEYWORDS)


def is_low_signal_query(message: str) -> bool:
    """判定 query 是否为低信号，避免触发模糊搜索。"""

    if not message:
        return True

    text = message.strip()
    if not text:
        return True

    lowered = text.lower()
    if lowered in LOW_SIGNAL_TOKENS:
        return True

    if not re.search(r"[A-Za-z0-9\u4e00-\u9fff]", text):
        return True

    if len(text) < _get_min_query_length():
        has_intent_signal = (
            _has_question_signal(text)
            or any(keyword in lowered for keyword in TIMELINESS_KEYWORDS)
            or any(keyword in lowered for keyword in AI_KEYWORDS)
        )
        if not has_intent_signal:
            return True

    return False


def _is_overcompressed_query(query: str, normalized_message: str) -> bool:
    """检测分类器 query 是否被压缩过头（例如仅剩 'iOS'）。"""

    compact_query = (query or "").strip()
    compact_message = (normalized_message or "").strip()
    if not compact_query or not compact_message:
        return False

    min_query_len = _get_min_query_length()

    if len(compact_query) < min_query_len and len(compact_message) >= min_query_len:
        return True

    has_message_constraint = bool(
        re.search(r"\d", compact_message)
        or any(
            kw in compact_message.lower()
            for kw in ("什么时候", "何时", "推送", "版本", "内测", "功能", "beta", "release")
        )
    )
    has_query_constraint = bool(
        re.search(r"\d", compact_query)
        or any(
            kw in compact_query.lower()
            for kw in ("什么时候", "何时", "推送", "版本", "内测", "功能", "beta", "release")
        )
    )
    if len(compact_message) >= 12 and len(compact_query) <= 4 and has_message_constraint and not has_query_constraint:
        return True

    return False


def should_search(message: str) -> bool:
    """检测消息是否需要触发搜索（基于关键词快速匹配）。"""

    clean_message = normalize_search_query(message)
    if is_low_signal_query(clean_message):
        return False

    if is_local_datetime_query(clean_message):
        return False

    msg_lower = clean_message.lower()
    has_question_signal = _has_question_signal(clean_message)

    strong_timeliness_keywords = [kw for kw in TIMELINESS_KEYWORDS if kw not in WEAK_TIME_KEYWORDS]
    if any(keyword in msg_lower for keyword in strong_timeliness_keywords):
        return True

    if any(keyword in msg_lower for keyword in WEAK_TIME_KEYWORDS) and has_question_signal:
        return True

    has_ai_keyword = any(kw in msg_lower for kw in AI_KEYWORDS)
    has_best_keyword = any(kw in msg_lower for kw in BEST_KEYWORDS)
    if has_ai_keyword and has_best_keyword:
        return True

    if has_ai_keyword and ("是什么" in msg_lower or "什么是" in msg_lower):
        return True

    return False


def should_fallback_strong_timeliness(message: str) -> bool:
    """分类失败时的回退：仅命中强时效词才外搜。"""

    clean = normalize_search_query(message)
    if is_low_signal_query(clean):
        log.debug(
            f"[诊断] should_fallback_strong_timeliness: 低信号过滤 | msg='{message[:SHOULD_FALLBACK_MSG_PREVIEW_CHARS]}'"
        )
        return False
    if is_local_datetime_query(clean):
        log.debug(
            f"[诊断] should_fallback_strong_timeliness: 本地时间过滤 | msg='{message[:SHOULD_FALLBACK_MSG_PREVIEW_CHARS]}'"
        )
        return False
    msg_lower = clean.lower()
    strong_timeliness_keywords = [kw for kw in TIMELINESS_KEYWORDS if kw not in WEAK_TIME_KEYWORDS]
    matched_keywords = [kw for kw in strong_timeliness_keywords if kw in msg_lower]
    result = len(matched_keywords) > 0
    log.debug(
        f"[诊断] should_fallback_strong_timeliness | "
        f"result={result} | matched={matched_keywords} | msg='{clean[:50]}'"
    )
    return result


def _resolve_pronoun_query(query: str, context: Optional[list], max_len: int) -> str:
    """检测纯指代性 query 并尝试从上下文提取实体名进行消解。"""

    if not query or not context:
        return query

    pronoun_patterns = [
        r"^那么.+呢$",
        r"^.+呢$",
        r"^它(们)?怎么样",
        r"^这个呢",
        r"^那个呢",
        r"^还有.+呢",
    ]

    is_pronoun_query = any(re.match(p, query) for p in pronoun_patterns)
    if not is_pronoun_query:
        return query

    log.debug(f"检测到指代性 query: '{query}'，尝试从上下文提取实体")

    entity_keywords = [
        "gpt",
        "mika",
        "claude",
        "llama",
        "qwen",
        "deepseek",
        "kimi",
        "chatgpt",
        "gpt-4",
        "gpt-5",
        "mika-2",
        "claude-3",
        "claude-4",
        "iphone",
        "pixel",
        "mac",
        "windows",
        "android",
        "ios",
    ]

    extracted_entities: List[str] = []
    for msg in reversed(context[-PRONOUN_CONTEXT_TAIL_COUNT:]):
        content = msg.get("content", "")
        if not isinstance(content, str):
            continue
        content_lower = content.lower()
        for entity in entity_keywords:
            if entity in content_lower and entity not in [e.lower() for e in extracted_entities]:
                match = re.search(re.escape(entity), content, re.IGNORECASE)
                if match:
                    extracted_entities.append(match.group(0))
                    if len(extracted_entities) >= PRONOUN_ENTITY_MAX_COUNT:
                        break
        if len(extracted_entities) >= PRONOUN_ENTITY_MAX_COUNT:
            break

    if extracted_entities:
        query_keywords = re.sub(r"(那么|呢|怎么样|还有|它们?|这个|那个)", "", query).strip()
        if query_keywords:
            resolved = f"{' '.join(extracted_entities)} {query_keywords}"
        else:
            resolved = " ".join(extracted_entities)
        resolved = resolved[:max_len]
        log.info(f"指代消解: '{query}' -> '{resolved}'")
        return resolved

    return query
