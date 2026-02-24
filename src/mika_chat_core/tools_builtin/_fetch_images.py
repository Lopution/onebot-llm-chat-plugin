"""历史图片回取工具。"""

from __future__ import annotations

import json
from typing import Any

from ..infra.logging import logger
from ..runtime import get_config as get_runtime_config
from ..tools import tool, _resolve_tool_override


@tool(
    "fetch_history_images",
    description="按消息ID回取历史图片，支持图片二阶段分析。",
    parameters={
        "type": "object",
        "properties": {
            "msg_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "需要回取图片的消息ID列表",
            },
            "max_images": {"type": "integer", "description": "最多回取图片数量"},
        },
        "required": ["msg_ids"],
    },
)
async def handle_fetch_history_images(args: dict, group_id: str = "") -> str:
    """历史图片回取工具（支持宿主覆盖）。"""
    override = _resolve_tool_override("fetch_history_images")
    if override is not None:
        return await override(args, group_id)

    from mika_chat_core.config import Config
    from mika_chat_core.metrics import metrics
    from mika_chat_core.utils.context_db import get_db
    from mika_chat_core.utils.context_schema import normalize_content
    from mika_chat_core.utils.image_processor import get_image_processor
    from mika_chat_core.utils.recent_images import get_image_cache

    try:
        try:
            plugin_config = get_runtime_config()
        except Exception:
            plugin_config = Config(  # type: ignore[call-arg]
                llm_api_key="test-api-key-12345678901234567890",
                mika_master_id="1",
            )

        max_allowed = int(getattr(plugin_config, "mika_history_image_two_stage_max", 2) or 2)

        group_id_str = str(group_id or "").strip()
        if not group_id_str:
            metrics.history_image_fetch_tool_fail_total += 1
            return json.dumps({"error": "group_id is required", "images": []})

        msg_ids = args.get("msg_ids", []) if isinstance(args, dict) else []
        max_images = min(
            int(args.get("max_images", 2) if isinstance(args, dict) else 2),
            max_allowed,
        )

        if not msg_ids:
            metrics.history_image_fetch_tool_fail_total += 1
            return json.dumps({"error": "No msg_ids provided", "images": []})

        msg_ids = msg_ids[:max_images]

        image_cache = get_image_cache()
        processor = get_image_processor()
        result_images: list[dict[str, str]] = []

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
            except Exception as exc:
                logger.warning(f"fetch_history_images: archive 回查失败 | msg_id={msg_id} | error={exc}")
                row = None

            archive_urls: list[str] = []
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

            for img_url in archive_urls:
                if len(result_images) >= max_images:
                    break
                await _append_data_url(
                    msg_id=str(msg_id),
                    sender_name="某人",
                    image_url=img_url,
                    source="archive",
                )

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
        from mika_chat_core.metrics import metrics

        logger.error(f"fetch_history_images: 工具执行失败 | error={exc}", exc_info=True)
        metrics.history_image_fetch_tool_fail_total += 1
        return json.dumps({"error": str(exc), "images": []})
