"""Reply sending policy helpers extracted from handlers.py."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

from .contracts import ContentPart, SendMessageAction
from .infra.logging import logger as log
from .ports.message import StreamMessagePort


@dataclass
class SendStageResult:
    ok: bool
    method: str
    error: str = ""


@dataclass
class StageOverrides:
    stream_text: Optional[Callable[..., Awaitable[SendStageResult]]] = None
    split_text: Optional[Callable[..., Awaitable[SendStageResult]]] = None
    short_quote_text: Optional[Callable[..., Awaitable[SendStageResult]]] = None
    long_forward: Optional[Callable[..., Awaitable[SendStageResult]]] = None
    render_image: Optional[Callable[..., Awaitable[SendStageResult]]] = None
    text_fallback: Optional[Callable[..., Awaitable[SendStageResult]]] = None


def _build_final_reply_text(reply_text: str, is_proactive: bool) -> str:
    if is_proactive:
        return f"【自主回复】\n{reply_text}"
    return reply_text


def _relabel_stage(result: SendStageResult, method: str) -> SendStageResult:
    return SendStageResult(ok=result.ok, method=method, error=result.error)


async def _stage_message_port(
    final_text: str,
    *,
    session_id: str,
    reply_to: str,
    message_port_getter: Callable[[], Any],
) -> SendStageResult:
    message_port = message_port_getter()
    if message_port is None:
        return SendStageResult(ok=False, method="message_port", error="port_unavailable")

    action = SendMessageAction(
        type="send_message",
        session_id=session_id,
        parts=[ContentPart(kind="text", text=final_text)],
        reply_to=reply_to,
        meta={"source": "send_reply_with_policy"},
    )
    try:
        result = await message_port.send_message(action)
    except Exception as exc:
        return SendStageResult(ok=False, method="message_port", error=f"port_error:{exc}")

    if isinstance(result, dict) and result.get("ok") is False:
        return SendStageResult(
            ok=False,
            method="message_port",
            error=str(result.get("error", "port_send_failed")),
        )
    return SendStageResult(ok=True, method="message_port", error="")


async def _stage_split_text(
    final_text: str,
    *,
    session_id: str,
    reply_to: str,
    split_threshold: int,
    split_max_chunks: int,
    message_port_getter: Callable[[], Any],
    split_message_text_fn: Callable[..., list[str]],
) -> SendStageResult:
    chunks = split_message_text_fn(final_text, max_length=split_threshold)
    if len(chunks) <= 1:
        return SendStageResult(ok=False, method="split_text", error="split_not_needed")

    max_chunks = int(split_max_chunks or 0)
    if max_chunks < 2:
        max_chunks = 2
    if len(chunks) > max_chunks:
        merged_tail = "".join(chunks[max_chunks - 1 :])
        chunks = [*chunks[: max_chunks - 1], merged_tail]

    for index, chunk in enumerate(chunks):
        stage_result = await _stage_message_port(
            chunk,
            session_id=session_id,
            reply_to=reply_to if index == 0 else "",
            message_port_getter=message_port_getter,
        )
        if not stage_result.ok:
            return SendStageResult(
                ok=False,
                method="split_text",
                error=f"chunk_{index + 1}_failed:{stage_result.error}",
            )
    return SendStageResult(ok=True, method=f"split_text:{len(chunks)}")


async def _stage_stream_text(
    chunks: list[str],
    *,
    session_id: str,
    reply_to: str,
    message_port_getter: Callable[[], Any],
    stream_chunk_chars: int,
    stream_delay_ms: int,
    stream_mode: str,
) -> SendStageResult:
    message_port = message_port_getter()
    if message_port is None:
        return SendStageResult(ok=False, method="stream_text", error="port_unavailable")
    if not isinstance(message_port, StreamMessagePort):
        return SendStageResult(ok=False, method="stream_text", error="stream_not_supported")

    normalized_chunks = [str(item or "") for item in list(chunks or []) if str(item or "")]
    if not normalized_chunks:
        return SendStageResult(ok=False, method="stream_text", error="empty_stream")

    async def _chunk_iter() -> AsyncIterator[str]:
        for chunk in normalized_chunks:
            yield chunk

    try:
        result = await message_port.send_stream(
            session_id=session_id,
            chunks=_chunk_iter(),
            reply_to=reply_to,
            meta={
                "source": "send_reply_with_policy",
                "stream_mode": str(stream_mode or "chunked"),
                "chunk_chars": int(stream_chunk_chars),
                "chunk_delay_ms": int(stream_delay_ms),
            },
        )
    except Exception as exc:
        return SendStageResult(ok=False, method="stream_text", error=f"stream_error:{exc}")

    if isinstance(result, dict) and result.get("ok") is False:
        return SendStageResult(
            ok=False,
            method="stream_text",
            error=str(result.get("error", "stream_send_failed")),
        )
    return SendStageResult(ok=True, method=f"stream_text:{len(normalized_chunks)}", error="")


async def _stage_short_quote_text(
    final_text: str,
    *,
    session_id: str,
    reply_to: str,
    message_port_getter: Callable[[], Any],
) -> SendStageResult:
    return _relabel_stage(
        await _stage_message_port(
            final_text,
            session_id=session_id,
            reply_to=reply_to,
            message_port_getter=message_port_getter,
        ),
        "quote_text",
    )


async def _stage_text_fallback(
    final_text: str,
    *,
    session_id: str,
    reply_to: str,
    message_port_getter: Callable[[], Any],
) -> SendStageResult:
    return _relabel_stage(
        await _stage_message_port(
            final_text,
            session_id=session_id,
            reply_to=reply_to,
            message_port_getter=message_port_getter,
        ),
        "quote_text_fallback",
    )


async def _stage_long_forward(
    envelope: Any,
    final_text: str,
    *,
    plugin_config: Any,
    send_forward_msg_fn: Callable[..., Awaitable[bool]],
) -> SendStageResult:
    ok = await send_forward_msg_fn(envelope, final_text, plugin_config=plugin_config)
    return SendStageResult(ok=bool(ok), method="forward", error="" if ok else "forward_failed")


async def _stage_render_image(
    envelope: Any,
    final_text: str,
    *,
    plugin_config: Any,
    send_rendered_image_with_quote_fn: Callable[..., Awaitable[bool]],
) -> SendStageResult:
    ok = await send_rendered_image_with_quote_fn(
        envelope,
        final_text,
        plugin_config=plugin_config,
    )
    return SendStageResult(
        ok=bool(ok),
        method="quote_image",
        error="" if ok else "render_or_send_failed",
    )


async def send_rendered_image_with_quote(
    envelope: Any,
    content: str,
    *,
    plugin_config: Any,
    message_port_getter: Callable[[], Any],
    context_builder: Callable[[Any], Any],
    render_text_to_png_bytes_fn: Callable[..., bytes],
) -> bool:
    """将文本渲染为图片并发送（优先引用）。"""
    try:
        image_bytes = render_text_to_png_bytes_fn(
            content,
            max_width=int(getattr(plugin_config, "mika_long_reply_image_max_width", 960) or 960),
            font_size=int(getattr(plugin_config, "mika_long_reply_image_font_size", 24) or 24),
            max_chars=int(getattr(plugin_config, "mika_long_reply_image_max_chars", 12000) or 12000),
        )
    except Exception as exc:
        log.warning(f"文本渲染图片失败，跳过图片兜底: {exc}")
        return False

    image_base64 = base64.b64encode(image_bytes).decode("ascii")
    ctx = context_builder(envelope)
    message_port = message_port_getter()
    if message_port is None:
        log.warning("图片发送失败：message_port 不可用")
        return False

    action = SendMessageAction(
        type="send_message",
        session_id=ctx.session_key,
        parts=[ContentPart(kind="image", asset_ref=f"base64://{image_base64}")],
        reply_to=str(ctx.message_id or ""),
        meta={"source": "send_rendered_image_with_quote"},
    )
    try:
        result = await message_port.send_message(action)
    except Exception as exc:
        log.warning(f"message_port 图片发送异常 | error={exc}")
        return False
    if isinstance(result, dict) and result.get("ok") is False:
        log.warning(f"message_port 图片发送失败 | error={result.get('error', 'unknown')}")
        return False
    return True


async def send_forward_msg(
    envelope: Any,
    content: str,
    *,
    plugin_config: Any,
    message_port_getter: Callable[[], Any],
    context_builder: Callable[[Any], Any],
) -> bool:
    """发送转发消息（用于长文本）。"""
    nodes = [
        {
            "type": "node",
            "data": {
                "name": plugin_config.mika_bot_display_name,
                "uin": str(envelope.bot_self_id or ""),
                "content": content,
            },
        }
    ]

    ctx = context_builder(envelope)
    is_group = bool(ctx.is_group and ctx.group_id)

    message_port = message_port_getter()
    if message_port is not None and hasattr(message_port, "send_forward"):
        try:
            result = await message_port.send_forward(ctx.session_key, nodes)
            if isinstance(result, dict) and result.get("ok"):
                if is_group:
                    log.debug(f"转发消息发送成功(message_port) | group={ctx.group_id}")
                else:
                    log.debug(f"转发消息发送成功(message_port) | user={ctx.user_id}")
                return True
        except Exception as exc:
            log.warning(f"message_port.send_forward 失败 | error={exc}")

    log.warning("转发消息发送失败：message_port 不可用或平台不支持")
    return False


async def send_reply_with_policy(
    envelope: Any,
    reply_text: str,
    *,
    is_proactive: bool,
    plugin_config: Any,
    reply_chunks: Optional[list[str]] = None,
    context_builder: Callable[[Any], Any],
    message_port_getter: Callable[[], Any],
    split_message_text_fn: Callable[..., list[str]],
    apply_content_safety_filter_fn: Callable[..., Any],
    send_forward_msg_fn: Callable[..., Awaitable[bool]],
    send_rendered_image_with_quote_fn: Callable[..., Awaitable[bool]],
    stage_overrides: Optional[StageOverrides] = None,
) -> None:
    """统一回复发送策略。"""
    final_text = _build_final_reply_text(reply_text, is_proactive=is_proactive)
    safety_result = apply_content_safety_filter_fn(
        final_text,
        enabled=bool(getattr(plugin_config, "mika_content_safety_enabled", False)),
        action=str(getattr(plugin_config, "mika_content_safety_action", "replace") or "replace"),
        block_keywords=list(getattr(plugin_config, "mika_content_safety_block_keywords", []) or []),
        replacement=str(
            getattr(
                plugin_config,
                "mika_content_safety_replacement",
                "抱歉，这条回复不适合直接发送，我换个说法。",
            )
            or ""
        ),
    )
    if safety_result.filtered:
        log.warning(
            f"[内容安全] 已触发过滤 | action={safety_result.action} | hits={len(safety_result.hits)}"
        )
        if safety_result.action == "drop":
            return
        final_text = safety_result.text

    threshold = int(getattr(plugin_config, "mika_forward_threshold", 300) or 300)
    split_enabled = bool(getattr(plugin_config, "mika_message_split_enabled", False))
    split_threshold = int(getattr(plugin_config, "mika_message_split_threshold", 300) or 300)
    split_max_chunks = int(getattr(plugin_config, "mika_message_split_max_chunks", 6) or 6)
    stream_enabled = bool(getattr(plugin_config, "mika_reply_stream_enabled", False))
    stream_min_chars = int(getattr(plugin_config, "mika_reply_stream_min_chars", 120) or 120)
    stream_chunk_chars = int(getattr(plugin_config, "mika_reply_stream_chunk_chars", 80) or 80)
    stream_delay_ms = int(getattr(plugin_config, "mika_reply_stream_delay_ms", 0) or 0)
    stream_mode = str(getattr(plugin_config, "mika_reply_stream_mode", "chunked") or "chunked").strip().lower()
    is_long = len(final_text) >= max(1, threshold)
    overrides = stage_overrides or StageOverrides()
    stage_stream_text = overrides.stream_text or _stage_stream_text
    stage_split_text = overrides.split_text or _stage_split_text
    stage_short_quote_text = overrides.short_quote_text or _stage_short_quote_text
    stage_long_forward = overrides.long_forward or _stage_long_forward
    stage_render_image = overrides.render_image or _stage_render_image
    stage_text_fallback = overrides.text_fallback or _stage_text_fallback
    ctx = context_builder(envelope)
    session = ctx.session_key
    reply_to = str(getattr(ctx, "message_id", "") or "")

    stage_result: Optional[SendStageResult] = None

    if stream_enabled and len(final_text) >= max(1, stream_min_chars):
        candidate_chunks = [str(item or "") for item in list(reply_chunks or []) if str(item or "")]
        if len(candidate_chunks) <= 1:
            candidate_chunks = split_message_text_fn(final_text, max_length=max(1, stream_chunk_chars))
        if len(candidate_chunks) > 1:
            stage_result = await stage_stream_text(
                candidate_chunks,
                session_id=session,
                reply_to=reply_to,
                message_port_getter=message_port_getter,
                stream_chunk_chars=max(1, stream_chunk_chars),
                stream_delay_ms=max(0, stream_delay_ms),
                stream_mode=stream_mode if stream_mode in {"chunked", "final_only"} else "chunked",
            )
            if stage_result.ok:
                log.info(f"[发送策略] session={session} | method={stage_result.method} | is_long={is_long}")
                return

    if split_enabled and len(final_text) >= max(1, split_threshold):
        stage_result = await stage_split_text(
            final_text,
            session_id=session,
            reply_to=reply_to,
            split_threshold=split_threshold,
            split_max_chunks=max(2, split_max_chunks),
            message_port_getter=message_port_getter,
            split_message_text_fn=split_message_text_fn,
        )
        if stage_result.ok:
            log.info(f"[发送策略] session={session} | method={stage_result.method} | is_long={is_long}")
            return

    if not is_long:
        stage_result = await stage_short_quote_text(
            final_text,
            session_id=session,
            reply_to=reply_to,
            message_port_getter=message_port_getter,
        )
        if stage_result.ok:
            log.info(f"[发送策略] session={session} | method={stage_result.method} | is_long={is_long}")
            return
    else:
        stage_result = await stage_long_forward(
            envelope,
            final_text,
            plugin_config=plugin_config,
            send_forward_msg_fn=send_forward_msg_fn,
        )
        if stage_result.ok:
            log.info(f"[发送策略] session={session} | method={stage_result.method} | is_long={is_long}")
            return

    if bool(getattr(plugin_config, "mika_long_reply_image_fallback_enabled", True)):
        stage_result = await stage_render_image(
            envelope,
            final_text,
            plugin_config=plugin_config,
            send_rendered_image_with_quote_fn=send_rendered_image_with_quote_fn,
        )
        if stage_result.ok:
            log.info(f"[发送策略] session={session} | method={stage_result.method} | is_long={is_long}")
            return

    stage_result = await stage_text_fallback(
        final_text,
        session_id=session,
        reply_to=reply_to,
        message_port_getter=message_port_getter,
    )
    if stage_result.ok:
        log.info(f"[发送策略] session={session} | method={stage_result.method} | is_long={is_long}")
        return

    log.error(
        f"[发送策略] session={session} | method={stage_result.method} | "
        f"is_long={is_long} | error={stage_result.error}"
    )
