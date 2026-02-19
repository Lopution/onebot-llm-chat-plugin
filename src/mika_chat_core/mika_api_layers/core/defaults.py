"""Static defaults for MikaClient."""

from __future__ import annotations

from typing import Any, Dict, List


DEFAULT_ERROR_MESSAGES: Dict[str, str] = {
    "timeout": "呜…{name} 的脑袋转得太慢了，等会儿再试试呢~",
    "rate_limit": "哇…大家都在找 {name} 聊天，有点忙不过来了，稍等一下下好吗？💦",
    "auth_error": "诶？{name} 的身份验证出了点问题，快让 Sensei 帮忙检查一下~",
    "server_error": "服务器那边好像在打瞌睡…再试一次吧~",
    "content_filter": "唔…这个话题 {name} 不太方便回答呢…换个话题吧？",
    "api_error": "诶？好像出了点小问题…{name} 需要休息一下~",
    "unknown": "啊咧？发生了奇怪的事情…再说一次好不好？",
    "empty_reply": "呐，{name} 刚才走神了，能再说一次吗？☆",
}


AVAILABLE_TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "搜索互联网获取实时信息。当用户询问最新新闻、天气、比赛结果、价格、股票、实时事件等时效性信息时使用。注意：不要用于查询群聊历史或对话上下文。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词，应简洁明确",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_group_history",
            "description": "搜索当前群聊的历史消息记录。当用户询问'群里刚才在聊什么'、'之前说了什么'等关于群聊上下文的问题时使用。仅在群聊中可用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "count": {
                        "type": "integer",
                        "description": "要获取的历史消息数量，默认20，最大50",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_history_images",
            "description": "获取历史消息中的图片。当你需要查看之前对话中提到的图片（如表情包、截图）时使用。上下文中带有 <msg_id:xxx> 标记的消息可以通过此工具获取原图。",
            "parameters": {
                "type": "object",
                "properties": {
                    "msg_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "需要获取图片的消息 ID 列表（从上下文中的 <msg_id:xxx> 提取）",
                    },
                    "max_images": {
                        "type": "integer",
                        "description": "最多获取几张图片，默认2，最大2",
                    },
                },
                "required": ["msg_ids"],
            },
        },
    },
]
