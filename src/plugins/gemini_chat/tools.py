"""工具处理器模块。

定义和注册 Gemini API Tool Calling 的工具处理器，包括：
- 工具注册装饰器
- web_search 网络搜索工具
- search_group_history 群聊历史搜索工具
- fetch_history_images 历史图片获取工具

使用示例：
    @tool("my_tool")
    async def handle_my_tool(args: dict, group_id: str = "") -> str:
        return "工具执行结果"
"""

from typing import Any, Callable, Dict

from nonebot import logger


# 工具注册表
TOOL_HANDLERS: Dict[str, Callable] = {}


def tool(name: str):
    """工具注册装饰器
    
    使用方法:
        @tool("web_search")
        async def web_search_handler(args: dict, group_id: str = "") -> str:
            ...
    
    Args:
        name: 工具名称，用于在 TOOL_HANDLERS 中注册
        
    Returns:
        装饰器函数
    """
    def decorator(func: Callable) -> Callable:
        TOOL_HANDLERS[name] = func
        return func
    return decorator


@tool("search_group_history")
async def handle_search_group_history(args: dict, group_id: str) -> str:
    """处理搜索群聊历史的工具调用
    
    Args:
        args: 工具参数字典，包含 count 等参数
        group_id: 群组 ID
        
    Returns:
        格式化的历史消息字符串
    """
    from .utils.context_store import get_context_store

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
                        parts.append("[图片]")
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
    except Exception as e:
        logger.error(f"Failed to search group history: {e}")
        return f"翻记录时出错了：{str(e)}"


@tool("web_search")
async def handle_web_search(args: dict, group_id: str = "") -> str:
    """Web 搜索工具处理器
    
    Args:
        args: 工具参数字典，包含 query 参数
        group_id: 群组 ID（未使用）
        
    Returns:
        搜索结果字符串
    """
    from .utils.search_engine import google_search
    
    query = args.get("query", "") if isinstance(args, dict) else str(args)
    logger.debug(f"执行 web_search | query={query}")
    result = await google_search(query, "", "")
    return result if result else "未找到相关搜索结果"


@tool("fetch_history_images")
async def handle_fetch_history_images(args: dict, group_id: str = "") -> str:
    """获取历史图片工具处理器（两阶段补图）
    
    允许模型根据 msg_id 请求查看特定历史消息中的图片。
    
    Args:
        args: 工具参数字典，包含:
            - msg_ids: List[str] 需要获取图片的消息 ID 列表
            - max_images: int 最多获取几张（可选，默认2）
        group_id: 群组 ID（用于安全验证）
        
    Returns:
        JSON 格式的图片数据或错误信息
    """
    import json
    from nonebot import get_bot, get_plugin_config
    from .config import Config
    from .utils.recent_images import get_image_cache
    from .utils.image_processor import get_image_processor
    
    plugin_config = get_plugin_config(Config)
    max_allowed = plugin_config.gemini_history_image_two_stage_max
    
    try:
        # [安全] 必须提供 group_id，否则拒绝（防止跨场景越权取图）
        group_id_str = str(group_id) if group_id else ""
        if not group_id_str:
            logger.warning("fetch_history_images: group_id 为空，拒绝")
            return json.dumps({"error": "group_id is required", "images": []})

        msg_ids = args.get("msg_ids", []) if isinstance(args, dict) else []
        max_images = min(args.get("max_images", 2), max_allowed) if isinstance(args, dict) else min(2, max_allowed)
        
        if not msg_ids:
            return json.dumps({"error": "No msg_ids provided", "images": []})
        
        # 限制请求数量
        msg_ids = msg_ids[:max_images + 1]  # 允许多请求1个以便有备选
        
        image_cache = get_image_cache()
        processor = get_image_processor()
        
        result_images = []
        
        for msg_id in msg_ids:
            if len(result_images) >= max_images:
                break
            
            # 1. 先从 ImageCache 查找
            cached_images, found = image_cache.get_images_by_message_id(
                group_id=group_id_str,
                user_id="",  # 群聊时 user_id 不重要
                message_id=str(msg_id)
            )
            
            if found and cached_images:
                for img in cached_images:
                    if len(result_images) >= max_images:
                        break
                    try:
                        # 下载并编码图片
                        base64_data, mime_type = await processor.download_and_encode(img.url)
                        result_images.append({
                            "msg_id": msg_id,
                            "sender_name": img.sender_name,
                            "data_url": f"data:{mime_type};base64,{base64_data}"
                        })
                    except Exception as e:
                        logger.warning(f"fetch_history_images: 下载图片失败 | msg_id={msg_id} | error={e}")
                continue
            
            # 2. 缓存未命中，尝试从 OneBot 获取
            # 2. 缓存未命中：谨慎尝试从 OneBot 获取（必须做归属校验）
            try:
                bot = get_bot()
                msg_data = await bot.get_msg(message_id=int(msg_id))

                # OneBot v11 常见字段：message_type/group_id
                if not isinstance(msg_data, dict) or not msg_data:
                    logger.warning(f"fetch_history_images: get_msg 返回非 dict 或空 | msg_id={msg_id}")
                    continue

                msg_type = str(msg_data.get("message_type") or "")
                msg_gid = msg_data.get("group_id")
                if msg_gid is None:
                    # 某些实现可能把群信息放到其他字段（尽力解析）
                    msg_gid = (msg_data.get("group") or {}).get("group_id") if isinstance(msg_data.get("group"), dict) else None

                if msg_gid is None:
                    # 无法验证群归属：按保守策略拒绝（仅允许 cache 命中）
                    logger.warning(
                        f"fetch_history_images: 无法从 get_msg 验证 group_id，按保守策略跳过 | msg_id={msg_id}"
                    )
                    continue

                if str(msg_gid) != group_id_str:
                    logger.warning(
                        f"fetch_history_images: group_id 不匹配，拒绝 | expected={group_id_str} actual={msg_gid} msg_id={msg_id}"
                    )
                    continue

                if msg_type and msg_type != "group":
                    logger.warning(
                        f"fetch_history_images: message_type 非 group，拒绝 | type={msg_type} msg_id={msg_id}"
                    )
                    continue

                sender = msg_data.get("sender", {})
                sender_name = sender.get("card") or sender.get("nickname") or "某人"

                raw_message = msg_data.get("message", [])
                    
                if isinstance(raw_message, list):
                    for seg in raw_message:
                        if len(result_images) >= max_images:
                            break
                        seg_type = seg.get("type") if isinstance(seg, dict) else getattr(seg, "type", None)
                        seg_data = seg.get("data", {}) if isinstance(seg, dict) else getattr(seg, "data", {})

                        if seg_type == "image":
                            img_url = seg_data.get("url") or seg_data.get("file")
                            if img_url:
                                try:
                                    base64_data, mime_type = await processor.download_and_encode(img_url)
                                    result_images.append({
                                        "msg_id": msg_id,
                                        "sender_name": sender_name,
                                        "data_url": f"data:{mime_type};base64,{base64_data}"
                                    })
                                except Exception as e:
                                    logger.warning(
                                        f"fetch_history_images: 下载图片失败 | url={str(img_url)[:50]} | error={e}"
                                    )
            except Exception as e:
                logger.warning(f"fetch_history_images: 获取消息失败 | msg_id={msg_id} | error={e}")
        
        if not result_images:
            return json.dumps({
                "error": "No images found for the requested msg_ids",
                "images": [],
                "hint": "The images may have expired or the msg_ids are invalid."
            })
        
        # 构建映射提示
        mapping_parts = [f"Image {i+1} from <msg_id:{img['msg_id']}> (sent by {img['sender_name']})"
                         for i, img in enumerate(result_images)]
        
        return json.dumps({
            "success": True,
            "count": len(result_images),
            "mapping": mapping_parts,
            "images": [img["data_url"] for img in result_images]
        })
        
    except Exception as e:
        logger.error(f"fetch_history_images: 工具执行失败 | error={e}", exc_info=True)
        return json.dumps({"error": str(e), "images": []})


# extract_images 已移动到 utils.image_processor
# needs_search 和相关常量已废弃，使用 utils.search_engine.should_search


# ==================== 兼容旧 tests 的导出 ====================

# 旧 tests 仍从 gemini_chat.tools 导入这些符号。

from .utils.search_engine import TIME_SENSITIVE_KEYWORDS  # noqa: E402


def needs_search(message: str) -> bool:
    """兼容旧 tests：基于旧关键词策略判断是否需要外部搜索。

    说明：当前推荐使用 [`should_search()`](bot/src/plugins/gemini_chat/utils/search_engine.py:1)。
    """
    from .utils.search_engine import should_search

    return should_search(message)


def extract_images(message: Any, max_images: int = 10):
    """兼容旧 tests：从消息中提取图片 URL。

    实现委派到 [`utils.image_processor.extract_images()`](bot/src/plugins/gemini_chat/utils/image_processor.py:1)。
    """
    from .utils.image_processor import extract_images as _extract

    return _extract(message, max_images=max_images)
