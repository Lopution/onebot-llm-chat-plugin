"""搜索意图分类与 query 规范化模块。

该模块不负责执行外部搜索（网络调用 Serper 等），只负责：
- 文本规范化与低信号过滤
- 关键词快速判定是否应搜索
- 调用 LLM 做主题分类与 query 生成（带缓存）

功能特性：
- 多级判定（关键词 -> 规则 -> LLM）
- 分类结果缓存（降低 LLM 调用成本）
- 可配置的缓存 TTL 和大小限制

注意：
对外接口会通过 [`search_engine`](search_engine.py:1) 重新导出，以保持向后兼容。

相关模块：
- [`search_engine`](search_engine.py:1): 搜索主入口
- [`prompt_loader`](prompt_loader.py:1): 提示词加载
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Tuple

import hashlib
import re
import time

from nonebot import logger as log

from ..config import plugin_config
from .prompt_loader import load_search_prompt


# ==================== Magic-number constants ====================
# 说明：只提取散落数字为命名常量/配置项，不修改业务逻辑。
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


def _get_classify_prompt() -> str:
    """获取分类提示词模板（从 `search.yaml` 读取）。"""

    config = load_search_prompt()
    classify_config = config.get("classify_topic", {})
    return classify_config.get("template", "")


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


def _get_must_search_topics() -> list:
    """获取必须搜索的主题列表。"""

    config = load_search_prompt()
    classify_config = config.get("classify_topic", {})
    return classify_config.get("must_search_topics", [])


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
    if time.time() - ts <= ttl_seconds:
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
    _classify_cache[key] = (value, time.time())


def _get_classify_cache_ttl_seconds() -> int:
    try:
        value = int(
            getattr(plugin_config, "gemini_search_classify_cache_ttl_seconds", CLASSIFY_DEFAULT_CACHE_TTL_SECONDS)
        )
        return max(CLASSIFY_MIN_CACHE_TTL_SECONDS, value)
    except Exception:
        return CLASSIFY_DEFAULT_CACHE_TTL_SECONDS


def _get_classify_cache_max_size() -> int:
    try:
        value = int(getattr(plugin_config, "gemini_search_classify_cache_max_size", CLASSIFY_DEFAULT_CACHE_MAX_SIZE))
        return max(CLASSIFY_MIN_CACHE_MAX_SIZE, value)
    except Exception:
        return CLASSIFY_DEFAULT_CACHE_MAX_SIZE


def _get_classify_temperature() -> float:
    try:
        value = float(getattr(plugin_config, "gemini_search_classify_temperature", CLASSIFY_TEMPERATURE_MIN))
        return max(CLASSIFY_TEMPERATURE_MIN, min(CLASSIFY_TEMPERATURE_MAX, value))
    except Exception:
        return CLASSIFY_TEMPERATURE_MIN


def _get_classify_max_tokens() -> int:
    try:
        value = int(getattr(plugin_config, "gemini_search_classify_max_tokens", CLASSIFY_DEFAULT_MAX_TOKENS))
        return max(CLASSIFY_MIN_MAX_TOKENS, min(CLASSIFY_MAX_MAX_TOKENS, value))
    except Exception:
        return CLASSIFY_DEFAULT_MAX_TOKENS


def _get_classify_max_query_length() -> int:
    """分类器生成的 search_query 最大长度（防注入/降噪）。"""

    try:
        value = int(
            getattr(plugin_config, "gemini_search_classify_max_query_length", CLASSIFY_DEFAULT_MAX_QUERY_LENGTH)
        )
        return max(CLASSIFY_MIN_MAX_QUERY_LENGTH, min(CLASSIFY_MAX_MAX_QUERY_LENGTH, value))
    except Exception:
        return CLASSIFY_DEFAULT_MAX_QUERY_LENGTH


def _get_query_normalize_bot_names() -> List[str]:
    """用于 `normalize_search_query` 的机器人名列表（用于去除用户 @/称呼 等噪声）。"""

    names: List[str] = []
    try:
        display_name = getattr(plugin_config, "gemini_bot_display_name", "")
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
    "gemini",
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


def _get_min_query_length() -> int:
    """从配置读取最小 query 长度（提供安全兜底）。"""

    try:
        value = int(getattr(plugin_config, "gemini_search_min_query_length", MIN_QUERY_LENGTH_DEFAULT))
        return max(MIN_QUERY_LENGTH_FLOOR, value)
    except Exception:
        return MIN_QUERY_LENGTH_DEFAULT


# 弱时间词：单独出现时容易误触发（如“我今天好累”）
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
        "gemini",
        "claude",
        "llama",
        "qwen",
        "deepseek",
        "kimi",
        "chatgpt",
        "gpt-4",
        "gpt-5",
        "gemini-2",
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


def _extract_json_object(text: Optional[str]) -> Optional[dict]:
    """从文本中提取第一个有效的 JSON 对象。"""

    import ast
    import json

    if not text:
        return None

    def _strip_invisible(s: str) -> str:
        return (
            s.replace("\ufeff", "")
            .replace("\u200b", "")
            .replace("\u200c", "")
            .replace("\u200d", "")
            .replace("\u2060", "")
        )

    def _try_parse_obj(s: str) -> Optional[dict]:
        if not s:
            return None
        s = _strip_invisible(s).strip()
        if not s:
            return None

        try:
            obj = json.loads(s)
            return obj if isinstance(obj, dict) else None
        except Exception:
            pass

        fixed = s
        fixed = fixed.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
        fixed = re.sub(r",\s*([}\]])", r"\1", fixed)
        try:
            obj = json.loads(fixed)
            return obj if isinstance(obj, dict) else None
        except Exception:
            pass

        py_like = re.sub(r"\btrue\b", "True", fixed, flags=re.IGNORECASE)
        py_like = re.sub(r"\bfalse\b", "False", py_like, flags=re.IGNORECASE)
        py_like = re.sub(r"\bnull\b", "None", py_like, flags=re.IGNORECASE)
        try:
            obj = ast.literal_eval(py_like)
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None

    def _extract_first_braced_object(s: str) -> Optional[str]:
        if not s:
            return None
        in_string = False
        escape = False
        brace_count = 0
        start_idx = -1
        for i, ch in enumerate(s):
            if escape:
                escape = False
                continue
            if ch == "\\":
                if in_string:
                    escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                if brace_count == 0:
                    start_idx = i
                brace_count += 1
            elif ch == "}":
                if brace_count > 0:
                    brace_count -= 1
                    if brace_count == 0 and start_idx >= 0:
                        return s[start_idx : i + 1]
        return None

    raw = _strip_invisible(str(text))

    code_blocks = re.findall(r"```\s*(?:json)?\s*([\s\S]*?)\s*```", raw, flags=re.IGNORECASE)
    for block in code_blocks:
        obj = _try_parse_obj(block)
        if obj is not None:
            return obj
        candidate = _extract_first_braced_object(block)
        if candidate:
            obj = _try_parse_obj(candidate)
            if obj is not None:
                return obj

    clean_text = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
    clean_text = re.sub(r"```\s*$", "", clean_text.strip())

    obj = _try_parse_obj(clean_text)
    if obj is not None:
        return obj

    candidate = _extract_first_braced_object(clean_text)
    if candidate:
        obj = _try_parse_obj(candidate)
        if obj is not None:
            return obj

    json_match = re.search(r"\{(?s:.)*?\"needs_search\"\s*:\s*(true|false)", clean_text)
    if json_match:
        partial_json = clean_text[json_match.start() :]
        if not partial_json.rstrip().endswith("}"):
            open_braces = partial_json.count("{") - partial_json.count("}")
            if partial_json.count('"') % 2 == 1:
                partial_json += '"'
            partial_json += "}" * max(0, open_braces)
        obj = _try_parse_obj(partial_json)
        if obj is not None:
            return obj

    return None


async def classify_topic_for_search(
    message: str,
    api_key: str,
    base_url: str,
    context: list = None,
    model: str = "gemini-3-flash",
) -> tuple[bool, str, str]:
    """使用 LLM 分析问题，智能判断是否需要搜索并生成优化查询。"""

    import httpx
    import json

    bot_names = _get_query_normalize_bot_names()
    normalized_message = normalize_search_query(message, bot_names=bot_names)

    context_section = ""
    if context and len(context) > 0:
        context_lines = []
        for msg in context[-PRONOUN_CONTEXT_TAIL_COUNT:]:
            role = "用户" if msg.get("role") == "user" else "助手"
            content = msg.get("content", "")
            if isinstance(content, str) and content:
                short_content = (
                    content[:CLASSIFY_CONTEXT_ITEM_PREVIEW_CHARS] + "..."
                    if len(content) > CLASSIFY_CONTEXT_ITEM_PREVIEW_CHARS
                    else content
                )
                context_lines.append(f"{role}: {short_content}")
        if context_lines:
            context_section = "最近对话历史:\n" + "\n".join(context_lines) + "\n\n"

    current_time = datetime.now().strftime("%Y-%m-%d")
    current_year = datetime.now().year

    classify_prompt = _get_classify_prompt()
    if not classify_prompt:
        log.warning("分类提示词加载失败，使用默认")
        classify_prompt = CLASSIFY_PROMPT_DEFAULT

    prompt = classify_prompt.format(
        context_section=context_section,
        question=normalized_message,
        current_time=current_time,
        current_year=current_year,
    )

    log.debug(
        f"开始智能分类 | message='{message[:CLASSIFY_LOG_MESSAGE_PREVIEW_CHARS]}' | context_len={len(context) if context else 0}"
    )

    cache_key = _get_classify_cache_key(message, context=context)
    cached = _get_cached_classify_result(cache_key, _get_classify_cache_ttl_seconds())
    if cached is not None:
        needs_search, topic, search_query = cached
        log.debug(f"分类判定缓存命中 | needs_search={needs_search} | topic={topic}")
        return needs_search, topic, search_query

    try:
        classify_max_tokens = _get_classify_max_tokens()
        classify_temperature = _get_classify_temperature()
        log.debug(
            f"[诊断] 分类器参数 | max_tokens={classify_max_tokens} | "
            f"temperature={classify_temperature} | model={model}"
        )

        async with httpx.AsyncClient(timeout=CLASSIFY_HTTP_TIMEOUT_SECONDS) as client:
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"请分析以下用户消息并输出 JSON 判定结果：\n{normalized_message}"},
            ]

            request_body = {
                "model": model,
                "messages": messages,
                "stream": False,
                "max_tokens": classify_max_tokens,
                "temperature": classify_temperature,
                "response_format": {"type": "json_object"},
            }

            log.info(
                f"[分类器请求] model={model} | messages_count={len(messages)} | "
                f"system_len={len(prompt)} | user_msg='{normalized_message[:CLASSIFY_LOG_USER_MSG_PREVIEW_CHARS]}...'"
            )

            def _sanitize_body_for_log(body: dict) -> dict:
                b = dict(body)
                msgs = b.get("messages")
                if isinstance(msgs, list):
                    summarized = []
                    for m in msgs:
                        role = m.get("role") if isinstance(m, dict) else None
                        content = ""
                        if isinstance(m, dict):
                            content = str(m.get("content") or "")
                        summarized.append(
                            {
                                "role": role,
                                "content_len": len(content),
                                "content_preview": (
                                    (content[:CLASSIFY_LOG_BODY_CONTENT_PREVIEW_CHARS] + "...")
                                    if len(content) > CLASSIFY_LOG_BODY_CONTENT_PREVIEW_CHARS
                                    else content
                                ),
                            }
                        )
                    b["messages"] = summarized
                return b

            try:
                log.debug(
                    "分类请求体: %s",
                    json.dumps(_sanitize_body_for_log(request_body), ensure_ascii=False),
                )
            except Exception:
                log.debug(
                    "分类请求体(关键字段): model=%s response_format=%s",
                    request_body.get("model"),
                    request_body.get("response_format"),
                )

            async def _post_classify(body: dict) -> httpx.Response:
                return await client.post(
                    f"{base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )

            used_response_format = "response_format" in request_body
            did_downgrade = False

            response = await _post_classify(request_body)
            log.debug(f"分类响应状态码: {response.status_code}")

            if (
                response.status_code >= 400
                and response.status_code < 500
                and "response_format" in request_body
            ):
                response_text = (
                    response.text[:RESPONSE_FORMAT_DOWNGRADE_ERROR_PREVIEW_CHARS]
                    if response.text
                    else "无内容"
                )
                log.warning(
                    f"主题分类 response_format 可能不兼容，降级重试 | "
                    f"status={response.status_code} | {response_text}"
                )
                downgraded_body = request_body.copy()
                downgraded_body.pop("response_format", None)
                response = await _post_classify(downgraded_body)
                did_downgrade = True
                log.debug(f"分类响应状态码(降级后): {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                choice = data.get("choices", [{}])[0]
                finish_reason = choice.get("finish_reason", "unknown")
                content = choice.get("message", {}).get("content")
                raw_content = (content or "").strip()

                log.info(
                    f"[分类器响应] finish_reason={finish_reason} | "
                    f"content_len={len(raw_content)} | raw_content='{raw_content[:CLASSIFY_LOG_RESPONSE_PREVIEW_CHARS]}'"
                )

                if finish_reason == "length":
                    log.warning(
                        f"分类响应被 max_tokens 截断 | finish_reason=length | "
                        f"content_len={len(raw_content)} | max_tokens={classify_max_tokens}"
                    )

                log_content = (
                    raw_content[:CLASSIFY_LOG_RAW_CONTENT_LONG_PREVIEW_CHARS] + "..."
                    if len(raw_content) > CLASSIFY_LOG_RAW_CONTENT_LONG_PREVIEW_CHARS
                    else raw_content
                )
                log.debug(f"分类原始响应: {log_content}")

                if not raw_content:
                    log.warning("主题分类返回空内容")
                    return False, "未知", ""

                result = _extract_json_object(raw_content)

                if (not result) and used_response_format and (not did_downgrade):
                    log.warning(
                        "主题分类 JSON mode 可能被忽略/未生效，尝试去除 response_format 再请求一次"
                    )
                    downgraded_body = request_body.copy()
                    downgraded_body.pop("response_format", None)
                    response2 = await _post_classify(downgraded_body)
                    log.debug(f"分类响应状态码(解析失败后降级重试): {response2.status_code}")
                    if response2.status_code == 200:
                        try:
                            data2 = response2.json()
                            content2 = data2.get("choices", [{}])[0].get("message", {}).get("content")
                            raw_content = (content2 or "").strip()
                            log_content2 = (
                                raw_content[:CLASSIFY_LOG_RAW_CONTENT_LONG_PREVIEW_CHARS] + "..."
                                if len(raw_content) > CLASSIFY_LOG_RAW_CONTENT_LONG_PREVIEW_CHARS
                                else raw_content
                            )
                            log.debug(f"分类原始响应(降级重试): {log_content2}")
                            result = _extract_json_object(raw_content)
                        except Exception as e:
                            log.warning(f"主题分类降级重试解析异常: {type(e).__name__}: {e}")

                if result:
                    needs_search = result.get("needs_search", False)
                    topic = result.get("topic", "未知")
                    search_query = result.get("search_query", "")

                    max_query_len = _get_classify_max_query_length()
                    clean_search_query = normalize_search_query(str(search_query or ""), bot_names=bot_names)
                    clean_search_query = clean_search_query[:max_query_len]

                    if not clean_search_query:
                        log.debug("search_query 为空或清洗后无效，回退到 normalized_message")
                        clean_search_query = (normalized_message or "")[:max_query_len]

                    if not needs_search:
                        clean_search_query = ""

                    log.success(
                        f"智能分类成功: topic='{topic}' | needs_search={needs_search} | query='{clean_search_query}'"
                    )
                    _set_classify_cache(
                        cache_key,
                        (needs_search, topic, clean_search_query),
                        _get_classify_cache_max_size(),
                    )
                    return needs_search, topic, clean_search_query

                log.warning(
                    f"JSON 提取失败，尝试正则兜底 | raw_len={len(raw_content)} | "
                    f"raw_content='{raw_content}'"
                )

                if len(raw_content) < MIN_VALID_RESPONSE_LEN:
                    log.warning(
                        f"响应过短（{len(raw_content)} < {MIN_VALID_RESPONSE_LEN}），"
                        f"疑似模型输出被截断或异常，采用保守策略"
                    )
                    return False, "响应过短", ""

                needs_search_match = re.search(
                    r'"needs_search"\s*:\s*(true|false)', raw_content, re.IGNORECASE
                )
                if needs_search_match:
                    needs_search_val = needs_search_match.group(1).lower() == "true"

                    query_match = re.search(r'"search_query"\s*:\s*"([^"]*)', raw_content)
                    extracted_query = query_match.group(1) if query_match else ""

                    max_query_len = _get_classify_max_query_length()
                    extracted_query = normalize_search_query(str(extracted_query or ""), bot_names=bot_names)
                    extracted_query = extracted_query[:max_query_len]

                    if len(extracted_query) < 2:
                        extracted_query = (normalized_message or "")[:max_query_len]

                    extracted_query = _resolve_pronoun_query(extracted_query, context, max_query_len)

                    log.info(
                        f"正则兜底成功: needs_search={needs_search_val} | query='{extracted_query}'"
                    )
                    _set_classify_cache(
                        cache_key,
                        (needs_search_val, "正则提取", extracted_query),
                        _get_classify_cache_max_size(),
                    )
                    return needs_search_val, "正则提取", extracted_query

                log.warning("正则提取失败，回退到关键词匹配")
                needs_search = any(must_topic in raw_content for must_topic in MUST_SEARCH_TOPICS)
                max_query_len = _get_classify_max_query_length()
                result_tuple = (
                    needs_search,
                    "关键词匹配",
                    (normalized_message or "")[:max_query_len],
                )
                _set_classify_cache(cache_key, result_tuple, _get_classify_cache_max_size())
                return result_tuple

            response_text = response.text[:200] if response.text else "无内容"
            log.warning(f"主题分类请求失败: {response.status_code} | {response_text}")
            return False, "未知", ""

    except Exception as e:
        log.warning(f"主题分类异常: {type(e).__name__}: {e}")
        return False, "未知", ""
