"""Host-agnostic matcher helpers.

本模块仅提供规则判断与处理函数，不注册 NoneBot matcher。
宿主适配层（如 `nonebot_plugin_mika_chat.matchers`）负责把这些函数绑定到事件系统。
"""

from __future__ import annotations

import random
import time
from typing import Any

from mika_chat_core.group_state import (
    get_proactive_cooldowns,
    get_proactive_message_counts,
    heat_monitor,
)
from mika_chat_core.handlers import handle_group, parse_message_with_mentions
from mika_chat_core.metrics import metrics
from mika_chat_core.runtime import (
    get_config as get_runtime_config,
    get_host_event_port as get_runtime_host_event_port,
    get_message_port as get_runtime_message_port,
)
from mika_chat_core.settings import Config
from mika_chat_core.engine import ChatEngine
from mika_chat_core.event_envelope import build_event_envelope
from mika_chat_core.semantic_transcript import build_context_record_text, summarize_envelope
from mika_chat_core.utils.event_context import build_event_context, build_event_context_from_event
from mika_chat_core.utils.image_processor import resolve_image_urls
from mika_chat_core.utils.nb_types import BotT, EventT
from mika_chat_core.utils.recent_images import get_image_cache

from .infra.logging import logger as log


def _get_plugin_config() -> Config:
    try:
        return get_runtime_config()
    except Exception:
        return Config(gemini_api_key="test-api-key-12345678901234567890", gemini_master_id=1)


plugin_config = _get_plugin_config()

_proactive_cooldowns = get_proactive_cooldowns()
_proactive_message_counts = get_proactive_message_counts()


async def check_at_me_anywhere(bot: BotT, event: EventT) -> bool:
    """检查消息是否 @ 了机器人。"""
    ctx = build_event_context(bot, event)
    if not ctx.is_group:
        return False

    try:
        if ctx.is_tome:
            return True

        self_id = str(getattr(bot, "self_id", ""))
        for seg in getattr(event, "original_message", []) or []:
            try:
                if seg.type == "at" and str(seg.data.get("qq", "")) == self_id:
                    return True
                if seg.type == "mention" and str(seg.data.get("user_id", "")) == self_id:
                    return True
            except Exception:
                continue
        return False
    except Exception:
        return False


async def _is_private_message(bot: BotT, event: EventT) -> bool:
    ctx = build_event_context(bot, event)
    return bool(ctx.user_id) and not ctx.is_group


async def check_proactive(event: EventT) -> bool:
    """检查是否触发主动发言（二级触发：感知层）。"""
    ctx = build_event_context_from_event(event, platform="onebot")
    group_id_str = str(ctx.group_id or "")

    if not group_id_str:
        return False
    if not bool(getattr(plugin_config, "gemini_active_reply_ltm_enabled", True)):
        return False

    active_reply_whitelist = getattr(plugin_config, "gemini_active_reply_whitelist", []) or []
    if active_reply_whitelist:
        allowed = {str(x) for x in active_reply_whitelist}
        if group_id_str not in allowed:
            return False

    active_reply_probability = float(
        getattr(plugin_config, "gemini_active_reply_probability", 1.0) or 1.0
    )

    def _pass_active_probability() -> bool:
        if active_reply_probability >= 1:
            return True
        return random.random() <= max(0.0, active_reply_probability)

    if ctx.is_tome:
        return False

    if plugin_config.gemini_group_whitelist:
        allowed = {str(x) for x in plugin_config.gemini_group_whitelist}
        if group_id_str not in allowed:
            return False

    text = ctx.plaintext or ""
    try:
        has_image = any(seg.type == "image" for seg in getattr(event, "message", []))
    except Exception:
        has_image = False

    text_lower = text.lower()
    if any(k.lower() in text_lower for k in plugin_config.gemini_proactive_keywords):
        last_time = _proactive_cooldowns.get(group_id_str, 0)
        current_time = time.monotonic()
        min_keyword_cooldown = max(1, int(plugin_config.gemini_proactive_keyword_cooldown))
        if current_time - last_time < min_keyword_cooldown:
            return False
        if not _pass_active_probability():
            return False
        metrics.proactive_trigger_total += 1
        return True

    if plugin_config.gemini_proactive_rate <= 0:
        return False
    if len(text) <= plugin_config.gemini_proactive_ignore_len and not has_image:
        return False

    heat = heat_monitor.get_heat(group_id_str)
    if heat < plugin_config.gemini_heat_threshold:
        return False

    last_time = _proactive_cooldowns.get(group_id_str, 0)
    current_time = time.monotonic()
    if current_time - last_time < plugin_config.gemini_proactive_cooldown:
        return False

    message_count = _proactive_message_counts.get(group_id_str, 0)
    if message_count < plugin_config.gemini_proactive_cooldown_messages:
        return False

    has_topic = False
    if text:
        try:
            from .utils.semantic_matcher import semantic_matcher

            is_match, _, _ = semantic_matcher.check_similarity(text)
            if is_match:
                has_topic = True
        except Exception as e:
            log.debug(f"[主动发言] 语义匹配异常: {e}")
            has_topic = False

    if not has_topic:
        return False
    if random.random() > plugin_config.gemini_proactive_rate:
        return False
    if not _pass_active_probability():
        return False

    metrics.proactive_trigger_total += 1
    return True


async def _handle_proactive(bot: BotT, event: EventT) -> None:
    """主动发言处理（二级触发：认知层）。"""
    from mika_chat_core.deps import get_gemini_client_dep

    ctx = build_event_context(bot, event)
    if not ctx.is_group or not ctx.group_id:
        return

    parsed_text = ""
    try:
        parsed_text, _ = await parse_message_with_mentions(bot, event)
        parsed_text = (parsed_text or "").strip()
    except Exception as e:
        log.debug(f"[主动发言][@解析] parse_message_with_mentions 失败，回退 plaintext: {e}")
        parsed_text = ""

    plaintext = (ctx.plaintext or "").strip()
    trigger_text = parsed_text or plaintext

    group_id = str(ctx.group_id)
    _proactive_cooldowns[group_id] = time.monotonic()
    _proactive_message_counts[group_id] = 0

    gemini_client = get_gemini_client_dep()
    context = await gemini_client.get_context(str(ctx.user_id), group_id)
    temp_context = list(context)[-15:]
    nickname = ctx.sender_name or "User"
    temp_context.append({"role": "user", "content": trigger_text, "nickname": nickname})

    heat = heat_monitor.get_heat(group_id)
    result = await gemini_client.judge_proactive_intent(temp_context, heat)
    if not result.get("should_reply"):
        metrics.proactive_reject_total += 1
        return

    envelope = build_event_envelope(bot, event, protocol="onebot")
    envelope.meta["intent"] = "group"
    envelope.meta["is_proactive"] = True
    host_port = get_runtime_host_event_port()
    if host_port and hasattr(host_port, "register_event"):
        try:
            host_port.register_event(envelope, bot=bot, event=event)
        except Exception as exc:
            log.debug(f"[Core->Engine] proactive register_event failed: {exc}")

    ports_bundle = {
        "message": get_runtime_message_port(),
        "host_events": host_port,
    }
    try:
        await ChatEngine.handle_event(envelope, ports_bundle, plugin_config, dispatch=True)
    except Exception as exc:
        log.exception(f"[Core->Engine] proactive_group_via_engine_failed_without_fallback | err={exc}")


async def _cache_images(bot: BotT, event: EventT) -> None:
    """缓存群聊中的图片消息并记录上下文。"""
    from mika_chat_core.deps import get_gemini_client_dep

    ctx = build_event_context(bot, event)
    if not ctx.is_group or not ctx.group_id:
        return

    group_id = str(ctx.group_id)
    heat_monitor.record_message(group_id)
    _proactive_message_counts[group_id] = _proactive_message_counts.get(group_id, 0) + 1

    if plugin_config.gemini_group_whitelist:
        allowed = {str(x) for x in plugin_config.gemini_group_whitelist}
        if group_id not in allowed:
            return

    original_message = getattr(event, "original_message", None) or []
    image_urls = await resolve_image_urls(
        bot,
        original_message,
        int(plugin_config.gemini_max_images),
    )

    envelope = build_event_envelope(bot, event, protocol="onebot")
    summary = summarize_envelope(envelope)

    message_id_str = str(ctx.message_id or "")
    image_cache = get_image_cache()
    if image_urls:
        nickname = ctx.sender_name or str(ctx.user_id)
        image_cache.cache_images(
            group_id=group_id,
            user_id=str(ctx.user_id),
            image_urls=image_urls,
            sender_name=nickname,
            message_id=message_id_str,
        )
    else:
        image_cache.record_message(
            group_id=group_id,
            user_id=str(ctx.user_id),
            message_id=message_id_str,
        )

    try:
        client = get_gemini_client_dep()
        history = await client.get_context(str(ctx.user_id), group_id)
        recent_ids = {m.get("message_id") for m in history[-20:] if m.get("message_id")}
        if not message_id_str or message_id_str in recent_ids:
            return

        nickname = ctx.sender_name or "User"
        tag = f"{nickname}({ctx.user_id})"
        record_text = ""
        parse_failed = False
        if summary.has_reply or summary.has_mention:
            try:
                parsed_text, _ = await parse_message_with_mentions(bot, event)
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
                group_id=group_id,
                message_id=message_id_str,
            )
    except Exception as e:
        log.warning(f"上下文记录失败: {e}")


__all__ = [
    "plugin_config",
    "_proactive_cooldowns",
    "_proactive_message_counts",
    "check_at_me_anywhere",
    "_is_private_message",
    "check_proactive",
    "_handle_proactive",
    "_cache_images",
    "handle_group",
    "parse_message_with_mentions",
]
