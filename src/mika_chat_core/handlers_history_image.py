"""Handlers - 历史图片策略与图片 URL 解析流程。"""

from __future__ import annotations

from typing import Any, Optional

from .contracts import ContentPart


def cfg(plugin_config: Any, key: str, default: Any) -> Any:
    """读取配置项并提供稳定默认值（不修改配置对象本身）。"""
    value = getattr(plugin_config, key, default)
    return default if value is None else value


def history_collage_enabled(plugin_config: Any) -> bool:
    """历史拼图开关（新配置优先，旧配置兼容）。"""
    if hasattr(plugin_config, "mika_history_collage_enabled"):
        return bool(cfg(plugin_config, "mika_history_collage_enabled", False))
    return bool(cfg(plugin_config, "mika_history_collage_enabled", True))


def dedupe_image_urls(urls: list[str], max_images: int) -> list[str]:
    merged: list[str] = []
    if max_images <= 0:
        return merged
    for url in urls:
        item = str(url or "").strip()
        if not item:
            continue
        if item in merged:
            continue
        merged.append(item)
        if len(merged) >= max_images:
            break
    return merged


async def apply_history_image_strategy_flow(
    *,
    ctx: Any,
    message_text: str,
    image_urls: list[str],
    sender_name: str,
    plugin_config: Any,
    mika_client: Any,
    log_obj: Any,
    metrics_obj: Any,
    get_image_cache_fn,
    determine_history_image_action_fn,
    build_image_mapping_hint_fn,
    build_candidate_hint_fn,
    history_image_action_cls,
    create_collage_from_urls_fn,
    is_collage_available_fn,
) -> tuple[list[str], Optional[str]]:
    """统一处理历史图片策略，返回(最终图片列表, system 注入提示)。"""
    image_cache = get_image_cache_fn()
    cached_hint: Optional[str] = None
    final_image_urls = list(image_urls or [])

    group_id = str(ctx.group_id) if getattr(ctx, "is_group", False) and ctx.group_id else None
    user_id = str(ctx.user_id)
    message_id = str(ctx.message_id or "")
    scope_info = (
        f"group={group_id} | user={user_id}" if group_id else f"user={user_id}"
    )

    if final_image_urls:
        image_cache.cache_images(
            group_id=group_id,
            user_id=user_id,
            image_urls=final_image_urls,
            sender_name=sender_name,
            message_id=message_id,
        )
        return final_image_urls, cached_hint

    candidate_images = image_cache.peek_recent_images(
        group_id=group_id,
        user_id=user_id,
        limit=int(cfg(plugin_config, "mika_history_image_collage_max", 4)),
    )

    context_messages = None
    try:
        context_messages = await mika_client.get_context(user_id, group_id)
    except Exception as exc:
        # 上下文获取失败不应阻断历史图片策略判定（仅影响隐式指代等增强能力）。
        log_obj.debug(f"[历史图片] 获取上下文失败，继续策略判定: {exc}")

    # If request-time history already includes multimodal parts, avoid duplicating the same
    # image again via "history image injection" (saves cost and reduces noise).
    #
    # Note: `mika_history_store_multimodal` controls storage format in context backend;
    # it does NOT necessarily mean we send those images to the provider. The actual
    # request-time behavior is controlled by `mika_history_send_multimodal`.
    try:
        if bool(cfg(plugin_config, "mika_history_send_multimodal", False)) and context_messages:
            present_msg_ids: set[str] = set()
            for msg in (context_messages or [])[-20:]:
                mid = str(msg.get("message_id") or "").strip()
                if not mid:
                    continue
                content = msg.get("content")
                if not isinstance(content, list):
                    continue
                if any(
                    isinstance(part, dict) and str(part.get("type") or "").lower() == "image_url"
                    for part in content
                ):
                    present_msg_ids.add(mid)

            if present_msg_ids and candidate_images:
                candidate_images = [
                    img
                    for img in candidate_images
                    if str(getattr(img, "message_id", "") or "").strip() not in present_msg_ids
                ]
    except Exception:
        pass

    decision = determine_history_image_action_fn(
        message_text=message_text,
        candidate_images=candidate_images,
        context_messages=context_messages,
        mode=str(cfg(plugin_config, "mika_history_image_mode", "hybrid")),
        inline_max=int(cfg(plugin_config, "mika_history_image_inline_max", 1)),
        two_stage_max=int(cfg(plugin_config, "mika_history_image_two_stage_max", 2)),
        collage_max=int(cfg(plugin_config, "mika_history_image_collage_max", 4)),
        enable_collage=history_collage_enabled(plugin_config),
        inline_threshold=float(cfg(plugin_config, "mika_history_inline_threshold", 0.85)),
        two_stage_threshold=float(cfg(plugin_config, "mika_history_two_stage_threshold", 0.5)),
        custom_keywords=cfg(plugin_config, "mika_history_image_trigger_keywords", []) or None,
    )

    if decision.action == history_image_action_cls.INLINE:
        final_image_urls = [img.url for img in decision.images_to_inject]
        cached_hint = build_image_mapping_hint_fn(decision.images_to_inject)
        metrics_obj.history_image_inline_used_total += 1
        metrics_obj.history_image_images_injected_total += len(final_image_urls)
        log_obj.info(
            f"[历史图片] INLINE | {scope_info} | images={len(final_image_urls)} | reason={decision.reason}"
        )
        return final_image_urls, cached_hint

    if decision.action == history_image_action_cls.COLLAGE and is_collage_available_fn():
        collage_urls = [img.url for img in decision.images_to_inject]
        collage_result = await create_collage_from_urls_fn(
            collage_urls,
            target_max_px=int(cfg(plugin_config, "mika_history_image_collage_target_px", 768)),
        )
        if collage_result:
            base64_data, mime_type = collage_result
            final_image_urls = [f"data:{mime_type};base64,{base64_data}"]
            cached_hint = build_image_mapping_hint_fn(decision.images_to_inject)
            metrics_obj.history_image_collage_used_total += 1
            metrics_obj.history_image_images_injected_total += len(decision.images_to_inject)
            log_obj.info(
                f"[历史图片] COLLAGE | {scope_info} | images={len(collage_urls)} | reason={decision.reason}"
            )
            return final_image_urls, cached_hint

        inline_max = int(cfg(plugin_config, "mika_history_image_inline_max", 1))
        fallback_images = decision.images_to_inject[:inline_max]
        final_image_urls = [img.url for img in fallback_images]
        cached_hint = build_image_mapping_hint_fn(fallback_images)
        metrics_obj.history_image_inline_used_total += 1
        metrics_obj.history_image_images_injected_total += len(final_image_urls)
        log_obj.warning(
            f"[历史图片] COLLAGE失败回退INLINE | {scope_info} | images={len(final_image_urls)}"
        )
        return final_image_urls, cached_hint

    if decision.action == history_image_action_cls.TWO_STAGE:
        metrics_obj.history_image_two_stage_triggered_total += 1
        hint_parts: list[str] = []
        if group_id:
            candidate_hint = build_candidate_hint_fn(decision.candidate_msg_ids)
            if candidate_hint:
                hint_parts.append(candidate_hint)
        else:
            hint_parts.append("[System Note: 私聊历史图片不支持自动回取；如需识别图片，请重新发送图片。]")

        # Caption-first: avoid attaching `data:base64` to the main request (too large / proxy-unfriendly).
        media_policy = str(cfg(plugin_config, "mika_media_policy_default", "caption") or "caption").strip().lower()
        caption_enabled = bool(cfg(plugin_config, "mika_media_caption_enabled", False))
        if caption_enabled and media_policy == "caption" and decision.candidate_msg_ids:
            max_images = int(cfg(plugin_config, "mika_history_image_two_stage_max", 2) or 2)
            # Best-effort: use cached URLs; no base64 in storage/request.
            msg_id_to_url: dict[str, str] = {}
            for img in candidate_images:
                mid = str(getattr(img, "message_id", "") or "").strip()
                url = str(getattr(img, "url", "") or "").strip()
                if mid and url and mid not in msg_id_to_url:
                    msg_id_to_url[mid] = url

            image_parts: list[dict[str, Any]] = []
            for mid in list(decision.candidate_msg_ids or [])[: max(1, max_images)]:
                url = msg_id_to_url.get(str(mid))
                if not url:
                    continue
                image_parts.append({"type": "image_url", "image_url": {"url": url}})

            if image_parts:
                try:
                    from .utils.media_captioner import caption_images

                    captions = await caption_images(
                        image_parts,
                        request_id=str(message_id or "history_image"),
                        cfg=plugin_config,
                    )
                except Exception as exc:
                    log_obj.warning(f"[历史图片] TWO_STAGE caption 生成失败: {exc}")
                    captions = []

                if captions:
                    lines = ["[Context Media Captions | Untrusted]"]
                    for i, caption in enumerate(captions):
                        text = str(caption or "").strip()
                        if text:
                            lines.append(f"- Image {i+1}: {text}")
                    hint_parts.append("\n".join(lines).strip())

        cached_hint = "\n\n".join([p for p in hint_parts if str(p or "").strip()]).strip() or None
        log_obj.info(
            f"[历史图片] TWO_STAGE(caption-first) | {scope_info} | candidates={len(decision.candidate_msg_ids)} | reason={decision.reason}"
        )

    return final_image_urls, cached_hint


async def resolve_image_urls_via_port_flow(
    content_parts: list[ContentPart],
    *,
    platform_api: Optional[Any] = None,
    max_images: int = 10,
) -> list[str]:
    """从标准化 content parts 解析可用图片 URL。"""
    if max_images <= 0:
        return []

    urls: list[str] = []
    unresolved_refs: list[str] = []
    for part in content_parts:
        if part.kind != "image":
            continue
        ref = str(part.asset_ref or "").strip()
        if not ref:
            continue
        if ref.startswith(("http://", "https://", "data:")):
            urls.append(ref)
        else:
            unresolved_refs.append(ref)

    if unresolved_refs and platform_api is not None:
        for asset_ref in unresolved_refs:
            try:
                resolved = await platform_api.resolve_file_url(asset_ref)
            except Exception:
                resolved = None
            resolved_url = str(resolved or "").strip()
            if resolved_url.startswith(("http://", "https://", "data:")):
                urls.append(resolved_url)
            else:
                urls.append(asset_ref)

    return dedupe_image_urls(urls, max_images=max_images)
