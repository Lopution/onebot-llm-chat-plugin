"""Mika API - 回复清理与安全处理工具。"""

from __future__ import annotations

SANITIZE_REGEX_INPUT_MAX_LENGTH = 4000


def _strip_search_exposure(text: str) -> str:
    import re

    if not text:
        return text

    patterns = [
        r"^(?:根据|通过|我?查到了?|我?搜索到了?|从|在)(?:最新)?(?:的)?(?:搜索|网络|资料|结果|信息|数据).*?[，。,.]\s*",
        r"^我查到.*?[，。,.]\s*",
        r"^(?:人家|Mika|我)(?:刚才|特意)?(?:去|有)?(?:确认|查|搜)(?:了|过)?一下.*?。",
        r"^(?:从|根据)搜索结果(?:来看)?.*?[，。,.]",
    ]

    cleaned = text
    for pattern in patterns:
        if len(cleaned) <= SANITIZE_REGEX_INPUT_MAX_LENGTH:
            cleaned = re.sub(pattern, "", cleaned, flags=re.MULTILINE | re.IGNORECASE)
            continue

        chunks = cleaned.splitlines(keepends=True)
        sanitized_chunks: list[str] = []
        for chunk in chunks:
            prefix = chunk[:SANITIZE_REGEX_INPUT_MAX_LENGTH]
            suffix = chunk[SANITIZE_REGEX_INPUT_MAX_LENGTH:]
            sanitized_chunks.append(re.sub(pattern, "", prefix, flags=re.IGNORECASE) + suffix)
        cleaned = "".join(sanitized_chunks)
    return cleaned


def clean_thinking_markers(text: str) -> str:
    """清理模型回复中的思考标记与搜索暴露前缀。"""
    import re

    if not text:
        return text

    thinking_patterns = [
        r"\*[A-Za-z\s]+(?:\([^)]*\))?:\*\s*",
        r"^\*(?:Thinking|Drafting|Planning|Response|Actual)[^*]*\*:?\s*",
        r"_(?:Thinking|Drafting|Planning)[^_]*_:?\s*",
    ]

    cleaned = text
    for pattern in thinking_patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.MULTILINE | re.IGNORECASE)

    cleaned = _strip_search_exposure(cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()
