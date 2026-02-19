"""Mika API - Tool schema 模式与压缩逻辑。"""

from __future__ import annotations

import time
from typing import Any, Dict, List, MutableMapping, Optional, Set


TOOL_SCHEMA_ALLOWED_KEYS: Set[str] = {
    "type",
    "properties",
    "required",
    "items",
    "enum",
    "const",
    "format",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "additionalProperties",
    "oneOf",
    "anyOf",
    "allOf",
    "nullable",
}


def compact_json_schema_node(
    node: Any,
    *,
    keep_param_description: bool,
    allowed_keys: Optional[Set[str]] = None,
) -> Any:
    active_allowed_keys = allowed_keys or TOOL_SCHEMA_ALLOWED_KEYS

    if isinstance(node, list):
        return [
            compact_json_schema_node(
                item,
                keep_param_description=keep_param_description,
                allowed_keys=active_allowed_keys,
            )
            for item in node
        ]

    if not isinstance(node, dict):
        return node

    compact: Dict[str, Any] = {}
    for key, value in node.items():
        if key == "description":
            if keep_param_description:
                compact[key] = value
            continue
        if key not in active_allowed_keys:
            continue

        if key == "properties" and isinstance(value, dict):
            compact[key] = {
                str(prop_name): compact_json_schema_node(
                    prop_schema,
                    keep_param_description=keep_param_description,
                    allowed_keys=active_allowed_keys,
                )
                for prop_name, prop_schema in value.items()
                if str(prop_name).strip()
            }
            continue

        if key in {"items", "additionalProperties"} and isinstance(value, dict):
            compact[key] = compact_json_schema_node(
                value,
                keep_param_description=keep_param_description,
                allowed_keys=active_allowed_keys,
            )
            continue

        if key in {"oneOf", "anyOf", "allOf"} and isinstance(value, list):
            compact[key] = [
                compact_json_schema_node(
                    item,
                    keep_param_description=keep_param_description,
                    allowed_keys=active_allowed_keys,
                )
                for item in value
                if isinstance(item, dict)
            ]
            continue

        compact[key] = value

    if compact.get("type") == "object" and "properties" not in compact:
        compact["properties"] = {}
    return compact


def build_lightweight_tool_schemas(
    tools: List[Dict[str, Any]],
    *,
    keep_param_description: bool,
    allowed_keys: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    compact_tools: List[Dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        if tool.get("type") != "function":
            compact_tools.append(dict(tool))
            continue

        function_payload = tool.get("function") if isinstance(tool.get("function"), dict) else {}
        name = str(function_payload.get("name") or "").strip()
        description = str(function_payload.get("description") or "").strip()
        parameters = function_payload.get("parameters")

        compact_tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": compact_json_schema_node(
                        parameters if isinstance(parameters, dict) else {"type": "object", "properties": {}},
                        keep_param_description=keep_param_description,
                        allowed_keys=allowed_keys,
                    ),
                },
            }
        )

    return compact_tools


def activate_tool_schema_full_fallback(
    *,
    session_key: str,
    request_id: str,
    reason: str,
    plugin_cfg: Any,
    fallback_until: MutableMapping[str, float],
    log_obj: Any,
    fallback_ttl_default: int,
) -> None:
    if not bool(getattr(plugin_cfg, "mika_tool_schema_auto_fallback_full", True)):
        return

    ttl_seconds = max(
        1,
        int(
            getattr(
                plugin_cfg,
                "mika_tool_schema_fallback_ttl_seconds",
                fallback_ttl_default,
            )
            or fallback_ttl_default
        ),
    )
    expires_at = time.monotonic() + float(ttl_seconds)
    fallback_until[str(session_key)] = expires_at
    log_obj.info(
        f"[req:{request_id}] tool schema 回退已激活 | session={session_key} | "
        f"ttl={ttl_seconds}s | reason={reason}"
    )


def resolve_tool_schema_mode(
    *,
    tool_count: int,
    session_key: Optional[str],
    plugin_cfg: Any,
    fallback_until: MutableMapping[str, float],
    auto_threshold_default: int,
) -> str:
    now = time.monotonic()
    expired_keys = [key for key, value in fallback_until.items() if float(value or 0.0) <= now]
    for key in expired_keys:
        fallback_until.pop(key, None)

    if (
        bool(getattr(plugin_cfg, "mika_tool_schema_auto_fallback_full", True))
        and session_key
        and float(fallback_until.get(str(session_key), 0.0) or 0.0) > now
    ):
        return "full"

    mode = str(getattr(plugin_cfg, "mika_tool_schema_mode", "full") or "full").strip().lower()
    if mode not in {"full", "light", "auto"}:
        mode = "full"

    threshold = max(
        1,
        int(
            getattr(
                plugin_cfg,
                "mika_tool_schema_auto_threshold",
                auto_threshold_default,
            )
            or auto_threshold_default
        ),
    )
    if mode == "light":
        return "light"
    if mode == "auto" and int(tool_count or 0) >= threshold:
        return "light"
    return "full"
