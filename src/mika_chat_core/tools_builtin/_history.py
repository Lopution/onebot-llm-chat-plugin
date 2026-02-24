"""群聊历史搜索工具。"""

from __future__ import annotations

from typing import Any

from ..infra.logging import logger
from ..utils.media_semantics import placeholder_from_content_part
from ..tools import tool, _resolve_tool_override


@tool(
    "search_group_history",
    description="搜索当前会话的历史消息记录。仅用于查询聊天上下文，不用于互联网实时信息。",
    parameters={
        "type": "object",
        "properties": {
            "count": {"type": "integer", "description": "要获取的历史消息数量，默认20，最大50"}
        },
    },
)
async def handle_search_group_history(args: dict, group_id: str) -> str:
    """群聊历史搜索工具（支持宿主覆盖）。"""
    override = _resolve_tool_override("search_group_history")
    if override is not None:
        return await override(args, group_id)

    from mika_chat_core.utils.context_store import get_context_store

    group_id_str = str(group_id or "").strip()
    if not group_id_str:
        return "该工具仅在群聊可用（需要 group_id）。"

    try:
        count = int(args.get("count", 20) if isinstance(args, dict) else 20)
        count = max(1, min(count, 50))

        store = get_context_store()
        history = await store.get_context(user_id="_tool_", group_id=group_id_str)
        if not history:
            return "没有找到历史消息。"

        def _content_to_text(content: Any) -> str:
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts: list[str] = []
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    item_type = item.get("type")
                    if item_type == "text":
                        parts.append(str(item.get("text") or ""))
                    elif item_type == "image_url":
                        parts.append(placeholder_from_content_part(item))
                return " ".join(p for p in parts if p)
            return str(content or "")

        lines: list[str] = []
        for msg in history[-count:]:
            role = str(msg.get("role") or "")
            content_text = _content_to_text(msg.get("content"))
            content_text = content_text.replace("\n", " ").strip()
            if not content_text:
                continue
            if role == "assistant" and not content_text.startswith("["):
                lines.append(f"[assistant]: {content_text}")
            else:
                lines.append(content_text)

        if not lines:
            return "没有找到可用的历史消息。"
        return "以下是查找到的历史消息：\n" + "\n".join(lines)
    except Exception as exc:
        logger.error(f"Failed to search group history: {exc}")
        return f"翻记录时出错了：{str(exc)}"
