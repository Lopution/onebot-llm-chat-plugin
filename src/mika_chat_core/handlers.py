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
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from .config import Config
from .contracts import ContentPart, EventEnvelope, SessionKey
from .ports.bot_api import PlatformApiPort
from .runtime import (
    get_client as get_runtime_client,
    get_config as get_runtime_config,
    get_message_port as get_runtime_message_port,
    get_platform_api_port as get_runtime_platform_api_port,
)
from .infra.logging import logger as log
from .infra.metrics_store import get_metrics_timeline_store
from .utils.recent_images import get_image_cache
from .utils.history_image_policy import (
    determine_history_image_action,
    build_image_mapping_hint,
    build_candidate_hint,
    HistoryImageAction,
)
from .utils.image_collage import create_collage_from_urls, is_collage_available
from .metrics import metrics
from .planning.relevance_filter import get_relevance_filter
from .utils.session_lock import get_session_lock_manager
from .utils.event_context import build_event_context_from_envelope
from .utils.text_image_renderer import render_text_to_png_bytes
from .utils.message_splitter import split_message_text
from .security.content_safety import apply_content_safety_filter
from .error_policy import swallow as _swallow
from .handlers_flow import FlowDeps, run_group_locked_flow, run_private_locked_flow
from .handlers_parse import parse_envelope_with_mentions as service_parse_envelope_with_mentions
from .handlers_history_image import (
    apply_history_image_strategy_flow as service_apply_history_image_strategy_flow,
    cfg as service_cfg,
    dedupe_image_urls as service_dedupe_image_urls,
    history_collage_enabled as service_history_collage_enabled,
    resolve_image_urls_via_port_flow as service_resolve_image_urls_via_port_flow,
)
from .handlers_offline_sync import (
    sync_offline_messages_task_flow as service_sync_offline_messages_task_flow,
)
from .handlers_proactive import (
    build_proactive_chatroom_injection as service_build_proactive_chatroom_injection,
    render_transcript_content as service_render_transcript_content,
)
from .handlers_reply import (
    SendStageResult,
    StageOverrides,
    _stage_long_forward,
    _stage_render_image,
    _stage_short_quote_text,
    _stage_split_text,
    _stage_stream_text,
    _stage_text_fallback,
    send_forward_msg as service_send_forward_msg,
    send_rendered_image_with_quote as service_send_rendered_image_with_quote,
    send_reply_with_policy as service_send_reply_with_policy,
)


@dataclass
class RequestContextPayload:
    """统一的请求上下文载荷。"""

    ctx: Any
    message_text: str
    image_urls: List[str]
    reply_images: List[str]


def _make_session_key(*, user_id: str, group_id: Optional[str]) -> str:
    """与 SQLiteContextStore 的 key 规则对齐，确保同一会话串行。"""
    if group_id:
        return f"group:{group_id}"
    return f"private:{user_id}"


def _cfg(plugin_config: Config, key: str, default: Any) -> Any:
    """读取配置项并提供稳定默认值（不修改配置对象本身）。"""
    return service_cfg(plugin_config, key, default)


def _resolve_llm_cfg(plugin_config: Config) -> dict[str, Any]:
    """兼容获取 LLM 配置（Config 或测试中的简化对象）。"""
    getter = getattr(plugin_config, "get_llm_config", None)
    if callable(getter):
        try:
            resolved = getter()
            if isinstance(resolved, dict):
                return dict(resolved)
        except Exception:
            _swallow("get_llm_config() failed, falling back to attr-based config", exc_info=True)

    provider = str(_cfg(plugin_config, "llm_provider", "openai_compat") or "openai_compat").strip().lower()
    base_url = str(_cfg(plugin_config, "llm_base_url", "") or "").strip().rstrip("/")
    model = str(_cfg(plugin_config, "llm_model", "") or "").strip()
    fast_model = str(_cfg(plugin_config, "llm_fast_model", "") or "").strip()
    api_key = str(_cfg(plugin_config, "llm_api_key", "") or "").strip()
    api_keys = [api_key] if api_key else []
    return {
        "provider": provider,
        "base_url": base_url,
        "model": model,
        "fast_model": fast_model,
        "api_keys": api_keys,
        "extra_headers": {},
    }


def _history_collage_enabled(plugin_config: Config) -> bool:
    """历史拼图开关（新配置优先，旧配置兼容）。"""
    return service_history_collage_enabled(plugin_config)


def _normalize_message_text_from_parts(parts: list[ContentPart]) -> str:
    return " ".join(
        str(part.text or "").strip()
        for part in parts
        if part.kind == "text" and str(part.text or "").strip()
    ).strip()


def _dedupe_image_urls(urls: list[str], max_images: int) -> list[str]:
    return service_dedupe_image_urls(urls, max_images)


async def _apply_history_image_strategy(
    *,
    ctx: Any,
    message_text: str,
    image_urls: list[str],
    sender_name: str,
    plugin_config: Config,
    mika_client: Any,
) -> tuple[list[str], Optional[str]]:
    """统一处理历史图片策略，返回(最终图片列表, system 注入提示)。"""
    return await service_apply_history_image_strategy_flow(
        ctx=ctx,
        message_text=message_text,
        image_urls=image_urls,
        sender_name=sender_name,
        plugin_config=plugin_config,
        mika_client=mika_client,
        log_obj=log,
        metrics_obj=metrics,
        get_image_cache_fn=get_image_cache,
        determine_history_image_action_fn=determine_history_image_action,
        build_image_mapping_hint_fn=build_image_mapping_hint,
        build_candidate_hint_fn=build_candidate_hint,
        history_image_action_cls=HistoryImageAction,
        create_collage_from_urls_fn=create_collage_from_urls,
        is_collage_available_fn=is_collage_available,
    )


async def _resolve_image_urls_via_port(
    content_parts: List[ContentPart],
    *,
    platform_api: Optional[PlatformApiPort] = None,
    max_images: int = 10,
) -> list[str]:
    """从标准化 content parts 解析可用图片 URL。"""
    return await service_resolve_image_urls_via_port_flow(
        content_parts,
        platform_api=platform_api,
        max_images=max_images,
    )


async def build_request_context_payload_from_envelope(
    envelope: EventEnvelope,
    plugin_config: Config,
    *,
    platform_api: Optional[PlatformApiPort] = None,
) -> RequestContextPayload:
    """统一构建一次请求输入（仅依赖 EventEnvelope + ports）。"""
    ctx = build_event_context_from_envelope(envelope)
    max_images = max(0, int(_cfg(plugin_config, "mika_max_images", 10) or 10))

    message_text = (ctx.plaintext or "").strip() or _normalize_message_text_from_parts(envelope.content_parts)
    reply_images: List[str] = []

    if ctx.is_group:
        message_text, reply_images = await parse_envelope_with_mentions(
            envelope,
            platform_api=platform_api,
            max_images=max_images,
            quote_image_caption_enabled=bool(
                _cfg(plugin_config, "mika_quote_image_caption_enabled", True)
            ),
            quote_image_caption_prompt=str(
                _cfg(plugin_config, "mika_quote_image_caption_prompt", "[引用图片共{count}张]")
            ),
            quote_image_caption_timeout_seconds=float(
                _cfg(plugin_config, "mika_quote_image_caption_timeout_seconds", 3.0)
            ),
        )
        if not message_text:
            message_text = (ctx.plaintext or "").strip() or _normalize_message_text_from_parts(
                envelope.content_parts
            )

    image_urls = await _resolve_image_urls_via_port(
        envelope.content_parts,
        platform_api=platform_api,
        max_images=max_images,
    )

    if reply_images:
        image_urls = _dedupe_image_urls([*image_urls, *reply_images], max_images=max_images)
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


async def build_request_context_payload(
    envelope: EventEnvelope,
    plugin_config: Optional[Config] = None,
) -> RequestContextPayload:
    """统一构建一次请求输入（兼容别名）。"""
    if plugin_config is None:
        plugin_config = get_config()
    return await build_request_context_payload_from_envelope(
        envelope,
        plugin_config,
        platform_api=get_runtime_platform_api_port(),
    )


def _render_transcript_content(content: Any) -> str:
    return service_render_transcript_content(content)


def _build_proactive_chatroom_injection(
    history: List[Dict[str, Any]],
    *,
    bot_name: str,
    max_lines: int,
    trigger_message: str = "",
    trigger_sender: str = "",
) -> str:
    return service_build_proactive_chatroom_injection(
        history,
        bot_name=bot_name,
        max_lines=max_lines,
        trigger_message=trigger_message,
        trigger_sender=trigger_sender,
    )

# ==================== 兼容旧测试的导出（thin wrapper） ====================

def get_mika_client():
    """兼容旧 tests：历史上测试 patch `mika_chat.handlers.get_mika_client`。"""
    return get_runtime_client()


def get_config():
    """兼容旧 tests：统一通过 runtime 获取配置。"""
    return get_runtime_config()


def get_user_profile_store():
    """兼容旧 tests：历史上测试会 patch `mika_chat.handlers.get_user_profile_store`。

    当前实现的真实入口在 [`utils.user_profile.get_user_profile_store()`](mika_chat_core/utils/user_profile.py:1)。
    """
    from .utils.user_profile import get_user_profile_store as _get

    return _get()

def _handle_task_exception(task: asyncio.Task[Any]) -> None:
    """处理后台任务的异常，防止异常被静默忽略。

    .. deprecated::
        由 TaskSupervisor 统一管理，保留仅为兼容外部引用。
    """
    if task.done() and not task.cancelled():
        exc = task.exception()
        if exc:
            log.error(f"后台任务异常: {exc}", exc_info=exc)


async def sync_offline_messages() -> None:
    """Bot 启动时同步离线期间的群聊消息（后台异步执行）。"""
    from .runtime import get_task_supervisor

    get_task_supervisor().spawn(
        _sync_offline_messages_task(),
        name="sync_offline_messages",
        owner="startup",
    )


async def _sync_offline_messages_task() -> None:
    """同步离线消息的具体逻辑"""
    await service_sync_offline_messages_task_flow(
        get_config_fn=get_config,
        get_mika_client_fn=get_mika_client,
        get_runtime_platform_api_port_fn=get_runtime_platform_api_port,
        sleep_fn=asyncio.sleep,
        log_obj=log,
    )



async def handle_reset(
    envelope: EventEnvelope,
    plugin_config: Config = None,
    mika_client = None,
):
    """处理清空记忆指令
    
    Args:
        envelope: 标准化事件信封
        plugin_config: 插件配置（可选，默认通过依赖注入获取）
        mika_client: API 客户端（可选，默认通过依赖注入获取）
    """
    # 使用依赖注入获取资源（如果未提供）
    if plugin_config is None:
        plugin_config = get_config()
    if mika_client is None:
        mika_client = get_mika_client()

    ctx = build_event_context_from_envelope(envelope)
    user_id = ctx.user_id
    group_id = ctx.group_id
    session_key = ctx.session_key
    
    log.info(f"收到清空记忆指令 | user={user_id} | group={group_id or 'private'}")
    
    # 使用异步方法支持持久化存储
    lock = get_session_lock_manager().get_lock(session_key)
    async with lock:
        await mika_client.clear_context_async(user_id, group_id)
        
        log.success(f"记忆已清空 | user={user_id} | group={group_id or 'private'}")
        await send_reply_with_policy(
            envelope,
            "好的呢~ Mika 把刚才聊的内容都忘掉啦，我们重新开始吧~",
            is_proactive=False,
            plugin_config=plugin_config,
        )


async def handle_private(
    envelope: EventEnvelope,
    plugin_config: Config = None,
    mika_client = None,
):
    """处理私聊消息。

    当用户向机器人发送私聊消息时调用此函数。
    会自动提取文本和图片，构建带用户标签的消息，并调用 Mika API 获取回复。

    Args:
        envelope: 标准化消息事件。
        plugin_config: 插件配置对象（可选，默认通过依赖注入获取）。
        mika_client: API 客户端（可选，默认通过依赖注入获取）。

    Note:
        - 如果 mika_reply_private 配置为 False，则直接返回不处理
        - 主人（master）发送的消息会被标记为 "⭐Sensei"
        - 支持多模态消息（文本 + 图片）
        - 长文本回复会自动转为转发消息发送
    """
    # 使用依赖注入获取资源（如果未提供）
    if plugin_config is None:
        plugin_config = get_config()
    
    if not plugin_config.mika_reply_private:
        return

    ctx = build_event_context_from_envelope(envelope)
    session_key = ctx.session_key
    lock = get_session_lock_manager().get_lock(session_key)
    async with lock:
        await _handle_private_locked(
            envelope=envelope,
            plugin_config=plugin_config,
            mika_client=mika_client,
        )


async def _handle_private_locked(
    *,
    envelope: EventEnvelope,
    plugin_config: Config,
    mika_client,
) -> None:
    payload = await build_request_context_payload_from_envelope(
        envelope,
        plugin_config,
        platform_api=get_runtime_platform_api_port(),
    )
    ctx = payload.ctx
    message_text = payload.message_text
    image_urls = payload.image_urls

    if not message_text and not image_urls:
        return

    if mika_client is None:
        mika_client = get_mika_client()

    await run_private_locked_flow(
        envelope=envelope,
        ctx=ctx,
        message_text=message_text,
        image_urls=image_urls,
        plugin_config=plugin_config,
        mika_client=mika_client,
        deps=FlowDeps(
            apply_history_image_strategy=_apply_history_image_strategy,
            send_reply_with_policy=send_reply_with_policy,
            get_metrics_timeline_store=get_metrics_timeline_store,
        ),
    )


async def parse_envelope_with_mentions(
    envelope: EventEnvelope,
    *,
    platform_api: Optional[PlatformApiPort] = None,
    max_images: int = 10,
    quote_image_caption_enabled: bool = True,
    quote_image_caption_prompt: str = "[引用图片共{count}张]",
    quote_image_caption_timeout_seconds: float = 3.0,
) -> tuple[str, list[str]]:
    """解析 EventEnvelope 并保留 @ 与引用语义。"""
    return await service_parse_envelope_with_mentions(
        envelope=envelope,
        platform_api=platform_api,
        max_images=max_images,
        quote_image_caption_enabled=quote_image_caption_enabled,
        quote_image_caption_prompt=quote_image_caption_prompt,
        quote_image_caption_timeout_seconds=quote_image_caption_timeout_seconds,
        resolve_image_urls_via_port=_resolve_image_urls_via_port,
    )


async def parse_message_with_mentions(
    envelope: EventEnvelope,
    *,
    max_images: int = 10,
    quote_image_caption_enabled: bool = True,
    quote_image_caption_prompt: str = "[引用图片共{count}张]",
    quote_image_caption_timeout_seconds: float = 3.0,
) -> tuple[str, list[str]]:
    """解析 EventEnvelope 并保留 @ 与引用语义。"""
    return await parse_envelope_with_mentions(
        envelope,
        platform_api=get_runtime_platform_api_port(),
        max_images=max_images,
        quote_image_caption_enabled=quote_image_caption_enabled,
        quote_image_caption_prompt=quote_image_caption_prompt,
        quote_image_caption_timeout_seconds=quote_image_caption_timeout_seconds,
    )


async def handle_group(
    envelope: EventEnvelope,
    plugin_config: Config = None,
    mika_client = None,
    is_proactive: bool = False,
    proactive_reason: str = None
):
    """处理群聊消息（@机器人时触发）。



    当用户在群聊中 @ 机器人时调用此函数。
    会验证群组白名单、提取消息内容、更新用户档案，并调用 Mika API 获取回复。

    Args:
        envelope: 标准化群聊事件。
        plugin_config: 插件配置对象（可选，默认通过依赖注入获取）。
        mika_client: API 客户端（可选，默认通过依赖注入获取）。

    Note:
        - 如果 mika_reply_at 配置为 False，则直接返回不处理
        - 群组必须在白名单中才会响应（如果配置了白名单）
        - 主人发送的消息会被标记为 "⭐Sensei"
        - 普通用户消息标签格式为 "{昵称}({平台用户ID})"
        - 会自动从消息中提取用户信息并更新用户档案
        - 支持多模态消息（文本 + 图片）
        - 长文本回复会自动转为转发消息发送
    """
    ctx = build_event_context_from_envelope(envelope)
    log.info("[群聊Handler] ========== 开始处理 ==========")
    log.info(f"[群聊Handler] group={ctx.group_id} | user={ctx.user_id}")
    log.info(f"[群聊Handler] 消息内容: {(ctx.plaintext or '')[:50]}")
    
    # 使用依赖注入获取资源（如果未提供）
    if plugin_config is None:
        plugin_config = get_config()
    if mika_client is None:
        mika_client = get_mika_client()

    if not ctx.is_group or not ctx.group_id:
        return
    
    if not plugin_config.mika_reply_at and not is_proactive:
        log.debug("[群聊Handler] mika_reply_at=False, 跳过处理")
        return
    
    if plugin_config.mika_group_whitelist:
        allowed = {str(x) for x in plugin_config.mika_group_whitelist}
        if ctx.group_id not in allowed:
            log.debug(f"群 {ctx.group_id} 不在白名单中，跳过处理")
            return

    session_key = ctx.session_key
    lock = get_session_lock_manager().get_lock(session_key)
    async with lock:
        await _handle_group_locked(
            envelope=envelope,
            plugin_config=plugin_config,
            mika_client=mika_client,
            is_proactive=is_proactive,
            proactive_reason=proactive_reason,
        )
        return


async def _handle_group_locked(
    *,
    envelope: EventEnvelope,
    plugin_config: Config,
    mika_client,
    is_proactive: bool,
    proactive_reason: Optional[str],
) -> None:
    payload = await build_request_context_payload_from_envelope(
        envelope,
        plugin_config,
        platform_api=get_runtime_platform_api_port(),
    )
    ctx = payload.ctx
    if not ctx.is_group or not ctx.group_id:
        return

    raw_text = payload.message_text
    image_urls = payload.image_urls
    
    if not raw_text and not image_urls:
        return

    if mika_client is None:
        mika_client = get_mika_client()

    await run_group_locked_flow(
        envelope=envelope,
        ctx=ctx,
        raw_text=raw_text,
        image_urls=image_urls,
        plugin_config=plugin_config,
        mika_client=mika_client,
        is_proactive=is_proactive,
        proactive_reason=proactive_reason,
        deps=FlowDeps(
            apply_history_image_strategy=_apply_history_image_strategy,
            send_reply_with_policy=send_reply_with_policy,
            get_metrics_timeline_store=get_metrics_timeline_store,
            resolve_llm_cfg=_resolve_llm_cfg,
            build_proactive_chatroom_injection=_build_proactive_chatroom_injection,
            get_relevance_filter=get_relevance_filter,
            get_user_profile_store=get_user_profile_store,
        ),
    )


async def send_rendered_image_with_quote(
    envelope: EventEnvelope,
    content: str,
    plugin_config: Config = None,
) -> bool:
    """将文本渲染为图片并发送（优先引用）。"""
    if plugin_config is None:
        plugin_config = get_config()
    return await service_send_rendered_image_with_quote(
        envelope,
        content,
        plugin_config=plugin_config,
        message_port_getter=get_runtime_message_port,
        context_builder=build_event_context_from_envelope,
        render_text_to_png_bytes_fn=render_text_to_png_bytes,
    )


async def send_reply_with_policy(
    envelope: EventEnvelope,
    reply_text: str,
    *,
    is_proactive: bool,
    reply_chunks: Optional[List[str]] = None,
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
    await service_send_reply_with_policy(
        envelope,
        reply_text,
        is_proactive=is_proactive,
        reply_chunks=reply_chunks,
        plugin_config=plugin_config,
        context_builder=build_event_context_from_envelope,
        message_port_getter=get_runtime_message_port,
        split_message_text_fn=split_message_text,
        apply_content_safety_filter_fn=apply_content_safety_filter,
        send_forward_msg_fn=send_forward_msg,
        send_rendered_image_with_quote_fn=send_rendered_image_with_quote,
        stage_overrides=StageOverrides(
            stream_text=_stage_stream_text,
            split_text=_stage_split_text,
            short_quote_text=_stage_short_quote_text,
            long_forward=_stage_long_forward,
            render_image=_stage_render_image,
            text_fallback=_stage_text_fallback,
        ),
    )


async def send_forward_msg(
    envelope: EventEnvelope,
    content: str,
    plugin_config: Config = None
) -> bool:
    """发送转发消息（用于长文本）
    
    Args:
        envelope: 标准化事件信封
        content: 要发送的内容
        plugin_config: 插件配置（可选，默认通过依赖注入获取）
    """
    if plugin_config is None:
        plugin_config = get_config()

    return await service_send_forward_msg(
        envelope,
        content,
        plugin_config=plugin_config,
        message_port_getter=get_runtime_message_port,
        context_builder=build_event_context_from_envelope,
    )
