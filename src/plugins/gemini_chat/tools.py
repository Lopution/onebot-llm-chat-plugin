# Gemini Chat 插件 - 工具函数
"""工具处理器和辅助函数"""

from typing import Dict, Callable, Any

from nonebot import logger
from nonebot.adapters.onebot.v11 import Message


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
    from nonebot import get_bot, get_plugin_config
    from .config import Config
    
    plugin_config = get_plugin_config(Config)
    
    try:
        count = args.get("count", 20) if isinstance(args, dict) else 20
        count = min(count, 50)
        bot = get_bot()
        res = await bot.get_group_msg_history(group_id=int(group_id), count=count)
        history_list = res.get("messages", []) if isinstance(res, dict) else res
        
        if not history_list:
            return "没有找到历史消息。"
        
        def _segment_to_text(seg: Any) -> str:
            """将 OneBot 消息段转换为可读文本，占位保留非 text 段信息。"""
            seg_type = None
            seg_data: Dict[str, Any] = {}
            if isinstance(seg, dict):
                seg_type = seg.get("type")
                seg_data = seg.get("data") or {}
            else:
                seg_type = getattr(seg, "type", None)
                seg_data = getattr(seg, "data", {}) or {}

            seg_type = str(seg_type or "")

            if seg_type == "text":
                return str(seg_data.get("text", ""))
            if seg_type == "image":
                return "[图片]"
            if seg_type == "at":
                qq = str(seg_data.get("qq", ""))
                return f"@{qq}" if qq else "[@]"
            if seg_type in {"face", "mface"}:
                summary = str(seg_data.get("summary", "表情"))
                return f"[{summary}]" if summary else "[表情]"
            if seg_type == "reply":
                return "[回复]"
            if seg_type == "record":
                return "[语音]"
            if seg_type == "video":
                return "[视频]"
            if seg_type == "file":
                return "[文件]"
            if seg_type == "forward":
                return "[转发]"
            if seg_type:
                return f"[{seg_type}]"
            return "[未知内容]"

        formatted_messages = []
        for msg in history_list:
            sender_id = str(msg.get('user_id') or msg.get('sender', {}).get('user_id', ''))
            if sender_id == str(bot.self_id): continue
            
            nickname = (msg.get('sender', {}).get('card') or msg.get('sender', {}).get('nickname') or sender_id)
            tag = f"⭐{plugin_config.gemini_master_name}" if sender_id == str(plugin_config.gemini_master_id) else nickname
            
            raw_msg = msg.get('message', [])
            msg_text = ""
            if isinstance(raw_msg, str):
                msg_text = raw_msg
            elif isinstance(raw_msg, list):
                for seg in raw_msg:
                    msg_text += _segment_to_text(seg)
            else:
                # 兜底：可能是 Message / 其他结构
                try:
                    for seg in raw_msg:
                        msg_text += _segment_to_text(seg)
                except Exception:
                    msg_text = str(raw_msg)
            
            if msg_text:
                formatted_messages.append(f"[{tag}]: {msg_text}")
        
        return "以下是查找到的历史消息：\n" + "\n".join(formatted_messages[-count:])
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


def extract_images(message: Message, max_images: int = 10):
    """兼容旧 tests：从消息中提取图片 URL。

    实现委派到 [`utils.image_processor.extract_images()`](bot/src/plugins/gemini_chat/utils/image_processor.py:1)。
    """
    from .utils.image_processor import extract_images as _extract

    return _extract(message, max_images=max_images)
