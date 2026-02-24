"""搜索分类器 — JSON 解析工具。"""

from __future__ import annotations

from typing import Optional

import re


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
        fixed = fixed.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'")
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
