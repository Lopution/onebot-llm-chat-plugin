# Gemini Chat 插件 - 事件匹配器
"""NoneBot2 事件匹配器定义"""

from typing import Union

from nonebot import on_message, on_command, get_plugin_config
from nonebot import logger as log
import random
import time
from nonebot.adapters.onebot.v11 import (
    Bot,
    PrivateMessageEvent,
    GroupMessageEvent,
)

from .config import Config
from .handlers import handle_reset, handle_private, handle_group, parse_message_with_mentions
from .utils.image_processor import extract_images
from .utils.recent_images import get_image_cache
from .group_state import heat_monitor, get_proactive_cooldowns, get_proactive_message_counts
from .metrics import metrics


async def check_at_me_anywhere(event: GroupMessageEvent) -> bool:
    """检查消息是否 @ 了机器人
    
    OneBot V11 Adapter 的 _check_at_me() 会在消息到达 matcher 之前
    检测首尾的 @，如果匹配到就会从 event.message 中移除该 @ 段，
    同时设置 event.to_me=True。
    
    因此我们需要：
    1. 首先检查 event.to_me（adapter 已处理的首尾 @）
    2. 再检查 event.original_message 中是否有 @ 在非首尾位置
    """
    from nonebot import logger as log
    log.debug(f"[AT检测] 开始 | group={event.group_id} | self_id={event.self_id} | to_me={event.to_me}")
    log.debug(f"[AT检测] message: {[(s.type, dict(s.data)) for s in event.message]}")
    log.debug(f"[AT检测] original_message: {[(s.type, dict(s.data)) for s in event.original_message]}")
    
    # 1. 首先检查 NoneBot 已经处理好的 to_me 标志
    if event.to_me:
        log.info("[AT检测] ✅ event.to_me=True，匹配成功!")
        return True
    
    # 2. 如果 to_me 为 False，再检查 original_message 中是否有 @ 在非首尾位置
    self_id = str(event.self_id)
    for seg in event.original_message:  # 使用 original_message！
        if seg.type == "at" and str(seg.data.get("qq", "")) == self_id:
            log.info("[AT检测] ✅ 在 original_message 中找到 @，匹配成功!")
            return True
    
    log.debug("[AT检测] ❌ 未匹配")
    return False

# 获取配置
plugin_config = get_plugin_config(Config)


# ==================== 指令匹配器 ====================

# 清空记忆指令
reset_cmd = on_command("清空记忆", aliases={"reset", "重置记忆"}, priority=5, block=True)


@reset_cmd.handle()
async def _handle_reset(bot: Bot, event: Union[PrivateMessageEvent, GroupMessageEvent]):
    """清空记忆指令处理"""
    await handle_reset(bot, event, plugin_config)


# ==================== 消息匹配器 ====================

# 私聊消息
private_chat = on_message(priority=10, block=False)


@private_chat.handle()
async def _handle_private(bot: Bot, event: PrivateMessageEvent):
    """私聊消息处理"""
    await handle_private(bot, event, plugin_config)


# 群聊消息（需要 @机器人，支持消息任意位置的 @）
group_chat = on_message(rule=check_at_me_anywhere, priority=10, block=False)


@group_chat.handle()
async def _handle_group(bot: Bot, event: GroupMessageEvent):
    """群聊消息处理（@机器人时触发）"""
    await handle_group(bot, event, plugin_config)


# ==================== 主动发言匹配器 ====================

_proactive_cooldowns = get_proactive_cooldowns()
_proactive_message_counts = get_proactive_message_counts()

async def check_proactive(event: GroupMessageEvent) -> bool:
    """检查是否触发主动发言 (二级触发：感知层)"""
    # ===== Debug：关键决策因子采样（仅在真正触发/被过滤时输出） =====
    group_id_str = str(getattr(event, "group_id", ""))
    user_id_str = str(getattr(event, "user_id", ""))

    # 1. 如果已经 @了机器人，不触发主动发言
    if event.to_me:
        return False
        
    # 2. 检查群白名单
    if plugin_config.gemini_group_whitelist and event.group_id not in plugin_config.gemini_group_whitelist:
        return False
        
    # 3. 感知层判断
    text = event.get_plaintext() or ""

    # 图片消息：允许绕过短消息过滤（用户要求不改图片逻辑）
    try:
        has_image = any(seg.type == "image" for seg in getattr(event, "message", []))
    except Exception:
        has_image = False

    # 3.1 关键词检测 (Stage 1)
    # [优化] 大小写不敏感匹配
    text_lower = text.lower()
    if any(k.lower() in text_lower for k in plugin_config.gemini_proactive_keywords):
        # ===== 关键词触发：保持原逻辑（只受 keyword_cooldown 影响） =====
        last_time = _proactive_cooldowns.get(group_id_str, 0)
        current_time = time.time()
        min_keyword_cooldown = max(1, int(plugin_config.gemini_proactive_keyword_cooldown))
        if current_time - last_time < min_keyword_cooldown:
            log.info(
                f"[主动发言][感知层] 触发被冷却拦截 | reason=keyword | group={group_id_str} | user={user_id_str} | "
                f"has_image={has_image} | text_len={len(text)} | cooldown_s={min_keyword_cooldown}"
            )
            return False

        metrics.proactive_trigger_total += 1
        log.info(
            f"[主动发言][感知层] ✅触发进入判决 | reason=keyword | group={group_id_str} | user={user_id_str} | "
            f"has_image={has_image} | text_len={len(text)} | text='{text[:60]}'"
        )
        return True

    # 若主动发言概率为 0，则关闭“非关键词”的语义/热度通道，避免无意义计算与模型加载
    if plugin_config.gemini_proactive_rate <= 0:
        return False

    # ===== 非关键词触发：按用户确认的新 gate =====
    # 规则：必须同时满足【热度达标 + 冷却时间满足 + 消息条数满足】才会触发语义模型相似度判断；
    # 且必须语义命中才会进入 LLM 判决。

    # 忽略过短消息 (除非包含图片)
    if len(text) <= plugin_config.gemini_proactive_ignore_len and not has_image:
        return False

    # 1) 热度门槛（不达标直接不触发；避免“热度通道”单独触发）
    heat = heat_monitor.get_heat(group_id_str)
    if heat < plugin_config.gemini_heat_threshold:
        return False

    # 2) 冷却时间
    last_time = _proactive_cooldowns.get(group_id_str, 0)
    current_time = time.time()
    if current_time - last_time < plugin_config.gemini_proactive_cooldown:
        log.debug(
            f"[主动发言][感知层] 触发被冷却拦截 | reason=heat_gate | group={group_id_str} | user={user_id_str} | "
            f"since_last={current_time - last_time:.1f}s | cooldown_s={plugin_config.gemini_proactive_cooldown}"
        )
        return False

    # 3) 消息条数冷却
    message_count = _proactive_message_counts.get(group_id_str, 0)
    if message_count < plugin_config.gemini_proactive_cooldown_messages:
        log.debug(
            f"[主动发言][感知层] 触发被消息条数冷却拦截 | reason=heat_gate | group={group_id_str} | "
            f"count={message_count} < need={plugin_config.gemini_proactive_cooldown_messages}"
        )
        return False

    # 4) 语义话题命中（必须）
    has_topic = False
    semantic_topic = ""
    semantic_score = 0.0
    if text:
        try:
            from .utils.semantic_matcher import semantic_matcher

            is_match, topic, score = semantic_matcher.check_similarity(text)
            semantic_topic = topic or ""
            semantic_score = float(score or 0.0)
            if is_match:
                has_topic = True
        except Exception as e:
            log.debug(f"[主动发言] 语义匹配异常: {e}")
            has_topic = False

    if not has_topic:
        log.debug(
            f"[主动发言][感知层] 语义未命中，终止 | group={group_id_str} | user={user_id_str} | "
            f"has_image={has_image} | text_len={len(text)} | heat={heat}/{plugin_config.gemini_heat_threshold} | "
            f"best_score={semantic_score:.3f}"
        )
        return False

    trigger_reason = f"semantic({semantic_topic}:{semantic_score:.2f})"

    # 5) 概率过滤（保持原行为：最终决定是否进入 LLM 判决）
    if random.random() > plugin_config.gemini_proactive_rate:
        log.debug(
            f"[主动发言][感知层] 触发被概率过滤 | reason={trigger_reason} | group={group_id_str} | "
            f"rate={plugin_config.gemini_proactive_rate}"
        )
        return False

    metrics.proactive_trigger_total += 1
    log.info(
        f"[主动发言][感知层] ✅触发进入判决 | reason={trigger_reason} | group={group_id_str} | user={user_id_str} | "
        f"has_image={has_image} | text_len={len(text)} | heat={heat}/{plugin_config.gemini_heat_threshold} | "
        f"msg_count={message_count}/{plugin_config.gemini_proactive_cooldown_messages} | text='{text[:60]}'"
    )
    return True

# 优先级 98 (低于普通聊天 10，高于图片缓存 99)
proactive_chat = on_message(rule=check_proactive, priority=98, block=False)

@proactive_chat.handle()
async def _handle_proactive(bot: Bot, event: GroupMessageEvent):
    """主动发言处理 (二级触发：认知层)"""
    from .deps import get_gemini_client_dep

    # ===== 主动发言链路的 @ 解析修复 =====
    # 目标：让主动发言的“判决输入 + 额外 System 指令”都能看到 @ 提及对象。
    # 说明：群聊正常 handler 在 [`parse_message_with_mentions()`](bot/src/plugins/gemini_chat/handlers.py:297)
    # 中会把 at 段转成 "@昵称"；但主动发言之前的判决/提示此前用的是 `event.get_plaintext()`，
    # 可能丢失 @，导致模型误判“谁被祝生日快乐”。
    parsed_text = ""
    reply_images: list[str] = []
    try:
        parsed_text, reply_images = await parse_message_with_mentions(bot, event)
        parsed_text = (parsed_text or "").strip()
    except Exception as e:
        log.debug(f"[主动发言][@解析] parse_message_with_mentions 失败，回退 plaintext: {e}")
        parsed_text = ""

    plaintext = ""
    try:
        plaintext = (event.get_plaintext() or "").strip()
    except Exception:
        plaintext = ""

    trigger_text = parsed_text or plaintext

    # ===== Debug: @ 提及在主动发言链路中的可见性 =====
    # 这里输出 original_message 中的 at 目标 + plaintext + parsed_text（@昵称）摘要。
    try:
        at_targets: list[str] = []
        for seg in getattr(event, "original_message", []) or []:
            seg_type = getattr(seg, "type", None)
            if seg_type != "at":
                continue
            seg_data = getattr(seg, "data", {}) or {}
            at_targets.append(str(seg_data.get("qq", "")))
        if at_targets:
            log.info(
                f"[主动发言][@解析] group={getattr(event,'group_id','?')} | user={getattr(event,'user_id','?')} | "
                f"at_targets={at_targets} | plaintext='{plaintext[:80]}' | parsed='{trigger_text[:80]}'"
            )
    except Exception as e:
        log.debug(f"[主动发言][@解析] 提取 at 目标失败: {e}")
    
    group_id = str(event.group_id)
    
    # [修改] 进入判决阶段就立即更新冷却时间，防止并发请求连发
    # 即使 LLM 判决失败也会触发冷却，避免短时间内重复调用 API
    _proactive_cooldowns[group_id] = time.time()
    _proactive_message_counts[group_id] = 0
    
    # 1. 使用 LLM 进行意图判决
    gemini_client = get_gemini_client_dep()
    
    # 获取上下文（对于群聊，group_id 是 context key 的主要部分，user_id 可以使用当前发言者）
    context = await gemini_client.get_context(str(event.user_id), group_id)
    # 把当前消息拼进去（因为 context_store 还没存这条新消息）
    # 注意：handle_group 是会存的，但我们现在是 proactive，还没经过 handle_group
    # 为了判决准确，我们需要构造包含当前消息的上下文
    temp_context = list(context)[-15:] # 取最近 15 条
    nickname = event.sender.card or event.sender.nickname or "User"
    temp_context.append({"role": "user", "content": trigger_text, "nickname": nickname})
    
    heat = heat_monitor.get_heat(group_id)
    
    log.info(f"[主动发言] 感知层触发 | group={group_id} | heat={heat}")
    
    # 调用判决
    result = await gemini_client.judge_proactive_intent(temp_context, heat)
    
    if not result.get("should_reply"):
        metrics.proactive_reject_total += 1
        log.info(f"[主动发言] 判决跳过")
        return

    # 2. 判决通过，执行回复
    log.success(f"[主动发言] 判决通过")
    
    # 3. 将生成权交给主 Handler (Actor)
    # 传递 extra_prompt 让 Mika 知道为什么要插嘴
    # [修复] 明确指出需要回复的目标消息，避免"已读乱回"历史消息
    trigger_message = trigger_text
    # 截取前 150 字符，避免过长
    trigger_preview = trigger_message[:150] + "..." if len(trigger_message) > 150 else trigger_message
    
    # 获取发送者昵称
    sender_name = event.sender.card or event.sender.nickname or "某位同学"
    
    extra_prompt = (
        f"[System Instruction - 主动发言模式]\n"
        f"你并没有被@，但你决定主动加入对话。\n"
        f"【重要】你必须且只能回应 {sender_name} 刚刚发送的这条消息：\n"
        f"「{trigger_preview}」\n"
        f"【风格要求】\n"
        f"- 如果是闲聊/吐槽/分享：像朋友随口接话，1-2句话即可，可以用表情、语气词\n"
        f"- 如果是问题/求助：正常回答，但也不用太长篇大论\n"
        f"- 不要刻意把历史消息中的多个话题串联起来\n"
        f"- 专注于这一条消息本身\n"
        f"- 不要提及'我决定插嘴'或'主动发言'"
    )
    
    await handle_group(bot, event, plugin_config, is_proactive=True, proactive_reason=extra_prompt)




# 低优先级匹配器，用于缓存群聊中的图片消息 & 记录文本上下文
# 不阻止后续处理，仅用于记录以便后续引用
image_cache_matcher = on_message(priority=99, block=False)


@image_cache_matcher.handle()
async def _cache_images(bot: Bot, event: GroupMessageEvent):
    """缓存群聊中的图片消息 & 记录热度
    
    这个 matcher 优先级很低（99），能看到几乎所有群消息。
    """
    from nonebot import logger as log
    
    # 1. 记录热度和消息计数
    if hasattr(event, 'group_id'):
        group_id = str(event.group_id)
        heat_monitor.record_message(group_id)
        # 增加主动发言消息计数器
        _proactive_message_counts[group_id] = _proactive_message_counts.get(group_id, 0) + 1
    
    # 2. 图片缓存逻辑...
    log.debug(f"[消息监听] group={getattr(event, 'group_id', 'N/A')} | user={event.user_id}")
    
    # 仅处理群聊消息
    if not isinstance(event, GroupMessageEvent):
        log.debug("[图片缓存] 跳过 - 非群聊消息")
        return
    
    # 检查群组白名单
    if plugin_config.gemini_group_whitelist and event.group_id not in plugin_config.gemini_group_whitelist:
        return
    
    # 提取图片
    image_urls = extract_images(event.original_message, plugin_config.gemini_max_images)
    
    if not image_urls:
        # 如果没有图片，记录这条消息用于计数
        image_cache = get_image_cache()
        image_cache.record_message(
            group_id=str(event.group_id),
            user_id=str(event.user_id),
            message_id=str(event.message_id)
        )
        
        # [Context Recorder] 记录纯文本消息到上下文
        # 赋予 Bot "听觉"，即使不回复也能记住上下文
        from .deps import get_gemini_client_dep
        try:
            client = get_gemini_client_dep()
            # [改进] 增强去重：使用 Set 检查最近 20 条消息
            # 使用 Set 替代列表遍历，提高查找效率
            ctx = await client.get_context(str(event.user_id), str(event.group_id))
            recent_ids = {m.get("message_id") for m in ctx[-20:] if m.get("message_id")}
            
            if str(event.message_id) not in recent_ids:
                nickname = event.sender.card or event.sender.nickname or "User"
                tag = f"{nickname}({event.user_id})"
                text = event.get_plaintext()
                
                if not text:
                    # 如果是纯图片消息，保存占位符
                    if extract_images(event.message, 1):
                        text = "[图片]"
                
                if text:
                    await client.add_message(
                        user_id=str(event.user_id),
                        role="user",
                        content=f"[{tag}]: {text}",
                        group_id=str(event.group_id),
                        message_id=str(event.message_id)
                    )
        except Exception as e:
            log.warning(f"上下文记录失败: {e}")
            
        return
    
    # 缓存图片
    nickname = event.sender.card or event.sender.nickname or str(event.user_id)
    image_cache = get_image_cache()
    cached_count = image_cache.cache_images(
        group_id=str(event.group_id),
        user_id=str(event.user_id),
        image_urls=image_urls,
        sender_name=nickname,
        message_id=str(event.message_id)
    )
    
    # 日志记录（可选，生产环境可以移除或降级为 debug）
    # from .logger import matchers_logger as log
    # log.debug(f"缓存图片 | group={event.group_id} | user={event.user_id} | count={cached_count}")
