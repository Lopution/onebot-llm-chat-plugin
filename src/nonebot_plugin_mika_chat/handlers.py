"""消息处理器模块。

处理私聊和群聊消息的核心逻辑，包括：
- 私聊消息处理（自动回复）
- 群聊 @ 消息处理
- 主动发言判断与触发
- 图片提取与历史图片上下文增强
- 会话锁管理（防止并发冲突）

相关模块：
- [`matchers`](matchers.py:1): 事件匹配器定义
- [`lifecycle`](lifecycle.py:1): 插件生命周期管理
"""

import asyncio
import base64
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from nonebot import get_driver

from .config import Config
from .utils.image_processor import extract_images, resolve_image_urls, extract_and_resolve_images
from .deps import get_gemini_client_dep, get_config
from nonebot import logger as log
from .utils.recent_images import get_image_cache
from .utils.history_image_policy import (
    determine_history_image_action,
    build_image_mapping_hint,
    build_candidate_hint,
    HistoryImageAction,
)
from .utils.image_collage import create_collage_from_urls, is_collage_available
from .metrics import metrics
from .utils.session_lock import get_session_lock_manager
from .utils.safe_api import safe_call_api, safe_send
from .utils.event_context import build_event_context
from .utils.text_image_renderer import render_text_to_png_bytes
from .utils.nb_types import BotT

# 获取 driver 实例
driver = get_driver()


@dataclass
class RequestContextPayload:
    """统一的请求上下文载荷。"""

    ctx: Any
    message_text: str
    image_urls: List[str]
    reply_images: List[str]


@dataclass
class SendStageResult:
    """发送阶段结果。"""

    ok: bool
    method: str
    error: str = ""


def _make_session_key(*, user_id: str, group_id: Optional[str]) -> str:
    """与 SQLiteContextStore 的 key 规则对齐，确保同一会话串行。"""
    if group_id:
        return f"group:{group_id}"
    return f"private:{user_id}"


def _cfg(plugin_config: Config, key: str, default: Any) -> Any:
    """读取配置项并提供稳定默认值（不修改配置对象本身）。"""
    value = getattr(plugin_config, key, default)
    return default if value is None else value


async def _resolve_onebot_v12_image_urls(
    bot: BotT,
    event: Any,
    image_urls: list[str],
    *,
    max_images: int,
) -> list[str]:
    """best-effort 把 OneBot v12 的 image.file_id 解析为 http(s) URL。

    说明：为了保持既有测试的可 patch 性，这里仍以 :func:`extract_images` 作为主提取器，
    再补充通过 ``get_file`` 解析 file_id 的逻辑。
    """
    if max_images <= 0:
        return image_urls
    resolved = await extract_and_resolve_images(
        bot,
        getattr(event, "original_message", None),
        max_images=max_images,
    )
    merged: List[str] = []
    for url in [*(image_urls or []), *resolved]:
        if url and url not in merged:
            merged.append(url)
        if len(merged) >= max_images:
            break
    return merged


async def build_request_context_payload(
    bot: BotT,
    event: Any,
    plugin_config: Config,
) -> RequestContextPayload:
    """统一构建一次请求的输入上下文（文本 + 图片 + 引用图片）。"""
    ctx = build_event_context(bot, event)
    max_images = max(0, int(_cfg(plugin_config, "gemini_max_images", 10) or 10))

    message_text = (ctx.plaintext or "").strip()
    reply_images: List[str] = []

    if ctx.is_group:
        message_text, reply_images = await parse_message_with_mentions(
            bot,
            event,
            max_images=max_images,
            quote_image_caption_enabled=bool(
                _cfg(plugin_config, "gemini_quote_image_caption_enabled", True)
            ),
            quote_image_caption_prompt=str(
                _cfg(plugin_config, "gemini_quote_image_caption_prompt", "[引用图片共{count}张]")
            ),
            quote_image_caption_timeout_seconds=float(
                _cfg(plugin_config, "gemini_quote_image_caption_timeout_seconds", 3.0)
            ),
        )
        if not message_text:
            message_text = (ctx.plaintext or "").strip()

    image_urls = extract_images(getattr(event, "original_message", None), max_images)
    image_urls = await _resolve_onebot_v12_image_urls(
        bot,
        event,
        image_urls,
        max_images=max_images,
    )

    if reply_images:
        image_urls = list(dict.fromkeys([*image_urls, *reply_images]))
        log.info(
            f"[上下文载荷] 引用图片已注入 | session={ctx.session_key} | reply_images={len(reply_images)}"
        )
    elif ctx.is_group:
        log.debug(f"[上下文载荷] 引用图片未命中 | session={ctx.session_key}")

    return RequestContextPayload(
        ctx=ctx,
        message_text=message_text,
        image_urls=image_urls,
        reply_images=reply_images,
    )


def _render_transcript_content(content: Any) -> str:
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type == "text":
                parts.append(str(item.get("text") or ""))
            elif item_type == "image_url":
                parts.append("[图片]")
        text = " ".join(p for p in parts if p)
    else:
        text = str(content or "")
    return " ".join(text.split())


def _build_proactive_chatroom_injection(
    history: List[Dict[str, Any]],
    *,
    bot_name: str,
    max_lines: int,
    trigger_message: str = "",
    trigger_sender: str = "",
) -> str:
    if max_lines <= 0:
        return ""

    import re

    lines: List[str] = []
    for msg in (history or [])[-max_lines:]:
        role = msg.get("role")
        content = _render_transcript_content(msg.get("content"))
        if not content:
            continue

        # 尽量把一条消息压成一行，避免 transcript 过长
        content = content.replace("\n", " ").strip()
        if len(content) > 200:
            content = content[:200] + "…"

        if role == "assistant":
            lines.append(f"{bot_name}: {content}")
            continue

        m = re.match(r"^\[(.*?)\]:\s*(.*)$", content)
        if m:
            speaker = (m.group(1) or "").strip()
            said = (m.group(2) or "").strip()
            if speaker and said:
                lines.append(f"{speaker}: {said}")
                continue

        lines.append(content)

    transcript = "\n".join(lines).strip()
    if not transcript:
        transcript = "(无最近记录)"

    # 构建触发消息标记（参考 AstrBot 的实现）
    trigger_marker = ""
    if trigger_message:
        trigger_preview = trigger_message[:150] + "..." if len(trigger_message) > 150 else trigger_message
        sender_label = trigger_sender if trigger_sender else "某位群友"
        trigger_marker = f"\n---\nNow, a new message is coming from {sender_label}: `{trigger_preview}`"

    return (
        "[System Instruction - Chatroom Transcript]\n"
        "下面是最近的群聊记录，用于理解聊天氛围与上下文。\n"
        f"{transcript}"
        f"{trigger_marker}\n"
        "[End Transcript]\n"
        "请根据群聊上下文，自然地回应上面标记的新消息。可以适当结合正在讨论的话题。\n"
        "回复语言：优先使用触发消息的语言；若不确定，使用上述记录最后几条消息的主要语言。"
    )

# ==================== 兼容旧测试的导出（thin wrapper） ====================

def get_gemini_client():
    """兼容旧 tests：历史上测试 patch `gemini_chat.handlers.get_gemini_client`。

    当前实现使用依赖注入入口 [`get_gemini_client_dep()`](bot/src/plugins/gemini_chat/deps.py:1)。
    """
    return get_gemini_client_dep()


def get_user_profile_store():
    """兼容旧 tests：历史上测试会 patch `gemini_chat.handlers.get_user_profile_store`。

    当前实现的真实入口在 [`utils.user_profile.get_user_profile_store()`](bot/src/plugins/gemini_chat/utils/user_profile.py:1)。
    """
    from .utils.user_profile import get_user_profile_store as _get

    return _get()

def _handle_task_exception(task: asyncio.Task[Any]) -> None:
    """处理后台任务的异常，防止异常被静默忽略"""
    if task.done() and not task.cancelled():
        exc = task.exception()
        if exc:
            log.error(f"后台任务异常: {exc}", exc_info=exc)


@driver.on_bot_connect
async def sync_offline_messages(bot: BotT):
    """Bot 启动时同步离线期间的群聊消息（后台异步执行）"""
    import asyncio
    task = asyncio.create_task(_sync_offline_messages_task(bot))
    task.add_done_callback(_handle_task_exception)


async def _sync_offline_messages_task(bot: BotT):
    """同步离线消息的具体逻辑"""
    # 使用依赖注入获取配置和客户端
    plugin_config = get_config()

    if not bool(getattr(plugin_config, "gemini_offline_sync_enabled", False)):
        log.info("离线消息同步已关闭，跳过")
        return
        
    if not plugin_config.gemini_group_whitelist:
        log.info("未配置白名单群组，跳过离线消息同步")
        return

    # 等待一小会儿，确保连接完全建立
    import asyncio
    await asyncio.sleep(5)

    log.info("开始同步离线消息 (后台任务)...")
    gemini_client = get_gemini_client()
    
    # 检查是否使用持久化存储（虽然 public API 对外透明，但非持久化无需同步）
    if not gemini_client.is_persistent:
        log.warning("未启用持久化存储，跳过离线消息同步")
        return
        
    for group_id in plugin_config.gemini_group_whitelist:
        try:
            # 1. 获取当前 Context 中已有的消息 ID 集合
            # 使用公共 API 获取上下文
            # 对于群聊，user_id 传入占位符即可，因为 Key 由 group_id 决定
            existing_context = await gemini_client.get_context(user_id="_sync_", group_id=str(group_id))
            existing_ids = set()
            for msg in existing_context:
                # 兼容 MessageDict 和 Dict
                if "message_id" in msg:
                    existing_ids.add(str(msg["message_id"]))
            
            # 2. 获取 OneBot 历史消息
            # 注意：get_group_msg_history 并非所有实现都支持；这里做 best-effort 并在失败时跳过
            res = await safe_call_api(
                bot,
                "get_group_msg_history",
                group_id=group_id,
                message_count=plugin_config.gemini_history_count,
            )
            if res is None:
                res = await safe_call_api(
                    bot,
                    "get_group_msg_history",
                    group_id=group_id,
                    count=plugin_config.gemini_history_count,
                )
            messages = (res.get("messages", []) if isinstance(res, dict) else res) or []
            
            if not messages:
                continue
                
            new_messages_count = 0
            
            # 确保消息列表按时间正序排列
            # time 字段通常是 unix timestamp
            messages.sort(key=lambda x: x.get("time", 0))
            
            for msg in messages:
                msg_id = str(msg.get("message_id", ""))
                if not msg_id:
                    continue
                    
                if msg_id in existing_ids:
                    continue
                    
                # 这是一个新消息
                user_id = str(msg.get("user_id"))
                raw_message = msg.get("raw_message", "") or msg.get("message", "")
                
                # 忽略机器人自己发的消息
                sender_uin = str(msg.get("sender", {}).get("user_id", ""))
                if sender_uin == bot.self_id:
                     continue
                
                if not raw_message:
                    continue
                
                # 构建带有用户标签的消息内容，保持格式一致
                nickname = msg.get("sender", {}).get("card", "") or msg.get("sender", {}).get("nickname", "")
                tag = f"{nickname}({user_id})"
                formatted_message = f"[{tag}]: {raw_message}"
                
                msg_time = msg.get("time") # 获取消息时间戳
                
                # 写入 Context
                # 使用公共 API add_message
                await gemini_client.add_message(
                    user_id=user_id,
                    role="user",
                    content=formatted_message,
                    group_id=str(group_id),
                    message_id=msg_id,
                    timestamp=msg_time
                )
                new_messages_count += 1
                
            if new_messages_count > 0:
                log.success(f"群 {group_id} 离线消息同步完成 | 新增 {new_messages_count} 条")
            else:
                log.debug(f"群 {group_id} 无需同步 (最新)")
            
        except Exception as e:
            log.warning(f"同步群 {group_id} 消息失败: {e}")



async def handle_reset(
    bot: BotT,
    event: Any,
    plugin_config: Config = None,
    gemini_client = None,
):
    """处理清空记忆指令
    
    Args:
        bot: BotT 实例
        event: 消息事件
        plugin_config: 插件配置（可选，默认通过依赖注入获取）
        gemini_client: API 客户端（可选，默认通过依赖注入获取）
    """
    # 使用依赖注入获取资源（如果未提供）
    if plugin_config is None:
        plugin_config = get_config()
    if gemini_client is None:
        gemini_client = get_gemini_client()

    ctx = build_event_context(bot, event)
    user_id = ctx.user_id
    group_id = ctx.group_id
    session_key = ctx.session_key
    
    log.info(f"收到清空记忆指令 | user={user_id} | group={group_id or 'private'}")
    
    # 使用异步方法支持持久化存储
    lock = get_session_lock_manager().get_lock(session_key)
    async with lock:
        await gemini_client.clear_context_async(user_id, group_id)
        
        log.success(f"记忆已清空 | user={user_id} | group={group_id or 'private'}")
        await bot.send(event, "好的呢~ Mika 把刚才聊的内容都忘掉啦，我们重新开始吧~")


async def handle_private(
    bot: BotT,
    event: Any,
    plugin_config: Config = None,
    gemini_client = None,
):
    """处理私聊消息。

    当用户向机器人发送私聊消息时调用此函数。
    会自动提取文本和图片，构建带用户标签的消息，并调用 Gemini API 获取回复。

    Args:
        bot: NoneBot Bot 实例，用于发送回复消息。
        event: 私聊消息事件，包含用户 ID、消息内容等信息。
        plugin_config: 插件配置对象（可选，默认通过依赖注入获取）。
        gemini_client: API 客户端（可选，默认通过依赖注入获取）。

    Note:
        - 如果 gemini_reply_private 配置为 False，则直接返回不处理
        - 主人（master）发送的消息会被标记为 "⭐Sensei"
        - 支持多模态消息（文本 + 图片）
        - 长文本回复会自动转为转发消息发送
    """
    # 使用依赖注入获取资源（如果未提供）
    if plugin_config is None:
        plugin_config = get_config()
    
    if not plugin_config.gemini_reply_private:
        return

    ctx = build_event_context(bot, event)
    session_key = ctx.session_key
    lock = get_session_lock_manager().get_lock(session_key)
    async with lock:
        await _handle_private_locked(bot=bot, event=event, plugin_config=plugin_config, gemini_client=gemini_client)


async def _handle_private_locked(
    *,
    bot: BotT,
    event: Any,
    plugin_config: Config,
    gemini_client,
) -> None:
    payload = await build_request_context_payload(bot, event, plugin_config)
    ctx = payload.ctx
    message_text = payload.message_text
    image_urls = payload.image_urls

    if not message_text and not image_urls:
        return

    if gemini_client is None:
        gemini_client = get_gemini_client()
    
    user_id = ctx.user_id
    # 兼容旧行为（tests 依赖）：
    # - 普通私聊用户使用 [私聊用户]:
    # - 主人私聊使用 [⭐Sensei]:（master_name 不可用时回退为 Sensei）
    is_master = False
    try:
        is_master = int(ctx.user_id) == int(plugin_config.gemini_master_id)
    except Exception:
        is_master = False

    master_name = getattr(plugin_config, "gemini_master_name", "Sensei")
    if not isinstance(master_name, str) or not master_name.strip():
        master_name = "Sensei"

    tag = f"⭐{master_name}" if is_master else "私聊用户"

    # LLM 用户档案抽取（后台异步，不阻塞主流程）
    try:
        import asyncio
        from .utils.user_profile_extract_service import get_user_profile_extract_service

        svc = get_user_profile_extract_service()
        svc.ingest_message(
            qq_id=user_id,
            nickname=tag,  # 私聊没有 card/nickname，沿用 tag
            content=message_text,
            message_id=str(ctx.message_id or ""),
            group_id=None,
        )
    except Exception as e:
        log.warning(f"私聊档案抽取 ingest 失败: {e}")
    
    # 处理图片缓存 - 使用新的 hybrid 策略
    image_cache = get_image_cache()
    cached_hint = None
    
    if image_urls:
        # 当前消息包含图片，缓存它们
        nickname = "Sensei"  # 私聊统一使用 Sensei 称谓
        image_cache.cache_images(
            group_id=None,
            user_id=user_id,
            image_urls=image_urls,
            sender_name=nickname,
            message_id=str(ctx.message_id or "")
        )
    else:
        # 使用 hybrid 策略处理历史图片
        candidate_images = image_cache.peek_recent_images(
            group_id=None,
            user_id=user_id,
            limit=int(_cfg(plugin_config, "gemini_history_image_collage_max", 4))
        )
        
        decision = determine_history_image_action(
            message_text=message_text,
            candidate_images=candidate_images,
            context_messages=None,  # 私聊暂不传上下文
            mode=str(_cfg(plugin_config, "gemini_history_image_mode", "hybrid")),
            inline_max=int(_cfg(plugin_config, "gemini_history_image_inline_max", 1)),
            two_stage_max=int(_cfg(plugin_config, "gemini_history_image_two_stage_max", 2)),
            collage_max=int(_cfg(plugin_config, "gemini_history_image_collage_max", 4)),
            enable_collage=bool(_cfg(plugin_config, "gemini_history_image_enable_collage", True)),
            custom_keywords=_cfg(plugin_config, "gemini_history_image_trigger_keywords", []) or None,
        )
        
        if decision.action == HistoryImageAction.INLINE:
            # 直接回注原图
            image_urls = [img.url for img in decision.images_to_inject]
            cached_hint = build_image_mapping_hint(decision.images_to_inject)
            metrics.history_image_inline_used_total += 1
            metrics.history_image_images_injected_total += len(image_urls)
            log.info(f"[历史图片] INLINE | user={user_id} | images={len(image_urls)} | reason={decision.reason}")
            
        elif decision.action == HistoryImageAction.COLLAGE and is_collage_available():
            # 拼图后注入
            collage_urls = [img.url for img in decision.images_to_inject]
            collage_result = await create_collage_from_urls(
                collage_urls,
                target_max_px=int(
                    _cfg(plugin_config, "gemini_history_image_collage_target_px", 768)
                )
            )
            if collage_result:
                base64_data, mime_type = collage_result
                # 将拼图作为单张图片注入（需要在 build_messages 中特殊处理）
                # 这里暂时使用一个标记 URL
                image_urls = [f"data:{mime_type};base64,{base64_data}"]
                cached_hint = build_image_mapping_hint(decision.images_to_inject)
                metrics.history_image_collage_used_total += 1
                metrics.history_image_images_injected_total += len(decision.images_to_inject)
                log.info(f"[历史图片] COLLAGE | user={user_id} | images={len(collage_urls)} | reason={decision.reason}")
            else:
                # 拼图失败，回退到 inline
                inline_max = int(_cfg(plugin_config, "gemini_history_image_inline_max", 1))
                image_urls = [img.url for img in decision.images_to_inject[:inline_max]]
                cached_hint = build_image_mapping_hint(decision.images_to_inject[:inline_max])
                metrics.history_image_inline_used_total += 1
                metrics.history_image_images_injected_total += len(image_urls)
                log.warning(f"[历史图片] COLLAGE失败回退INLINE | user={user_id} | images={len(image_urls)}")
                
        elif decision.action == HistoryImageAction.TWO_STAGE:
            # 两阶段模式：只提供候选 msg_id 列表提示
            cached_hint = build_candidate_hint(decision.candidate_msg_ids)
            metrics.history_image_two_stage_triggered_total += 1
            log.info(f"[历史图片] TWO_STAGE | user={user_id} | candidates={len(decision.candidate_msg_ids)} | reason={decision.reason}")
    
    log.info(f"收到私聊消息 | user={user_id} | images={len(image_urls)}")
    log.debug(f"消息内容: {message_text[:100]}..." if len(message_text) > 100 else f"消息内容: {message_text}")
    
    # 构建消息（添加用户标签）
    final_message = f"[{tag}]: {message_text}"
    
    # [新增] 如果使用了缓存图片，将 mapping_info 作为 System 注入
    system_injection_content = None
    if cached_hint:
        system_injection_content = cached_hint
    
    reply = await gemini_client.chat(
        final_message,
        user_id,
        group_id=None,
        image_urls=image_urls,
        enable_tools=True,  # 启用工具调用
        message_id=str(ctx.message_id or ""),  # [新增] 传递消息 ID
        system_injection=system_injection_content  # 使用专用参数注入 System 提示
    )
    
    log.success(f"私聊回复完成 | user={user_id} | reply_len={len(reply)}")
    await send_reply_with_policy(
        bot,
        event,
        reply,
        is_proactive=False,
        plugin_config=plugin_config,
    )


async def parse_message_with_mentions(
    bot: BotT,
    event: Any,
    *,
    max_images: int = 10,
    quote_image_caption_enabled: bool = True,
    quote_image_caption_prompt: str = "[引用图片共{count}张]",
    quote_image_caption_timeout_seconds: float = 3.0,
) -> tuple:
    """解析消息并保留 @ 提及和引用内容
    
    将消息中的 at 段转换为文本格式 "@昵称"，
    将 reply 段解析为被引用消息的内容，以便 LLM 能够感知上下文。
    
    Args:
        bot: BotT 实例
        event: 群消息事件
        
    Returns:
        tuple: (解析后的文本消息, 额外的图片URL列表)
    """
    from .utils.recent_images import get_image_cache

    ctx = build_event_context(bot, event)
    group_id_arg: Any = None
    group_id_str = str(ctx.group_id or "").strip()
    if group_id_str:
        group_id_arg = int(group_id_str) if group_id_str.isdigit() else group_id_str
    
    text_parts = []
    extra_images = []  # 用于存放引用消息中的图片
    quoted_content = None  # 引用的消息内容
    
    for seg in event.original_message:
        if seg.type == "text":
            text_parts.append(seg.data.get("text", ""))
        elif seg.type in {"at", "mention"}:
            qq = str(seg.data.get("qq" if seg.type == "at" else "user_id", ""))
            if qq == "all":
                text_parts.append(" @全体成员 ")
                continue
            
            # 如果是 @ 机器人自己，可以保留或忽略（因为已经有 tag 了）
            # 但为了保持一致性，还是转换一下，或者如果是机器人自己可以使用 "Mika"
            if qq == bot.self_id:
                # 机器人自己，可以不处理，或者显示 @Mika
                # 但要注意，如果 event.to_me 为 True，可能已经被前端移除过一次
                # 这里使用的是 original_message，所以肯定还在
                text_parts.append(" @Mika ")
                continue
                
            # 获取被 @ 人的昵称
            try:
                nickname = ""
                if group_id_arg is not None and qq.isdigit():
                    member_info = await safe_call_api(
                        bot,
                        "get_group_member_info",
                        group_id=group_id_arg,
                        user_id=int(qq),
                        no_cache=False,
                    )
                    nickname = (member_info or {}).get("card") or (member_info or {}).get("nickname") or ""

                text_parts.append(f" @{nickname or qq} ")
                
            except Exception as e:
                log.warning(f"获取群成员信息失败: {e}")
                text_parts.append(f" @{qq} ")
                
        elif seg.type == "reply":
            # 处理回复/引用消息
            reply_msg_id = seg.data.get("id") or seg.data.get("message_id")
            if reply_msg_id:
                reply_msg_id_str = str(reply_msg_id)
                image_cache = get_image_cache()
                
                # 1. 先查图片缓存
                cached_images, cache_hit = image_cache.get_images_by_message_id(
                    group_id=group_id_str,
                    user_id=str(ctx.user_id),
                    message_id=reply_msg_id_str
                )
                
                if cache_hit and cached_images:
                    # 缓存命中，使用缓存的图片
                    extra_images.extend([img.url for img in cached_images])
                    sender_name = cached_images[0].sender_name if cached_images else "某人"
                    quoted_content = f"[引用 {sender_name} 的消息: [图片×{len(cached_images)}]]"
                    log.debug(f"[Reply处理] 缓存命中 | msg_id={reply_msg_id} | images={len(cached_images)}")
                else:
                    # 2. 缓存未命中，调用 API 获取被引用的消息
                    try:
                        reply_id_arg: Any
                        reply_id_arg = int(reply_msg_id_str) if reply_msg_id_str.isdigit() else reply_msg_id_str
                        timeout_seconds = max(0.5, float(quote_image_caption_timeout_seconds or 3.0))
                        try:
                            msg_data = await asyncio.wait_for(
                                safe_call_api(bot, "get_msg", message_id=reply_id_arg),
                                timeout=timeout_seconds,
                            )
                        except asyncio.TimeoutError:
                            msg_data = None
                            log.warning(
                                f"[Reply处理] 获取引用消息超时(get_msg) | msg_id={reply_msg_id} | timeout={timeout_seconds:.1f}s"
                            )
                        if msg_data is None:
                            try:
                                msg_data = await asyncio.wait_for(
                                    safe_call_api(bot, "get_message", message_id=reply_id_arg),
                                    timeout=timeout_seconds,
                                )
                            except asyncio.TimeoutError:
                                msg_data = None
                                log.warning(
                                    f"[Reply处理] 获取引用消息超时(get_message) | msg_id={reply_msg_id} | timeout={timeout_seconds:.1f}s"
                                )
                        if not isinstance(msg_data, dict):
                            raise ValueError("get_msg/get_message returned empty or non-dict")

                        sender = msg_data.get("sender", {})
                        sender_name = sender.get("card") or sender.get("nickname") or "某人"
                        sender_id = str(sender.get("user_id", ""))
                        
                        # 解析被引用消息的内容
                        raw_message = msg_data.get("message", [])
                        resolved_quote_images = await extract_and_resolve_images(
                            bot, raw_message, max_images=max_images
                        )
                        quoted_parts = []
                        
                        # 如果 raw_message 是字符串（raw_message 格式）
                        if isinstance(raw_message, str):
                            quoted_parts.append(raw_message)
                        else:
                            # 遍历消息段
                            for m_seg in raw_message:
                                seg_type = m_seg.get("type") if isinstance(m_seg, dict) else getattr(m_seg, "type", None)
                                seg_data = m_seg.get("data", {}) if isinstance(m_seg, dict) else getattr(m_seg, "data", {})
                                
                                if seg_type == "text":
                                    quoted_parts.append(seg_data.get("text", ""))
                                elif seg_type == "image":
                                    quoted_parts.append("[图片]")
                                elif seg_type == "face":
                                    # QQ 表情
                                    quoted_parts.append("[表情]")
                                elif seg_type == "mface":
                                    # QQ 大表情/表情包
                                    summary = seg_data.get("summary", "表情包")
                                    quoted_parts.append(f"[{summary}]")
                                elif seg_type == "record":
                                    quoted_parts.append("[语音]")
                                elif seg_type == "video":
                                    quoted_parts.append("[视频]")
                                elif seg_type == "file":
                                    quoted_parts.append("[文件]")
                                elif seg_type == "at":
                                    at_qq = seg_data.get("qq", "")
                                    quoted_parts.append(f"@{at_qq}")
                                elif seg_type == "mention":
                                    at_uid = seg_data.get("user_id", "")
                                    quoted_parts.append(f"@{at_uid}")
                                elif seg_type == "forward":
                                    quoted_parts.append("[转发消息]")
                                # 其他类型忽略
                        
                        quoted_text = "".join(quoted_parts).strip()
                        
                        if resolved_quote_images:
                            for img_url in resolved_quote_images:
                                if img_url not in extra_images:
                                    extra_images.append(img_url)
                            image_cache.cache_images(
                                group_id=group_id_str,
                                user_id=sender_id,
                                image_urls=resolved_quote_images,
                                sender_name=sender_name,
                                message_id=reply_msg_id_str,
                            )
                            if quote_image_caption_enabled:
                                try:
                                    caption_text = str(quote_image_caption_prompt).format(
                                        count=len(resolved_quote_images),
                                        sender=sender_name,
                                    )
                                except Exception:
                                    caption_text = f"[引用图片共{len(resolved_quote_images)}张]"
                                quoted_parts.append(caption_text)
                                quoted_text = "".join(quoted_parts).strip()

                        if quoted_text or extra_images:
                            quoted_content = f"[引用 {sender_name} 的消息: {quoted_text or '[多媒体内容]'}]"
                        
                        log.debug(f"[Reply处理] API获取成功 | msg_id={reply_msg_id} | content={quoted_text[:50] if quoted_text else 'N/A'}")
                        
                    except Exception as e:
                        log.warning(f"获取引用消息失败: {e}")
                
        # 其他类型暂时忽略或按需处理
        # image 已经有 extract_images 处理
    
    result = "".join(text_parts).strip()
    
    # 将引用内容添加到消息开头
    if quoted_content:
        result = f"{quoted_content}\n{result}"
    
    return result, extra_images


async def handle_group(
    bot: BotT,
    event: Any,
    plugin_config: Config = None,
    gemini_client = None,
    is_proactive: bool = False,
    proactive_reason: str = None
):
    """处理群聊消息（@机器人时触发）。



    当用户在群聊中 @ 机器人时调用此函数。
    会验证群组白名单、提取消息内容、更新用户档案，并调用 Gemini API 获取回复。

    Args:
        bot: NoneBot Bot 实例，用于发送回复消息。
        event: 群消息事件，包含群 ID、用户 ID、发送者信息等。
        plugin_config: 插件配置对象（可选，默认通过依赖注入获取）。
        gemini_client: API 客户端（可选，默认通过依赖注入获取）。

    Note:
        - 如果 gemini_reply_at 配置为 False，则直接返回不处理
        - 群组必须在白名单中才会响应（如果配置了白名单）
        - 主人发送的消息会被标记为 "⭐Sensei"
        - 普通用户消息标签格式为 "{昵称}({QQ号})"
        - 会自动从消息中提取用户信息并更新用户档案
        - 支持多模态消息（文本 + 图片）
        - 长文本回复会自动转为转发消息发送
    """
    ctx = build_event_context(bot, event)
    log.info("[群聊Handler] ========== 开始处理 ==========")
    log.info(f"[群聊Handler] group={ctx.group_id} | user={ctx.user_id}")
    log.info(f"[群聊Handler] 消息内容: {(ctx.plaintext or '')[:50]}")
    
    # 使用依赖注入获取资源（如果未提供）
    if plugin_config is None:
        plugin_config = get_config()
    if gemini_client is None:
        gemini_client = get_gemini_client()

    if not ctx.is_group or not ctx.group_id:
        return
    
    if not plugin_config.gemini_reply_at and not is_proactive:
        log.debug("[群聊Handler] gemini_reply_at=False, 跳过处理")
        return
    
    if plugin_config.gemini_group_whitelist:
        allowed = {str(x) for x in plugin_config.gemini_group_whitelist}
        if ctx.group_id not in allowed:
            log.debug(f"群 {ctx.group_id} 不在白名单中，跳过处理")
            return

    session_key = ctx.session_key
    lock = get_session_lock_manager().get_lock(session_key)
    async with lock:
        await _handle_group_locked(
            bot=bot,
            event=event,
            plugin_config=plugin_config,
            gemini_client=gemini_client,
            is_proactive=is_proactive,
            proactive_reason=proactive_reason,
        )
        return


async def _handle_group_locked(
    *,
    bot: BotT,
    event: Any,
    plugin_config: Config,
    gemini_client,
    is_proactive: bool,
    proactive_reason: Optional[str],
) -> None:
    payload = await build_request_context_payload(bot, event, plugin_config)
    ctx = payload.ctx
    if not ctx.is_group or not ctx.group_id:
        return

    raw_text = payload.message_text
    image_urls = payload.image_urls
    
    if not raw_text and not image_urls:
        return

    # 获取身份标签
    user_id_int = ctx.user_id
    nickname = ctx.sender_name or "Sensei"
    # is_master = user_id_int == plugin_config.gemini_master_id
    # 统一使用 [昵称(QQ)] 格式，让 Prompt 中的 "Universal Sensei" 逻辑去处理身份
    tag = f"{nickname}({user_id_int})"
    
    # 处理图片缓存 - 使用新的 hybrid 策略
    image_cache = get_image_cache()
    cached_hint = None
    
    if image_urls:
        # 当前消息包含图片，缓存它们
        image_cache.cache_images(
            group_id=str(ctx.group_id),
            user_id=str(user_id_int),
            image_urls=image_urls,
            sender_name=nickname,
            message_id=str(ctx.message_id or "")
        )
    else:
        # 使用 hybrid 策略处理历史图片
        candidate_images = image_cache.peek_recent_images(
            group_id=str(ctx.group_id),
            user_id=str(user_id_int),
            limit=int(_cfg(plugin_config, "gemini_history_image_collage_max", 4))
        )
        
        # 获取上下文用于策略判定
        context_messages = None
        try:
            context_messages = await gemini_client.get_context(str(user_id_int), str(ctx.group_id))
        except Exception as e:
            log.debug(f"[历史图片] 获取上下文失败，继续策略判定: {e}")
        
        decision = determine_history_image_action(
            message_text=raw_text,
            candidate_images=candidate_images,
            context_messages=context_messages,
            mode=str(_cfg(plugin_config, "gemini_history_image_mode", "hybrid")),
            inline_max=int(_cfg(plugin_config, "gemini_history_image_inline_max", 1)),
            two_stage_max=int(_cfg(plugin_config, "gemini_history_image_two_stage_max", 2)),
            collage_max=int(_cfg(plugin_config, "gemini_history_image_collage_max", 4)),
            enable_collage=bool(_cfg(plugin_config, "gemini_history_image_enable_collage", True)),
            custom_keywords=_cfg(plugin_config, "gemini_history_image_trigger_keywords", []) or None,
        )
        
        if decision.action == HistoryImageAction.INLINE:
            # 直接回注原图
            image_urls = [img.url for img in decision.images_to_inject]
            cached_hint = build_image_mapping_hint(decision.images_to_inject)
            metrics.history_image_inline_used_total += 1
            metrics.history_image_images_injected_total += len(image_urls)
            log.info(f"[历史图片] INLINE | group={ctx.group_id} | user={user_id_int} | images={len(image_urls)} | reason={decision.reason}")
            
        elif decision.action == HistoryImageAction.COLLAGE and is_collage_available():
            # 拼图后注入
            collage_urls = [img.url for img in decision.images_to_inject]
            collage_result = await create_collage_from_urls(
                collage_urls,
                target_max_px=int(
                    _cfg(plugin_config, "gemini_history_image_collage_target_px", 768)
                )
            )
            if collage_result:
                base64_data, mime_type = collage_result
                # 将拼图作为单张图片注入
                image_urls = [f"data:{mime_type};base64,{base64_data}"]
                cached_hint = build_image_mapping_hint(decision.images_to_inject)
                metrics.history_image_collage_used_total += 1
                metrics.history_image_images_injected_total += len(decision.images_to_inject)
                log.info(f"[历史图片] COLLAGE | group={ctx.group_id} | user={user_id_int} | images={len(collage_urls)} | reason={decision.reason}")
            else:
                # 拼图失败，回退到 inline
                inline_max = int(_cfg(plugin_config, "gemini_history_image_inline_max", 1))
                image_urls = [img.url for img in decision.images_to_inject[:inline_max]]
                cached_hint = build_image_mapping_hint(decision.images_to_inject[:inline_max])
                metrics.history_image_inline_used_total += 1
                metrics.history_image_images_injected_total += len(image_urls)
                log.warning(f"[历史图片] COLLAGE失败回退INLINE | group={ctx.group_id} | user={user_id_int} | images={len(image_urls)}")
                
        elif decision.action == HistoryImageAction.TWO_STAGE:
            # 两阶段模式：只提供候选 msg_id 列表提示
            cached_hint = build_candidate_hint(decision.candidate_msg_ids)
            metrics.history_image_two_stage_triggered_total += 1
            log.info(f"[历史图片] TWO_STAGE | group={ctx.group_id} | user={user_id_int} | candidates={len(decision.candidate_msg_ids)} | reason={decision.reason}")
    
    log.info(f"收到群聊消息 | group={ctx.group_id} | user={user_id_int} | nickname={nickname} | images={len(image_urls)}")
    log.debug(f"消息内容(解析后): {raw_text[:100]}..." if len(raw_text) > 100 else f"消息内容: {raw_text}")

    # ==================== 兼容旧 tests：用户档案更新（同步/可 await） ====================
    # 历史测试会 patch `gemini_chat.handlers.get_user_profile_store`，并期望调用 update_from_message。
    # 新实现已迁移到后台抽取服务；这里保留一个 best-effort 调用以满足测试与向后兼容。
    try:
        profile_store = get_user_profile_store()
        if hasattr(profile_store, "update_from_message"):
            await profile_store.update_from_message(
                qq_id=str(user_id_int),
                content=raw_text,
                nickname=nickname,
            )
    except Exception as e:
        log.warning(f"群聊用户档案 update_from_message 失败(忽略): {e}")
    
    # LLM 用户档案抽取（后台异步，不阻塞主回复流程）
    try:
        from .utils.user_profile_extract_service import get_user_profile_extract_service

        svc = get_user_profile_extract_service()
        svc.ingest_message(
            qq_id=str(user_id_int),
            nickname=nickname,
            content=raw_text,
            message_id=str(ctx.message_id or ""),
            group_id=str(ctx.group_id),
        )
    except Exception as e:
        log.warning(f"群聊档案抽取 ingest 失败: {e}")
    
    # 构建消息（添加用户标签）
    final_message = f"[{tag}]: {raw_text}"
    
    # 如果是主动发言，将判决理由作为 System 注入，让 Mika 知道为什么插嘴
    # [新增] 如果使用了缓存图片，将 mapping_info 也作为 System 注入
    injection_parts: List[str] = []
    if is_proactive and proactive_reason:
        injection_parts.append(proactive_reason)
    if cached_hint:
        injection_parts.append(cached_hint)

    history_override = None
    if is_proactive and bool(getattr(plugin_config, "gemini_proactive_chatroom_enabled", True)):
        try:
            max_lines = int(
                getattr(plugin_config, "gemini_proactive_chatroom_history_lines", 30) or 30
            )
            history = await gemini_client.get_context(str(user_id_int), str(ctx.group_id))
            chatroom_injection = _build_proactive_chatroom_injection(
                history,
                bot_name=getattr(plugin_config, "gemini_bot_display_name", "Mika") or "Mika",
                max_lines=max(0, max_lines),
                trigger_message=raw_text,
                trigger_sender=tag,
            )
            if chatroom_injection:
                injection_parts.append(chatroom_injection)
            # 清空上下文注入：仅保留 transcript（对标 AstrBot 的 contexts=[]）
            history_override = []
        except Exception as e:
            log.warning(f"[主动发言][chatroom] 构建 transcript 失败，回退原模式: {e}")

    system_injection_content = "\n".join([p for p in injection_parts if p]).strip() or None
    
    reply = await gemini_client.chat(
        final_message,
        str(user_id_int),
        group_id=str(ctx.group_id),
        image_urls=image_urls,
        enable_tools=True,  # 启用工具调用
        message_id=str(ctx.message_id or ""),
        system_injection=system_injection_content,  # 使用专用参数注入 System 提示
        history_override=history_override,
    )
    
    log.success(f"群聊回复完成 | group={ctx.group_id} | user={user_id_int} | reply_len={len(reply)}")
    
    await send_reply_with_policy(
        bot,
        event,
        reply,
        is_proactive=is_proactive,
        plugin_config=plugin_config,
    )


def _build_final_reply_text(reply_text: str, is_proactive: bool) -> str:
    if is_proactive:
        return f"【自主回复】\n{reply_text}"
    return reply_text


async def _stage_short_quote_text(bot: BotT, event: Any, final_text: str) -> SendStageResult:
    ok = await safe_send(bot, event, final_text, reply_message=True, at_sender=False)
    return SendStageResult(ok=bool(ok), method="quote_text", error="" if ok else "safe_send_failed")


async def _stage_long_forward(
    bot: BotT,
    event: Any,
    final_text: str,
    plugin_config: Config,
) -> SendStageResult:
    ok = await send_forward_msg(bot, event, final_text, plugin_config=plugin_config)
    return SendStageResult(ok=bool(ok), method="forward", error="" if ok else "forward_failed")


async def _stage_render_image(
    bot: BotT,
    event: Any,
    final_text: str,
    plugin_config: Config,
) -> SendStageResult:
    ok = await send_rendered_image_with_quote(bot, event, final_text, plugin_config=plugin_config)
    return SendStageResult(ok=bool(ok), method="quote_image", error="" if ok else "render_or_send_failed")


async def _stage_text_fallback(bot: BotT, event: Any, final_text: str) -> SendStageResult:
    ok = await safe_send(bot, event, final_text, reply_message=True, at_sender=False)
    return SendStageResult(ok=bool(ok), method="quote_text_fallback", error="" if ok else "safe_send_failed")


def _build_quote_image_segments(message_id: Optional[str], platform: str, image_base64: str) -> list[dict]:
    segments: list[dict] = []
    if message_id:
        if "v12" in platform:
            segments.append({"type": "reply", "data": {"message_id": message_id}})
        else:
            segments.append({"type": "reply", "data": {"id": message_id}})
    segments.append({"type": "image", "data": {"file": f"base64://{image_base64}"}})
    return segments


async def send_rendered_image_with_quote(
    bot: BotT,
    event: Any,
    content: str,
    plugin_config: Config = None,
) -> bool:
    """将文本渲染为图片并发送（优先引用）。"""
    if plugin_config is None:
        plugin_config = get_config()

    try:
        image_bytes = render_text_to_png_bytes(
            content,
            max_width=int(getattr(plugin_config, "gemini_long_reply_image_max_width", 960) or 960),
            font_size=int(getattr(plugin_config, "gemini_long_reply_image_font_size", 24) or 24),
            max_chars=int(getattr(plugin_config, "gemini_long_reply_image_max_chars", 12000) or 12000),
        )
    except Exception as e:
        log.warning(f"文本渲染图片失败，跳过图片兜底: {e}")
        return False

    image_base64 = base64.b64encode(image_bytes).decode("ascii")
    ctx = build_event_context(bot, event)
    segments = _build_quote_image_segments(ctx.message_id, ctx.platform, image_base64)

    if await safe_send(bot, event, segments, reply_message=True, at_sender=False):
        return True

    group_id_arg: Any = None
    user_id_arg: Any = None
    if ctx.group_id:
        group_id_arg = int(ctx.group_id) if ctx.group_id.isdigit() else ctx.group_id
    if ctx.user_id:
        user_id_arg = int(ctx.user_id) if ctx.user_id.isdigit() else ctx.user_id

    ok = False
    if ctx.is_group and group_id_arg is not None:
        ok = (
            await safe_call_api(
                bot,
                "send_group_msg",
                group_id=group_id_arg,
                message=segments,
                auto_escape=False,
            )
        ) is not None
        if not ok:
            ok = (
                await safe_call_api(
                    bot,
                    "send_message",
                    detail_type="group",
                    group_id=group_id_arg,
                    message=segments,
                )
            ) is not None
    elif user_id_arg is not None:
        ok = (
            await safe_call_api(
                bot,
                "send_private_msg",
                user_id=user_id_arg,
                message=segments,
                auto_escape=False,
            )
        ) is not None
        if not ok:
            ok = (
                await safe_call_api(
                    bot,
                    "send_message",
                    detail_type="private",
                    user_id=user_id_arg,
                    message=segments,
                )
            ) is not None

    if not ok:
        log.warning("图片引用发送失败")
    return ok


async def send_reply_with_policy(
    bot: BotT,
    event: Any,
    reply_text: str,
    *,
    is_proactive: bool,
    plugin_config: Config = None,
) -> None:
    """统一回复发送策略。

    策略顺序：
    - 短消息：引用文本
    - 长消息：优先 forward
    - 失败：渲染图片并引用
    - 再失败：单条纯文本并引用
    """
    if plugin_config is None:
        plugin_config = get_config()

    final_text = _build_final_reply_text(reply_text, is_proactive=is_proactive)
    threshold = int(getattr(plugin_config, "gemini_forward_threshold", 300) or 300)
    is_long = len(final_text) >= max(1, threshold)
    session = build_event_context(bot, event).session_key

    stage_result: Optional[SendStageResult] = None

    if is_long:
        stage_result = await _stage_long_forward(bot, event, final_text, plugin_config)
        if stage_result.ok:
            log.info(f"[发送策略] session={session} | method={stage_result.method} | is_long={is_long}")
            return
    else:
        stage_result = await _stage_short_quote_text(bot, event, final_text)
        if stage_result.ok:
            log.info(f"[发送策略] session={session} | method={stage_result.method} | is_long={is_long}")
            return

    if bool(getattr(plugin_config, "gemini_long_reply_image_fallback_enabled", True)):
        stage_result = await _stage_render_image(bot, event, final_text, plugin_config)
        if stage_result.ok:
            log.info(f"[发送策略] session={session} | method={stage_result.method} | is_long={is_long}")
            return

    stage_result = await _stage_text_fallback(bot, event, final_text)
    if stage_result.ok:
        log.info(f"[发送策略] session={session} | method={stage_result.method} | is_long={is_long}")
        return

    log.error(
        f"[发送策略] session={session} | method={stage_result.method} | is_long={is_long} | error={stage_result.error}"
    )


async def send_forward_msg(
    bot: BotT,
    event: Any,
    content: str,
    plugin_config: Config = None
) -> bool:
    """发送转发消息（用于长文本）
    
    Args:
        bot: BotT 实例
        event: 消息事件
        content: 要发送的内容
        plugin_config: 插件配置（可选，默认通过依赖注入获取）
    """
    if plugin_config is None:
        plugin_config = get_config()
    
    nodes = [{
        "type": "node",
        "data": {
            "name": plugin_config.gemini_bot_display_name,
            "uin": bot.self_id,
            "content": content
        }
    }]

    ctx = build_event_context(bot, event)
    is_group = bool(ctx.is_group and ctx.group_id)
    group_id_arg: Any = None
    user_id_arg: Any = None
    if ctx.group_id:
        group_id_arg = int(ctx.group_id) if ctx.group_id.isdigit() else ctx.group_id
    if ctx.user_id:
        user_id_arg = int(ctx.user_id) if ctx.user_id.isdigit() else ctx.user_id

    ok = False
    if is_group:
        ok = (
            await safe_call_api(
                bot, "send_group_forward_msg", group_id=group_id_arg, messages=nodes
            )
        ) is not None
        if ok:
            log.debug(f"转发消息发送成功 | group={ctx.group_id}")
    else:
        ok = (
            await safe_call_api(
                bot, "send_private_forward_msg", user_id=user_id_arg, messages=nodes
            )
        ) is not None
        if ok:
            log.debug(f"转发消息发送成功 | user={ctx.user_id}")

    if ok:
        return True

    log.warning("转发消息发送失败")
    return False
