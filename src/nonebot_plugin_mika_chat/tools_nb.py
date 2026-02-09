"""NoneBot-specific tool handlers."""

from __future__ import annotations

from typing import Any

from nonebot import logger
from nonebot import get_bot

from mika_chat_core.config import Config
from mika_chat_core.runtime import get_config


async def handle_search_group_history(args: dict, group_id: str) -> str:
    from mika_chat_core.utils.context_store import get_context_store

    group_id_str = str(group_id or "").strip()
    if not group_id_str:
        return "该工具仅在群聊可用（需要 group_id）。"

    try:
        count = int(args.get("count", 20) if isinstance(args, dict) else 20)
        count = max(1, min(count, 50))

        store = get_context_store()
        history = await store.get_context(user_id="_tool_", group_id=group_id_str)

        if not history:
            return "没有找到历史消息。"

        def _content_to_text(content: Any) -> str:
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts: list[str] = []
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    item_type = item.get("type")
                    if item_type == "text":
                        parts.append(str(item.get("text") or ""))
                    elif item_type == "image_url":
                        parts.append("[图片]")
                return " ".join(p for p in parts if p)
            return str(content or "")

        lines: list[str] = []
        for msg in history[-count:]:
            role = str(msg.get("role") or "")
            content_text = _content_to_text(msg.get("content"))
            content_text = content_text.replace("\n", " ").strip()
            if not content_text:
                continue
            if role == "assistant" and not content_text.startswith("["):
                lines.append(f"[assistant]: {content_text}")
            else:
                lines.append(content_text)

        if not lines:
            return "没有找到可用的历史消息。"

        return "以下是查找到的历史消息：\n" + "\n".join(lines)
    except Exception as exc:
        logger.error(f"Failed to search group history: {exc}")
        return f"翻记录时出错了：{str(exc)}"


async def handle_fetch_history_images(args: dict, group_id: str = "") -> str:
    import json

    from mika_chat_core.metrics import metrics
    from mika_chat_core.utils.context_db import get_db
    from mika_chat_core.utils.context_schema import normalize_content
    from mika_chat_core.utils.recent_images import get_image_cache
    from mika_chat_core.utils.image_processor import get_image_processor

    try:
        plugin_config = get_config()
    except Exception:
        plugin_config = Config(  # type: ignore[call-arg]
            gemini_api_key="test-api-key-12345678901234567890",
            gemini_master_id=1,
        )
    max_allowed = plugin_config.gemini_history_image_two_stage_max

    try:
        group_id_str = str(group_id) if group_id else ""
        if not group_id_str:
            logger.warning("fetch_history_images: group_id 为空，拒绝")
            metrics.history_image_fetch_tool_fail_total += 1
            return json.dumps({"error": "group_id is required", "images": []})

        msg_ids = args.get("msg_ids", []) if isinstance(args, dict) else []
        max_images = (
            min(args.get("max_images", 2), max_allowed) if isinstance(args, dict) else min(2, max_allowed)
        )

        if not msg_ids:
            metrics.history_image_fetch_tool_fail_total += 1
            return json.dumps({"error": "No msg_ids provided", "images": []})

        msg_ids = msg_ids[: max_images + 1]

        image_cache = get_image_cache()
        processor = get_image_processor()
        result_images = []

        async def _append_data_url(
            *,
            msg_id: str,
            sender_name: str,
            image_url: str,
            source: str,
        ) -> None:
            if len(result_images) >= max_images:
                return
            try:
                base64_data, mime_type = await processor.download_and_encode(image_url)
                result_images.append(
                    {
                        "msg_id": msg_id,
                        "sender_name": sender_name,
                        "data_url": f"data:{mime_type};base64,{base64_data}",
                    }
                )
                if source == "cache":
                    metrics.history_image_fetch_tool_source_cache_total += 1
                elif source == "archive":
                    metrics.history_image_fetch_tool_source_archive_total += 1
                elif source == "get_msg":
                    metrics.history_image_fetch_tool_source_get_msg_total += 1
            except Exception as exc:
                logger.warning(
                    f"fetch_history_images: 下载图片失败 | msg_id={msg_id} | source={source} | error={exc}"
                )

        for msg_id in msg_ids:
            if len(result_images) >= max_images:
                break

            cached_images, found = image_cache.get_images_by_message_id(
                group_id=group_id_str,
                user_id="",
                message_id=str(msg_id),
            )

            if found and cached_images:
                for img in cached_images:
                    if len(result_images) >= max_images:
                        break
                    await _append_data_url(
                        msg_id=str(msg_id),
                        sender_name=str(img.sender_name or "某人"),
                        image_url=str(img.url),
                        source="cache",
                    )
                if len(result_images) >= max_images:
                    continue

            archive_hit = False
            try:
                db = await get_db()
                async with db.execute(
                    """
                    SELECT content
                    FROM message_archive
                    WHERE context_key = ? AND message_id = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (f"group:{group_id_str}", str(msg_id)),
                ) as cursor:
                    row = await cursor.fetchone()

                archive_urls = []
                if row and row[0]:
                    raw_content = row[0]
                    parsed_content: Any = raw_content
                    if isinstance(raw_content, str):
                        try:
                            parsed_content = json.loads(raw_content)
                        except Exception:
                            parsed_content = raw_content
                    normalized = normalize_content(parsed_content)
                    if isinstance(normalized, list):
                        for part in normalized:
                            if not isinstance(part, dict):
                                continue
                            if str(part.get("type") or "").lower() != "image_url":
                                continue
                            image_url = part.get("image_url")
                            if isinstance(image_url, dict):
                                url = str(image_url.get("url") or "").strip()
                            else:
                                url = str(image_url or "").strip()
                            if url:
                                archive_urls.append(url)

                if archive_urls:
                    archive_hit = True
                    for img_url in archive_urls:
                        if len(result_images) >= max_images:
                            break
                        await _append_data_url(
                            msg_id=str(msg_id),
                            sender_name="某人",
                            image_url=img_url,
                            source="archive",
                        )
            except Exception as exc:
                logger.warning(f"fetch_history_images: archive 回查失败 | msg_id={msg_id} | error={exc}")

            if archive_hit and len(result_images) >= max_images:
                continue

            try:
                bot = get_bot()
                msg_data = await bot.get_msg(message_id=int(msg_id))

                if not isinstance(msg_data, dict) or not msg_data:
                    logger.warning(f"fetch_history_images: get_msg 返回非 dict 或空 | msg_id={msg_id}")
                    continue

                msg_type = str(msg_data.get("message_type") or "")
                msg_gid = msg_data.get("group_id")
                if msg_gid is None:
                    msg_gid = (
                        (msg_data.get("group") or {}).get("group_id")
                        if isinstance(msg_data.get("group"), dict)
                        else None
                    )

                if msg_gid is None:
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
                        seg_data = (
                            seg.get("data", {}) if isinstance(seg, dict) else getattr(seg, "data", {})
                        )
                        if seg_type == "image":
                            img_url = seg_data.get("url") or seg_data.get("file")
                            if img_url:
                                await _append_data_url(
                                    msg_id=str(msg_id),
                                    sender_name=str(sender_name),
                                    image_url=str(img_url),
                                    source="get_msg",
                                )
            except Exception as exc:
                logger.warning(f"fetch_history_images: 获取消息失败 | msg_id={msg_id} | error={exc}")

        if not result_images:
            metrics.history_image_fetch_tool_fail_total += 1
            return json.dumps(
                {
                    "error": "No images found for the requested msg_ids",
                    "images": [],
                    "hint": "The images may have expired or the msg_ids are invalid.",
                }
            )

        mapping_parts = [
            f"Image {i+1} from <msg_id:{img['msg_id']}> (sent by {img['sender_name']})"
            for i, img in enumerate(result_images)
        ]

        metrics.history_image_fetch_tool_success_total += 1
        return json.dumps(
            {
                "success": True,
                "count": len(result_images),
                "mapping": mapping_parts,
                "images": [img["data_url"] for img in result_images],
            }
        )
    except Exception as exc:
        logger.error(f"fetch_history_images: 工具执行失败 | error={exc}", exc_info=True)
        from mika_chat_core.metrics import metrics

        metrics.history_image_fetch_tool_fail_total += 1
        return json.dumps({"error": str(exc), "images": []})

