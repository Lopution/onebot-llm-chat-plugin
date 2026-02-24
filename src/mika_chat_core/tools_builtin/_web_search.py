"""Web 搜索工具。"""

from __future__ import annotations

from ..infra.logging import logger
from ..tools import tool


@tool(
    "web_search",
    description="搜索互联网获取实时信息。适用于新闻、天气、价格、赛事等时效性问题。",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词，应简洁明确"}
        },
        "required": ["query"],
    },
)
async def handle_web_search(args: dict, group_id: str = "") -> str:
    """Web 搜索工具处理器。"""
    from ..utils.search_engine import google_search

    query = args.get("query", "") if isinstance(args, dict) else str(args)
    logger.debug(f"执行 web_search | query={query}")
    result = await google_search(query, "", "")
    return result if result else "未找到相关搜索结果"
