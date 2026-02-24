"""NoneBot2 事件匹配器模块。

定义插件的事件匹配规则和处理入口，包括：
- 指令匹配器（清空记忆等）
- 私聊消息匹配器
- 群聊 @ 消息匹配器
- 主动发言触发器
- 群聊热度监控

相关模块：
- [`handlers`](handlers.py:1): 消息处理逻辑实现
- [`group_state`](group_state.py:1): 群状态管理
"""

from nonebot import on_message, on_command, get_plugin_config
from nonebot import logger as log
import time
from typing import Any

from mika_chat_core.config import Config
from mika_chat_core.handlers import parse_message_with_mentions
from mika_chat_core.runtime import (
    get_client as get_runtime_client,
    get_config as get_runtime_config,
)
from mika_chat_core.utils.image_processor import extract_images, resolve_image_urls
from mika_chat_core.utils.recent_images import get_image_cache
from mika_chat_core.group_state import (
    get_proactive_cooldowns,
    get_proactive_message_counts,
    heat_monitor,
    touch_proactive_group,
)
from mika_chat_core.metrics import metrics
from mika_chat_core.compat.onebot_envelope import (
    build_event_envelope,
    build_event_envelope_from_event,
)
from mika_chat_core.matchers import check_proactive as check_proactive_core
from mika_chat_core.semantic_transcript import build_context_record_text, summarize_envelope
from mika_chat_core.engine import ChatEngine
from mika_chat_core.core_service_client import CoreServiceClient, CoreServiceTimeoutError
from mika_chat_core.utils.event_context import build_event_context
from .safe_api import safe_send
from .runtime_ports_nb import get_runtime_ports_bundle
from nonebot.adapters import Bot, Event
from mika_chat_core.contracts import EventEnvelope


async def check_at_me_anywhere(bot: Bot, event: Event) -> bool:
    """检查消息是否 @ 了机器人
    
    OneBot V11 Adapter 的 _check_at_me() 会在消息到达 matcher 之前
    检测首尾的 @，如果匹配到就会从 event.message 中移除该 @ 段，
    同时设置 event.to_me=True。
    
    因此我们需要：
    1. 首先检查 event.to_me（adapter 已处理的首尾 @）
    2. 再检查 event.original_message 中是否有 @ 在非首尾位置
    """
    if _is_self_message_event(bot, event):
        return False

    ctx = build_event_context(bot, event)
    if not ctx.is_group:
        return False

    log.debug(f"[AT检测] 开始 | group={ctx.group_id} | self_id={bot.self_id} | to_me={ctx.is_tome}")
    try:
        log.debug(f"[AT检测] message: {[(s.type, dict(s.data)) for s in getattr(event, 'message', [])]}")
        log.debug(f"[AT检测] original_message: {[(s.type, dict(s.data)) for s in getattr(event, 'original_message', [])]}")
    except Exception:
        pass
    
    # 1. 首先检查 NoneBot 已经处理好的 to_me 标志
    if ctx.is_tome:
        log.info("[AT检测] ✅ event.to_me=True，匹配成功!")
        return True
    
    # 2. 如果 to_me 为 False，再检查 original_message 中是否有 @ 在非首尾位置
    self_id = str(getattr(bot, "self_id", ""))
    for seg in getattr(event, "original_message", []) or []:  # 使用 original_message！
        try:
            if seg.type == "at" and str(seg.data.get("qq", "")) == self_id:
                log.info("[AT检测] ✅ 在 original_message 中找到 @，匹配成功!")
                return True
            if seg.type == "mention" and str(seg.data.get("user_id", "")) == self_id:
                log.info("[AT检测] ✅ 在 original_message 中找到 mention，匹配成功!")
                return True
        except Exception:
            continue
    
    log.debug("[AT检测] ❌ 未匹配")
    return False

def _get_plugin_config() -> Config:
    try:
        return get_runtime_config()
    except Exception:
        return get_plugin_config(Config)


class _PluginConfigProxy:
    """Always resolve latest runtime config to avoid stale module-level cache."""

    def __getattr__(self, name: str) -> Any:
        return getattr(_get_plugin_config(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            object.__setattr__(self, name, value)
            return
        setattr(_get_plugin_config(), name, value)


plugin_config = _PluginConfigProxy()
runtime_ports = get_runtime_ports_bundle()
REMOTE_FAILURE_REPLY_TEXT = "服务暂时不可用，请稍后再试。"


def _is_message_sent_event(event: Event) -> bool:
    post_type = str(getattr(event, "post_type", "") or "").strip().lower()
    if post_type == "message_sent":
        return True
    message_sent_type = str(getattr(event, "message_sent_type", "") or "").strip().lower()
    return message_sent_type == "self"


def _is_self_message_event(bot: Bot, event: Event) -> bool:
    if _is_message_sent_event(event):
        return True

    self_id = str(getattr(bot, "self_id", "") or "").strip()
    if not self_id:
        return False

    sender = getattr(event, "sender", None)
    if isinstance(sender, dict):
        sender_id = str(sender.get("user_id", "") or "").strip()
    else:
        sender_id = str(getattr(sender, "user_id", "") or "").strip()
    if sender_id and sender_id == self_id:
        return True

    event_user_id = str(getattr(event, "user_id", "") or "").strip()
    return bool(event_user_id and event_user_id == self_id)


async def _send_remote_failure_reply(bot: Bot, event: Event, *, envelope: EventEnvelope) -> None:
    intent_value = str(envelope.meta.get("intent") or "").strip().lower()
    if intent_value not in {"private", "group", "reset"}:
        return
    if _is_self_message_event(bot, event):
        return

    await safe_send(
        bot,
        event,
        REMOTE_FAILURE_REPLY_TEXT,
        reply_message=True,
        at_sender=False,
    )


def _build_traced_event_envelope(bot: Bot, event: Event, *, source: str) -> EventEnvelope | None:
    """Best-effort adapter trace for host->core envelope conversion."""
    try:
        envelope = build_event_envelope(bot, event, protocol="onebot")
        actions = ChatEngine.envelope_to_actions(envelope)
        log.debug(
            f"[Adapter->Core] source={source} | session={envelope.session_id} | "
            f"message_id={envelope.message_id or '?'} | parts={len(envelope.content_parts)} | "
            f"preview_actions={len(actions)}"
        )
        return envelope
    except Exception as exc:
        log.debug(f"[Adapter->Core] source={source} | envelope_build_failed={exc}")
        return None


async def _execute_remote_core_event(envelope: EventEnvelope) -> None:
    runtime_cfg = plugin_config.get_core_runtime_config()
    base_url = str(runtime_cfg["remote_base_url"] or "").strip()
    timeout_seconds = float(runtime_cfg["remote_timeout_seconds"])
    token = str(runtime_cfg["service_token"] or "").strip()

    client = CoreServiceClient(
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        token=token,
    )
    actions = await client.handle_event(envelope, dispatch=False)
    await ChatEngine.dispatch_actions(actions, runtime_ports.message)


async def _handle_event_with_runtime_mode(
    envelope: EventEnvelope,
    *,
    bot: Bot,
    event: Event,
) -> None:
    runtime_ports.register_event(envelope, bot=bot, event=event)
    runtime_cfg = plugin_config.get_core_runtime_config()
    mode = str(runtime_cfg["mode"] or "remote").strip().lower()
    if mode != "remote":
        log.error(f"[Adapter->Core] invalid runtime mode: {mode!r} (remote-only build)")
        return

    try:
        await _execute_remote_core_event(envelope)
    except CoreServiceTimeoutError as exc:
        log.warning(
            f"[Adapter->Core][remote] request timeout, skip immediate fallback reply | "
            f"session={envelope.session_id} | message={envelope.message_id or '?'} | "
            f"err_type={type(exc).__name__}"
        )
    except Exception as exc:
        log.exception(
            f"[Adapter->Core][remote] failed without embedded fallback | "
            f"err_type={type(exc).__name__} | err={exc!r}"
        )
        await _send_remote_failure_reply(bot, event, envelope=envelope)


# ==================== 指令匹配器 ====================

# 清空记忆指令
reset_cmd = on_command("清空记忆", aliases={"reset", "重置记忆"}, priority=5, block=True)


@reset_cmd.handle()
async def _handle_reset(bot: Bot, event: Event):
    """清空记忆指令处理"""
    envelope = _build_traced_event_envelope(bot, event, source="reset_cmd")
    if envelope is None:
        envelope = build_event_envelope(bot, event, protocol="onebot")
    envelope.meta["intent"] = "reset"
    await _handle_event_with_runtime_mode(
        envelope,
        bot=bot,
        event=event,
    )


# ==================== 消息匹配器 ====================

async def _is_private_message(bot: Bot, event: Event) -> bool:
    if _is_self_message_event(bot, event):
        return False
    ctx = build_event_context(bot, event)
    return bool(ctx.user_id) and not ctx.is_group


# 私聊消息（显式 rule，避免依赖 adapter-specific event class）
private_chat = on_message(rule=_is_private_message, priority=10, block=False)


@private_chat.handle()
async def _handle_private(bot: Bot, event: Event):
    """私聊消息处理"""
    if _is_self_message_event(bot, event):
        return
    envelope = _build_traced_event_envelope(bot, event, source="private_chat")
    if envelope is None:
        envelope = build_event_envelope(bot, event, protocol="onebot")
    envelope.meta["intent"] = "private"
    await _handle_event_with_runtime_mode(
        envelope,
        bot=bot,
        event=event,
    )


# 群聊消息（需要 @机器人，支持消息任意位置的 @）
group_chat = on_message(rule=check_at_me_anywhere, priority=10, block=False)


@group_chat.handle()
async def _handle_group(bot: Bot, event: Event):
    """群聊消息处理（@机器人时触发）"""
    if _is_self_message_event(bot, event):
        return
    envelope = _build_traced_event_envelope(bot, event, source="group_chat")
    if envelope is None:
        envelope = build_event_envelope(bot, event, protocol="onebot")
    envelope.meta["intent"] = "group"
    await _handle_event_with_runtime_mode(
        envelope,
        bot=bot,
        event=event,
    )


# ==================== 主动发言匹配器 ====================

_proactive_cooldowns = get_proactive_cooldowns()
_proactive_message_counts = get_proactive_message_counts()

async def check_proactive(event: Event) -> bool:
    """检查是否触发主动发言（复用 core 判定逻辑）。"""
    if _is_message_sent_event(event):
        return False

    envelope = build_event_envelope_from_event(
        event,
        protocol="onebot",
        platform="onebot",
    )
    if not str(envelope.meta.get("group_id") or "").strip():
        return False

    try:
        return bool(await check_proactive_core(envelope))
    except Exception as exc:
        log.debug(f"[主动发言][感知层] core 判定异常: {exc}")
        return False

# 优先级 98 (低于普通聊天 10，高于图片缓存 99)
proactive_chat = on_message(rule=check_proactive, priority=98, block=False)

@proactive_chat.handle()
async def _handle_proactive(bot: Bot, event: Event):
    """主动发言处理 (二级触发：认知层)"""
    envelope = _build_traced_event_envelope(bot, event, source="proactive_group")
    if envelope is None:
        envelope = build_event_envelope(bot, event, protocol="onebot")

    ctx = build_event_context(bot, event)
    if not ctx.is_group or not ctx.group_id:
        return

    # ===== 主动发言链路的 @ 解析修复 =====
    # 目标：让主动发言的“判决输入 + 额外 System 指令”都能看到 @ 提及对象。
    # 说明：群聊正常 handler 在 [`parse_message_with_mentions()`](mika_chat_core/handlers.py:297)
    # 中会把 at 段转成 "@昵称"；但主动发言之前的判决/提示此前用的是 `event.get_plaintext()`，
    # 可能丢失 @，导致模型误判“谁被祝生日快乐”。
    parsed_text = ""
    reply_images: list[str] = []
    try:
        parsed_text, reply_images = await parse_message_with_mentions(envelope)
        parsed_text = (parsed_text or "").strip()
    except Exception as e:
        log.debug(f"[主动发言][@解析] parse_message_with_mentions 失败，回退 plaintext: {e}")
        parsed_text = ""

    plaintext = (ctx.plaintext or "").strip()

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
                f"[主动发言][@解析] group={ctx.group_id or '?'} | user={ctx.user_id or '?'} | "
                f"at_targets={at_targets} | plaintext='{plaintext[:80]}' | parsed='{trigger_text[:80]}'"
            )
    except Exception as e:
        log.debug(f"[主动发言][@解析] 提取 at 目标失败: {e}")
    
    group_id = str(ctx.group_id)
    
    # [修改] 进入判决阶段就立即更新冷却时间，防止并发请求连发
    # 即使 LLM 判决失败也会触发冷却，避免短时间内重复调用 API
    _proactive_cooldowns[group_id] = time.monotonic()
    _proactive_message_counts[group_id] = 0
    touch_proactive_group(group_id)
    
    # 1. 使用 LLM 进行意图判决
    mika_client = get_runtime_client()
    
    # 获取上下文（对于群聊，group_id 是 context key 的主要部分，user_id 可以使用当前发言者）
    context = await mika_client.get_context(str(ctx.user_id), group_id)
    # 把当前消息拼进去（因为 context_store 还没存这条新消息）
    # 注意：handle_group 是会存的，但我们现在是 proactive，还没经过 handle_group
    # 为了判决准确，我们需要构造包含当前消息的上下文
    temp_context = list(context)[-15:] # 取最近 15 条
    nickname = ctx.sender_name or "User"
    temp_context.append({"role": "user", "content": trigger_text, "nickname": nickname})
    
    heat = heat_monitor.get_heat(group_id)
    
    log.info(f"[主动发言] 感知层触发 | group={group_id} | heat={heat}")
    
    # 调用判决
    result = await mika_client.judge_proactive_intent(temp_context, heat)
    
    if not result.get("should_reply"):
        metrics.proactive_reject_total += 1
        log.info(f"[主动发言] 判决跳过")
        return

    # 2. 判决通过，执行回复
    log.success(f"[主动发言] 判决通过")
    
    # 3. 将生成权交给主 Handler (Actor)
    # 不再注入额外主动发言系统提示：让模型基于真实上下文自然回应触发消息
    envelope.meta["intent"] = "group"
    envelope.meta["is_proactive"] = True
    await _handle_event_with_runtime_mode(
        envelope,
        bot=bot,
        event=event,
    )




# 低优先级匹配器，用于缓存群聊中的图片消息 & 记录文本上下文
# 不阻止后续处理，仅用于记录以便后续引用
image_cache_matcher = on_message(priority=99, block=False)


@image_cache_matcher.handle()
async def _cache_images(bot: Bot, event: Event):
    """缓存群聊中的图片消息 & 记录热度
    
    这个 matcher 优先级很低（99），能看到几乎所有群消息。
    """
    from nonebot import logger as log
    
    ctx = build_event_context(bot, event)
    if _is_self_message_event(bot, event):
        return
    if not ctx.is_group or not ctx.group_id:
        return

    group_id = str(ctx.group_id)
    heat_monitor.record_message(group_id)
    _proactive_message_counts[group_id] = _proactive_message_counts.get(group_id, 0) + 1
    touch_proactive_group(group_id)
    
    # 2. 图片缓存逻辑...
    log.debug(f"[消息监听] group={ctx.group_id} | user={ctx.user_id}")
    
    # 检查群组白名单
    if plugin_config.mika_group_whitelist:
        allowed = {str(x) for x in plugin_config.mika_group_whitelist}
        if str(ctx.group_id) not in allowed:
            return
    
    # 提取图片
    original_message = getattr(event, "original_message", None) or []
    image_urls = await resolve_image_urls(
        original_message,
        int(plugin_config.mika_max_images),
        platform_api=runtime_ports.platform_api,
    )

    envelope = build_event_envelope(bot, event, protocol="onebot")
    summary = summarize_envelope(envelope)

    message_id_str = str(ctx.message_id or "")
    image_cache = get_image_cache()
    if image_urls:
        # 缓存本条消息中的图片
        nickname = ctx.sender_name or str(ctx.user_id)
        image_cache.cache_images(
            group_id=str(ctx.group_id),
            user_id=str(ctx.user_id),
            image_urls=image_urls,
            sender_name=nickname,
            message_id=message_id_str,
        )
    else:
        # 无图消息仍记录消息轨迹，供 gap/候选策略使用
        image_cache.record_message(
            group_id=str(ctx.group_id),
            user_id=str(ctx.user_id),
            message_id=message_id_str,
        )

    # [Context Recorder] 记录语义化文本上下文（引用/@/图片占位）
    # 赋予 Bot "听觉"，即使不回复也能记住对话关系
    try:
        client = get_runtime_client()
        history = await client.get_context(str(ctx.user_id), str(ctx.group_id))
        recent_ids = {m.get("message_id") for m in history[-20:] if m.get("message_id")}

        if not message_id_str or message_id_str in recent_ids:
            return

        nickname = ctx.sender_name or "User"
        tag = f"{nickname}({ctx.user_id})"
        record_text = ""
        parse_failed = False
        needs_rich_parse = summary.has_reply or summary.has_mention

        if needs_rich_parse:
            try:
                parsed_text, _ = await parse_message_with_mentions(envelope)
                record_text = (parsed_text or "").strip()
            except Exception as e:
                log.warning(f"[上下文记录] 富文本解析失败，使用降级占位: {e}")
                parse_failed = True
        else:
            record_text = (ctx.plaintext or "").strip()

        record_text = build_context_record_text(
            summary=summary,
            plaintext=ctx.plaintext or "",
            parsed_text=record_text,
            parse_failed=parse_failed,
        )

        if record_text:
            await client.add_message(
                user_id=str(ctx.user_id),
                role="user",
                content=f"[{tag}]: {record_text}",
                group_id=str(ctx.group_id),
                message_id=message_id_str,
            )
    except Exception as e:
        log.warning(f"上下文记录失败: {e}")
        return
    
    # 日志记录（可选，生产环境可以移除或降级为 debug）
    # from .logger import matchers_logger as log
    # log.debug(f"缓存图片 | group={ctx.group_id} | user={ctx.user_id} | count={cached_count}")
