"""WebUI config schema (single source of truth).

This module defines the UI schema and derived views used by:
- WebUI config editor API (`GET /config`)
- Config docs generator (`scripts/gen_config_docs.py`)

It is intentionally free of FastAPI and env IO details.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .config_schema_meta_part1 import CONFIG_FIELD_META_PART1
from .config_schema_meta_part2 import CONFIG_FIELD_META_PART2
from .config_schema_sections import CONFIG_SECTIONS_RAW


SECRET_PLACEHOLDER = "••••••••"


def env_key_for_field(field_name: str) -> str:
    field = str(field_name or "").strip()
    if field.startswith("mika_"):
        return f"MIKA_{field[len('mika_'):].upper()}"
    return field.upper()


_CONFIG_FIELD_META_RAW: Dict[str, Dict[str, Any]] = {
    **CONFIG_FIELD_META_PART1,
    **CONFIG_FIELD_META_PART2,
}


def _build_config_ui_schema() -> List[Dict[str, Any]]:
    """Build single-source UI schema and derive section/meta views from it."""
    schema: List[Dict[str, Any]] = []
    covered: set[str] = set()

    for section in CONFIG_SECTIONS_RAW:
        section_fields: List[Dict[str, Any]] = []
        for key in section["keys"]:
            meta = dict(_CONFIG_FIELD_META_RAW.get(key, {}))
            section_fields.append({"key": key, **meta})
            covered.add(key)
        schema.append({"name": section["name"], "fields": section_fields})

    extras = [key for key in _CONFIG_FIELD_META_RAW.keys() if key not in covered]
    if extras:
        schema.append(
            {"name": "其他", "fields": [{"key": key, **dict(_CONFIG_FIELD_META_RAW.get(key, {}))} for key in extras]}
        )
    return schema


CONFIG_UI_SCHEMA: List[Dict[str, Any]] = _build_config_ui_schema()

CONFIG_FIELD_META: Dict[str, Dict[str, Any]] = {
    field["key"]: {meta_key: meta_val for meta_key, meta_val in field.items() if meta_key != "key"}
    for section in CONFIG_UI_SCHEMA
    for field in section.get("fields", [])
}

CONFIG_SECTIONS: List[Dict[str, Any]] = [
    {"name": section["name"], "keys": [field["key"] for field in section.get("fields", [])]}
    for section in CONFIG_UI_SCHEMA
]

SECRET_KEYS: frozenset[str] = frozenset(k for k, v in CONFIG_FIELD_META.items() if v.get("secret"))


__all__ = [
    "CONFIG_FIELD_META",
    "CONFIG_SECTIONS",
    "CONFIG_UI_SCHEMA",
    "SECRET_KEYS",
    "SECRET_PLACEHOLDER",
    "env_key_for_field",
]

