"""Chat handling flow services extracted from handlers.py.

目标：把私聊/群聊锁内主流程从 handlers.py 抽离，降低单文件复杂度。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

from .infra.logging import logger as log


@dataclass
class FlowDeps:
    apply_history_image_strategy: Callable[..., Awaitable[tuple[List[str], Optional[str]]]]
    send_reply_with_policy: Callable[..., Awaitable[None]]
    get_metrics_timeline_store: Callable[[], Any]
    resolve_llm_cfg: Optional[Callable[[Any], Dict[str, Any]]] = None
    build_proactive_chatroom_injection: Optional[Callable[..., str]] = None
    get_relevance_filter: Optional[Callable[[], Any]] = None
    get_user_profile_store: Optional[Callable[[], Any]] = None


@dataclass
class GroupFlowState:
    envelope: Any
    ctx: Any
    raw_text: str
    image_urls: List[str]
    plugin_config: Any
    mika_client: Any
    is_proactive: bool
    proactive_reason: Optional[str]
    deps: FlowDeps
    user_id_int: str = ""
    nickname: str = "Sensei"
    tag: str = ""
    cached_hint: Optional[str] = None
    injection_parts: List[str] = field(default_factory=list)
    history_override: Optional[List[Dict[str, Any]]] = None
    system_injection_content: Optional[str] = None
    reply_chunks: List[str] = field(default_factory=list)
    reply: str = ""
    stop: bool = False


@dataclass
class PrivateFlowState:
    envelope: Any
    ctx: Any
    message_text: str
    image_urls: List[str]
    plugin_config: Any
    mika_client: Any
    deps: FlowDeps
    tag: str = "私聊用户"
    cached_hint: Optional[str] = None
    reply_chunks: List[str] = field(default_factory=list)
    reply: str = ""
    stop: bool = False


Stage = Callable[[Any], Awaitable[None]]


async def _run_pipeline(
    *,
    state: Any,
    stages: Sequence[Tuple[str, Stage]],
) -> None:
    for name, stage in stages:
        if bool(getattr(state, "stop", False)):
            log.debug(f"[flow] pipeline stopped before stage={name}")
            break
        await stage(state)


async def _private_stage_identity_and_profile(state: PrivateFlowState) -> None:
    user_id = state.ctx.user_id
    master_id = str(getattr(state.plugin_config, "mika_master_id", "") or "").strip()
    is_master = bool(master_id and str(state.ctx.user_id or "").strip() == master_id)

    master_name = getattr(state.plugin_config, "mika_master_name", "Sensei")
    if not isinstance(master_name, str) or not master_name.strip():
        master_name = "Sensei"
    state.tag = f"⭐{master_name}" if is_master else "私聊用户"

    try:
        from .utils.user_profile_extract_service import get_user_profile_extract_service

        svc = get_user_profile_extract_service()
        svc.ingest_message(
            platform_user_id=user_id,
            nickname=state.tag,
            content=state.message_text,
            message_id=str(state.ctx.message_id or ""),
            group_id=None,
        )
    except Exception as exc:
        log.warning(f"私聊档案抽取 ingest 失败: {exc}")


async def _private_stage_history_and_metrics(state: PrivateFlowState) -> None:
    user_id = state.ctx.user_id
    state.image_urls, state.cached_hint = await state.deps.apply_history_image_strategy(
        ctx=state.ctx,
        message_text=state.message_text,
        image_urls=state.image_urls,
        sender_name="Sensei",
        plugin_config=state.plugin_config,
        mika_client=state.mika_client,
    )

    log.info(f"收到私聊消息 | user={user_id} | images={len(state.image_urls)}")
    log.debug(
        f"消息内容: {state.message_text[:100]}..."
        if len(state.message_text) > 100
        else f"消息内容: {state.message_text}"
    )
    state.deps.get_metrics_timeline_store().record_message()


async def _private_stage_chat(state: PrivateFlowState) -> None:
    user_id = state.ctx.user_id
    final_message = f"[{state.tag}]: {state.message_text}"
    stream_enabled = bool(getattr(state.plugin_config, "mika_reply_stream_enabled", False))
    if stream_enabled and callable(getattr(state.mika_client, "chat_stream", None)):
        chunks: List[str] = []
        try:
            async for chunk in state.mika_client.chat_stream(
                final_message,
                user_id,
                group_id=None,
                image_urls=state.image_urls,
                enable_tools=True,
                message_id=str(state.ctx.message_id or ""),
                system_injection=state.cached_hint or None,
            ):
                text = str(chunk or "")
                if text:
                    chunks.append(text)
            merged = "".join(chunks).strip()
            if merged:
                state.reply_chunks = chunks
                state.reply = merged
            else:
                state.reply = ""
        except Exception as exc:
            log.warning(f"私聊流式回复失败，回退普通回复: {exc}")
            state.reply = ""

    if not state.reply:
        state.reply = await state.mika_client.chat(
            final_message,
            user_id,
            group_id=None,
            image_urls=state.image_urls,
            enable_tools=True,
            message_id=str(state.ctx.message_id or ""),
            system_injection=state.cached_hint or None,
        )
    log.success(f"私聊回复完成 | user={user_id} | reply_len={len(state.reply)}")


async def _private_stage_send(state: PrivateFlowState) -> None:
    await state.deps.send_reply_with_policy(
        state.envelope,
        state.reply,
        is_proactive=False,
        reply_chunks=state.reply_chunks or None,
        plugin_config=state.plugin_config,
    )


async def _group_stage_prepare(state: GroupFlowState) -> None:
    state.user_id_int = str(state.ctx.user_id)
    state.nickname = state.ctx.sender_name or "Sensei"
    state.tag = f"{state.nickname}({state.user_id_int})"

    state.image_urls, state.cached_hint = await state.deps.apply_history_image_strategy(
        ctx=state.ctx,
        message_text=state.raw_text,
        image_urls=state.image_urls,
        sender_name=state.nickname,
        plugin_config=state.plugin_config,
        mika_client=state.mika_client,
    )

    log.info(
        f"收到群聊消息 | group={state.ctx.group_id} | user={state.user_id_int} | "
        f"nickname={state.nickname} | images={len(state.image_urls)}"
    )
    log.debug(
        f"消息内容(解析后): {state.raw_text[:100]}..."
        if len(state.raw_text) > 100
        else f"消息内容: {state.raw_text}"
    )
    state.deps.get_metrics_timeline_store().record_message()


async def _group_stage_profile_update_legacy(state: GroupFlowState) -> None:
    if not callable(state.deps.get_user_profile_store):
        return
    try:
        profile_store = state.deps.get_user_profile_store()
        if hasattr(profile_store, "update_from_message"):
            await profile_store.update_from_message(
                platform_user_id=state.user_id_int,
                content=state.raw_text,
                nickname=state.nickname,
            )
    except Exception as exc:
        log.warning(f"群聊用户档案 update_from_message 失败(忽略): {exc}")


async def _group_stage_profile_ingest(state: GroupFlowState) -> None:
    try:
        from .utils.user_profile_extract_service import get_user_profile_extract_service

        svc = get_user_profile_extract_service()
        svc.ingest_message(
            platform_user_id=state.user_id_int,
            nickname=state.nickname,
            content=state.raw_text,
            message_id=str(state.ctx.message_id or ""),
            group_id=str(state.ctx.group_id),
        )
    except Exception as exc:
        log.warning(f"群聊档案抽取 ingest 失败: {exc}")


async def _group_stage_build_injection(state: GroupFlowState) -> None:
    if state.is_proactive and state.proactive_reason:
        state.injection_parts.append(state.proactive_reason)
    if state.cached_hint:
        state.injection_parts.append(state.cached_hint)

    state.system_injection_content = "\n".join([p for p in state.injection_parts if p]).strip() or None


async def _group_stage_relevance_filter(state: GroupFlowState) -> None:
    if state.is_proactive:
        return
    if not bool(getattr(state.plugin_config, "mika_relevance_filter_enabled", False)):
        return
    if not callable(state.deps.resolve_llm_cfg):
        return
    if not callable(state.deps.get_relevance_filter):
        return

    master_id = str(getattr(state.plugin_config, "mika_master_id", "") or "").strip()
    if state.user_id_int == master_id:
        return

    llm_cfg = state.deps.resolve_llm_cfg(state.plugin_config)
    filter_model = str(getattr(state.plugin_config, "mika_relevance_filter_model", "") or "").strip()
    if not filter_model:
        try:
            filter_model = str(state.plugin_config.resolve_task_model("filter", llm_cfg=llm_cfg)).strip()
        except Exception:
            filter_model = str(llm_cfg.get("fast_model") or llm_cfg.get("model") or "").strip()
    if not filter_model:
        return

    try:
        context_messages: List[Dict[str, Any]] = await state.mika_client.get_context(
            state.user_id_int, str(state.ctx.group_id)
        )
    except Exception:
        context_messages = []

    filter_result = await state.deps.get_relevance_filter().evaluate(
        message=state.raw_text,
        context_messages=context_messages,
        llm_cfg=llm_cfg,
        model=filter_model,
        temperature=float(getattr(state.plugin_config, "mika_search_classify_temperature", 0.0) or 0.0),
    )
    if not filter_result.should_reply:
        log.info(
            "[相关性过滤] 跳过回复 | "
            f"group={state.ctx.group_id} | user={state.user_id_int} | "
            f"confidence={filter_result.confidence:.2f} | reason={filter_result.reasoning}"
        )
        state.stop = True
        return

    log.debug(
        "[相关性过滤] 保留回复 | "
        f"group={state.ctx.group_id} | user={state.user_id_int} | "
        f"confidence={filter_result.confidence:.2f} | reason={filter_result.reasoning}"
    )


async def _group_stage_chat(state: GroupFlowState) -> None:
    final_message = f"[{state.tag}]: {state.raw_text}"
    stream_enabled = bool(getattr(state.plugin_config, "mika_reply_stream_enabled", False))
    if stream_enabled and callable(getattr(state.mika_client, "chat_stream", None)):
        chunks: List[str] = []
        try:
            async for chunk in state.mika_client.chat_stream(
                final_message,
                state.user_id_int,
                group_id=str(state.ctx.group_id),
                image_urls=state.image_urls,
                enable_tools=True,
                message_id=str(state.ctx.message_id or ""),
                system_injection=state.system_injection_content,
                history_override=state.history_override,
            ):
                text = str(chunk or "")
                if text:
                    chunks.append(text)
            merged = "".join(chunks).strip()
            if merged:
                state.reply_chunks = chunks
                state.reply = merged
            else:
                state.reply = ""
        except Exception as exc:
            log.warning(f"群聊流式回复失败，回退普通回复: {exc}")
            state.reply = ""

    if not state.reply:
        state.reply = await state.mika_client.chat(
            final_message,
            state.user_id_int,
            group_id=str(state.ctx.group_id),
            image_urls=state.image_urls,
            enable_tools=True,
            message_id=str(state.ctx.message_id or ""),
            system_injection=state.system_injection_content,
            history_override=state.history_override,
        )
    log.success(
        f"群聊回复完成 | group={state.ctx.group_id} | user={state.user_id_int} | reply_len={len(state.reply)}"
    )


async def _group_stage_send(state: GroupFlowState) -> None:
    await state.deps.send_reply_with_policy(
        state.envelope,
        state.reply,
        is_proactive=state.is_proactive,
        reply_chunks=state.reply_chunks or None,
        plugin_config=state.plugin_config,
    )


async def run_private_locked_flow(
    *,
    envelope: Any,
    ctx: Any,
    message_text: str,
    image_urls: List[str],
    plugin_config: Any,
    mika_client: Any,
    deps: Optional[FlowDeps] = None,
) -> None:
    """执行私聊锁内主流程（轻量管道）。"""
    if deps is None:
        raise ValueError("deps is required")

    state = PrivateFlowState(
        envelope=envelope,
        ctx=ctx,
        message_text=message_text,
        image_urls=list(image_urls or []),
        plugin_config=plugin_config,
        mika_client=mika_client,
        deps=deps,
    )
    await _run_pipeline(
        state=state,
        stages=[
            ("identity_profile", _private_stage_identity_and_profile),
            ("history_metrics", _private_stage_history_and_metrics),
            ("chat", _private_stage_chat),
            ("send", _private_stage_send),
        ],
    )


async def run_group_locked_flow(
    *,
    envelope: Any,
    ctx: Any,
    raw_text: str,
    image_urls: List[str],
    plugin_config: Any,
    mika_client: Any,
    is_proactive: bool,
    proactive_reason: Optional[str],
    deps: Optional[FlowDeps] = None,
) -> None:
    """执行群聊锁内主流程（轻量管道）。"""
    if deps is None:
        raise ValueError("deps is required")

    state = GroupFlowState(
        envelope=envelope,
        ctx=ctx,
        raw_text=raw_text,
        image_urls=list(image_urls or []),
        plugin_config=plugin_config,
        mika_client=mika_client,
        is_proactive=bool(is_proactive),
        proactive_reason=proactive_reason,
        deps=deps,
    )
    await _run_pipeline(
        state=state,
        stages=[
            ("prepare", _group_stage_prepare),
            ("profile_update_legacy", _group_stage_profile_update_legacy),
            ("profile_ingest", _group_stage_profile_ingest),
            ("build_injection", _group_stage_build_injection),
            ("relevance_filter", _group_stage_relevance_filter),
            ("chat", _group_stage_chat),
            ("send", _group_stage_send),
        ],
    )
