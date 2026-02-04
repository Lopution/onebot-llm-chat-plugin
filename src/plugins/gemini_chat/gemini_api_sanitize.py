"""Gemini API - 回复清理与安全处理工具。"""

from __future__ import annotations


def clean_thinking_markers(text: str) -> str:
    """
    清理模型回复中泄露的思考过程标记。

    某些模型会在回复中包含推理过程，如：
    - *Drafting the response (Mika style):*
    - *Actual Response Construction:*
    - *Thinking:*

    这些应该被过滤掉，只保留实际回复内容。
    """
    import re

    if not text:
        return text

    # 移除常见的思考过程标记模式
    patterns = [
        # *xxx:* 格式的思考标记
        r"\*[A-Za-z\s]+(?:\([^)]*\))?:\*\s*",
        # 移除以 *Thinking* 或 *Response* 等开头的行
        r"^\*(?:Thinking|Drafting|Planning|Response|Actual)[^*]*\*:?\s*",
        # 移除 markdown 斜体的思考标记
        r"_(?:Thinking|Drafting|Planning)[^_]*_:?\s*",
        # [新增] 移除搜索暴露语句 (Mika 必须保持沉浸感)
        r"^(?:根据|通过|我?查到了?|我?搜索到了?|从|在)(?:最新)?(?:的)?(?:搜索|网络|资料|结果|信息|数据).*?[，。,.]\s*",
        # [Fix] 更宽松地覆盖“我查到/我查到了…”这一类起句（测试期望）
        r"^我查到.*?[，。,.]\s*",
        r"^(?:人家|Mika|我)(?:刚才|特意)?(?:去|有)?(?:确认|查|搜)(?:了|过)?一下.*?。",
        r"^(?:从|根据)搜索结果(?:来看)?.*?[，。,.]",
    ]

    cleaned = text
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.MULTILINE | re.IGNORECASE)

    # 清理多余的空行
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    return cleaned.strip()
