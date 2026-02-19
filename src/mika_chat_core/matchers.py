"""Host-agnostic matcher helpers.

核心规则函数以 EventEnvelope 为输入，避免直接依赖宿主事件对象。
适配层可自行把原生事件转换成 EventEnvelope 后再调用。
"""

from __future__ import annotations

import random
import time
from typing import Any

from mika_chat_core.contracts import EventEnvelope
from mika_chat_core.group_state import (
    get_proactive_cooldowns,
    get_proactive_message_counts,
    heat_monitor,
    prune_proactive_state,
    touch_proactive_group,
)
from mika_chat_core.handlers import handle_group, parse_message_with_mentions
from mika_chat_core.metrics import metrics
from mika_chat_core.runtime import (
    get_client as get_runtime_client,
    get_config as get_runtime_config,
    get_platform_api_port as get_runtime_platform_api_port,
)
from mika_chat_core.semantic_transcript import build_context_record_text, summarize_envelope
from mika_chat_core.settings import Config
from mika_chat_core.utils.event_context import build_event_context_from_envelope
from mika_chat_core.utils.recent_images import get_image_cache

from .infra.logging import logger as log


def _get_plugin_config() -> Config:
    try:
        return get_runtime_config()
    except Exception:
        return Config(llm_api_key="test-api-key-12345678901234567890", mika_master_id="1")


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

_proactive_cooldowns = get_proactive_cooldowns()
_proactive_message_counts = get_proactive_message_counts()


def _is_message_sent_envelope(envelope: EventEnvelope) -> bool:
    meta = envelope.meta or {}
    post_type = str(meta.get("post_type", "") or "").strip().lower()
    if post_type == "message_sent":
        return True
    message_sent_type = str(meta.get("message_sent_type", "") or "").strip().lower()
    return message_sent_type == "self"


def is_self_message_from_envelope(envelope: EventEnvelope) -> bool:
    if _is_message_sent_envelope(envelope):
        return True
    bot_self_id = str(envelope.bot_self_id or "").strip()
    author_id = str(envelope.author.id or "").strip()
    return bool(bot_self_id and author_id and author_id == bot_self_id)


def check_at_me_from_envelope(envelope: EventEnvelope) -> bool:
    if is_self_message_from_envelope(envelope):
        return False
    ctx = build_event_context_from_envelope(envelope)
    if not ctx.is_group:
        return False
    if ctx.is_tome:
        return True
    target_bot_id = str(envelope.bot_self_id or "").strip()
    if not target_bot_id:
        return False
    for part in envelope.content_parts:
        if part.kind == "mention" and str(part.target_id or "").strip() == target_bot_id:
            return True
    return False


def is_private_message_from_envelope(envelope: EventEnvelope) -> bool:
    if is_self_message_from_envelope(envelope):
        return False
    ctx = build_event_context_from_envelope(envelope)
    return bool(ctx.user_id) and not ctx.is_group


def _resolve_image_refs_from_envelope(envelope: EventEnvelope, *, max_images: int) -> list[str]:
    refs: list[str] = []
    if max_images <= 0:
        return refs
    for part in envelope.content_parts:
        if part.kind != "image":
            continue
        ref = str(part.asset_ref or "").strip()
        if not ref:
            continue
        refs.append(ref)
        if len(refs) >= max_images:
            break
    return refs


async def _resolve_image_urls_from_envelope(envelope: EventEnvelope, *, max_images: int) -> list[str]:
    refs = _resolve_image_refs_from_envelope(envelope, max_images=max_images)
    if not refs:
        return []
    urls: list[str] = []
    platform_api = get_runtime_platform_api_port()
    for ref in refs:
        if ref.startswith(("http://", "https://", "data:")):
            if ref not in urls:
                urls.append(ref)
            if len(urls) >= max_images:
                break
            continue

        resolved = ""
        if platform_api is not None:
            try:
                resolved = str(await platform_api.resolve_file_url(ref) or "").strip()
            except Exception:
                resolved = ""
        candidate = resolved or ref
        if candidate.startswith(("http://", "https://", "data:")) and candidate not in urls:
            urls.append(candidate)
        if len(urls) >= max_images:
            break
    return urls


async def resolve_image_urls(envelope: EventEnvelope, max_images: int) -> list[str]:
    """兼容命名：解析 envelope 中图片资源为可用 URL。"""
    return await _resolve_image_urls_from_envelope(envelope, max_images=max_images)


async def check_at_me_anywhere(envelope: EventEnvelope) -> bool:
    """检查消息是否 @ 机器人（EventEnvelope 版本）。"""
    return check_at_me_from_envelope(envelope)


async def _is_private_message(envelope: EventEnvelope) -> bool:
    return is_private_message_from_envelope(envelope)


async def check_proactive(envelope: EventEnvelope) -> bool:
    """检查是否触发主动发言（二级触发：感知层）。"""
    if is_self_message_from_envelope(envelope):
        return False

    ctx = build_event_context_from_envelope(envelope)
    group_id_str = str(ctx.group_id or "")
    if not group_id_str:
        return False

    touch_proactive_group(group_id_str)
    prune_proactive_state()

    if not bool(getattr(plugin_config, "mika_active_reply_ltm_enabled", True)):
        return False

    active_reply_whitelist = getattr(plugin_config, "mika_active_reply_whitelist", []) or []
    if active_reply_whitelist:
        allowed = {str(x) for x in active_reply_whitelist}
        if group_id_str not in allowed:
            return False

    active_reply_probability = float(
        getattr(plugin_config, "mika_active_reply_probability", 1.0) or 1.0
    )

    def _pass_active_probability() -> bool:
        if active_reply_probability >= 1:
            return True
        return random.random() <= max(0.0, active_reply_probability)

    if ctx.is_tome:
        return False

    if plugin_config.mika_group_whitelist:
        allowed = {str(x) for x in plugin_config.mika_group_whitelist}
        if group_id_str not in allowed:
            return False

    text = ctx.plaintext or ""
    has_image = any(part.kind == "image" for part in envelope.content_parts)

    text_lower = text.lower()
    if any(k.lower() in text_lower for k in plugin_config.mika_proactive_keywords):
        last_time = _proactive_cooldowns.get(group_id_str, 0)
        current_time = time.monotonic()
        min_keyword_cooldown = max(1, int(plugin_config.mika_proactive_keyword_cooldown))
        if current_time - last_time < min_keyword_cooldown:
            return False
        if not _pass_active_probability():
            return False
        metrics.proactive_trigger_total += 1
        return True

    if plugin_config.mika_proactive_rate <= 0:
        return False
    if len(text) <= plugin_config.mika_proactive_ignore_len and not has_image:
        return False

    heat = heat_monitor.get_heat(group_id_str)
    if heat < plugin_config.mika_heat_threshold:
        return False

    last_time = _proactive_cooldowns.get(group_id_str, 0)
    current_time = time.monotonic()
    if current_time - last_time < plugin_config.mika_proactive_cooldown:
        return False

    message_count = _proactive_message_counts.get(group_id_str, 0)
    if message_count < plugin_config.mika_proactive_cooldown_messages:
        return False

    has_topic = False
    if text:
        try:
            from .utils.semantic_matcher import semantic_matcher

            is_match, _, _ = semantic_matcher.check_similarity(text)
            if is_match:
                has_topic = True
        except Exception as exc:
            log.debug(f"[主动发言] 语义匹配异常: {exc}")
            has_topic = False

    if not has_topic:
        return False
    if random.random() > plugin_config.mika_proactive_rate:
        return False
    if not _pass_active_probability():
        return False

    metrics.proactive_trigger_total += 1
    return True


async def _handle_proactive(envelope: EventEnvelope) -> None:
    """主动发言处理（二级触发：认知层）。"""
    ctx = build_event_context_from_envelope(envelope)
    if not ctx.is_group or not ctx.group_id:
        return

    parsed_text = ""
    try:
        parsed_text, _ = await parse_message_with_mentions(envelope)
        parsed_text = (parsed_text or "").strip()
    except Exception as exc:
        log.debug(f"[主动发言][@解析] parse_message_with_mentions 失败，回退 plaintext: {exc}")
        parsed_text = ""

    plaintext = (ctx.plaintext or "").strip()
    trigger_text = parsed_text or plaintext

    group_id = str(ctx.group_id)
    _proactive_cooldowns[group_id] = time.monotonic()
    _proactive_message_counts[group_id] = 0
    touch_proactive_group(group_id)

    mika_client = get_runtime_client()
    context = await mika_client.get_context(str(ctx.user_id), group_id)
    temp_context = list(context)[-15:]
    nickname = ctx.sender_name or "User"
    temp_context.append({"role": "user", "content": trigger_text, "nickname": nickname})

    heat = heat_monitor.get_heat(group_id)
    result = await mika_client.judge_proactive_intent(temp_context, heat)
    if not result.get("should_reply"):
        metrics.proactive_reject_total += 1
        return

    try:
        await handle_group(
            envelope,
            plugin_config=plugin_config,
            mika_client=mika_client,
            is_proactive=True,
            proactive_reason="semantic",
        )
    except Exception as exc:
        log.exception(f"[Core->Handlers] proactive_group_failed | err={exc}")


async def _cache_images(envelope: EventEnvelope) -> None:
    """缓存群聊中的图片消息并记录上下文。"""
    ctx = build_event_context_from_envelope(envelope)
    if is_self_message_from_envelope(envelope):
        return
    if not ctx.is_group or not ctx.group_id:
        return

    group_id = str(ctx.group_id)
    heat_monitor.record_message(group_id)
    _proactive_message_counts[group_id] = _proactive_message_counts.get(group_id, 0) + 1
    touch_proactive_group(group_id)

    if plugin_config.mika_group_whitelist:
        allowed = {str(x) for x in plugin_config.mika_group_whitelist}
        if group_id not in allowed:
            return

    image_urls = await resolve_image_urls(envelope, int(plugin_config.mika_max_images))
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
        client = get_runtime_client()
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
                parsed_text, _ = await parse_message_with_mentions(envelope)
                record_text = (parsed_text or "").strip()
            except Exception as exc:
                log.warning(f"[上下文记录] 富文本解析失败，使用降级占位: {exc}")
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
    except Exception as exc:
        log.warning(f"上下文记录失败: {exc}")


__all__ = [
    "plugin_config",
    "_proactive_cooldowns",
    "_proactive_message_counts",
    "check_at_me_from_envelope",
    "is_private_message_from_envelope",
    "is_self_message_from_envelope",
    "check_at_me_anywhere",
    "_is_private_message",
    "check_proactive",
    "_handle_proactive",
    "_cache_images",
    "resolve_image_urls",
    "handle_group",
    "parse_message_with_mentions",
]
