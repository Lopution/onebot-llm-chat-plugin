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
    from mika_chat_core.utils.history_image_fetcher import fetch_history_images_data_urls

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
        max_images = int(args.get("max_images", 2) if isinstance(args, dict) else 2)
        max_images = max(1, min(max_images, max_allowed))

        if not msg_ids:
            metrics.history_image_fetch_tool_fail_total += 1
            return json.dumps({"error": "No msg_ids provided", "images": []})

        result_images = await fetch_history_images_data_urls(
            context_key=f"group:{group_id_str}",
            msg_ids=[str(x) for x in (msg_ids or [])],
            max_images=max_images,
            plugin_config=plugin_config,
            metrics_obj=metrics,
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
