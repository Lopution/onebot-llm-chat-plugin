"""WebUI config env IO and value coercion.

This module contains:
- `.env` path resolution
- env file read/write
- json-friendly coercion based on `Config` type hints

It must not depend on FastAPI.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Union, get_args, get_origin

from ..config import Config
from .config_schema import SECRET_KEYS, SECRET_PLACEHOLDER, env_key_for_field


_ENV_LINE_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def resolve_env_path() -> Path:
    dotenv_path = str(os.getenv("DOTENV_PATH") or "").strip()
    if dotenv_path:
        path = Path(dotenv_path).expanduser()
        if not path.is_absolute():
            path = _project_root() / path
        return path
    return _project_root() / ".env"


def _unwrap_optional(annotation: Any) -> Any:
    origin = get_origin(annotation)
    if origin is Union:
        args = [arg for arg in get_args(annotation) if arg is not type(None)]
        if len(args) == 1:
            return args[0]
    return annotation


def field_kind(field_name: str) -> str:
    annotation = _unwrap_optional(Config.__annotations__.get(field_name))
    origin = get_origin(annotation)
    if annotation is bool:
        return "boolean"
    if annotation is int:
        return "integer"
    if annotation is float:
        return "number"
    if origin in {list, List}:
        return "array"
    if origin in {dict, Dict}:
        return "object"
    return "string"


def field_default(field_name: str) -> Any:
    model_fields = getattr(Config, "model_fields", None)
    if isinstance(model_fields, dict) and field_name in model_fields:
        default = getattr(model_fields[field_name], "default", None)
        if default is not None:
            type_name = str(getattr(default, "__class__", type(default)).__name__ or "")
            if type_name not in {"PydanticUndefinedType", "PydanticUndefined"}:
                return default
    if hasattr(Config, field_name):
        return getattr(Config, field_name)
    return None


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value}")


def coerce_value(field_name: str, raw_value: Any) -> Any:
    annotation = _unwrap_optional(Config.__annotations__.get(field_name))
    origin = get_origin(annotation)
    if annotation is bool:
        return _coerce_bool(raw_value)
    if annotation is int:
        return int(raw_value)
    if annotation is float:
        return float(raw_value)
    if origin in {list, List}:
        if isinstance(raw_value, list):
            return raw_value
        text = str(raw_value or "").strip()
        if not text:
            return []
        if text.startswith("["):
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return parsed
            raise ValueError(f"invalid list value for {field_name}")
        return [item.strip() for item in text.split(",") if item.strip()]
    if origin in {dict, Dict}:
        if isinstance(raw_value, dict):
            return raw_value
        text = str(raw_value or "").strip()
        if not text:
            return {}
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
        raise ValueError(f"invalid object value for {field_name}")
    if raw_value is None:
        return ""
    return str(raw_value)


def _encode_env_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return json.dumps(str(value), ensure_ascii=False)


def write_env_updates(env_path: Path, updates: Dict[str, Any]) -> None:
    env_path.parent.mkdir(parents=True, exist_ok=True)
    lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True) if env_path.exists() else []

    env_updates: Dict[str, str] = {env_key_for_field(k): _encode_env_value(v) for k, v in updates.items()}
    seen: set[str] = set()
    updated_lines: list[str] = []

    for line in lines:
        matched = _ENV_LINE_RE.match(line)
        if not matched:
            updated_lines.append(line)
            continue
        env_key = matched.group(1)
        if env_key not in env_updates:
            updated_lines.append(line)
            continue
        updated_lines.append(f"{env_key}={env_updates[env_key]}\n")
        seen.add(env_key)

    for env_key, encoded in env_updates.items():
        if env_key in seen:
            continue
        updated_lines.append(f"{env_key}={encoded}\n")

    env_path.write_text("".join(updated_lines), encoding="utf-8")


def collect_updates(
    payload: Dict[str, Any],
    *,
    current_config: Config | None = None,
) -> tuple[Dict[str, Any], str | None]:
    updates: Dict[str, Any] = {}
    for key, value in payload.items():
        if key not in Config.__annotations__:
            return {}, f"unsupported config key: {key}"
        if key in SECRET_KEYS:
            str_val = str(value or "").strip()
            if str_val == SECRET_PLACEHOLDER:
                continue
            if str_val == "":
                existing = getattr(current_config, key, None) if current_config is not None else None
                # Empty means "clear" only when it was previously set; otherwise keep unchanged.
                if isinstance(existing, (list, tuple, set)):
                    if not existing:
                        continue
                else:
                    if not str(existing or "").strip():
                        continue
        try:
            updates[key] = coerce_value(key, value)
        except Exception as exc:
            return {}, f"invalid value for {key}: {exc}"
    return updates, None


def parse_env_file(env_path: Path) -> Dict[str, str]:
    if not env_path.exists():
        return {}
    values: Dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        matched = _ENV_LINE_RE.match(line)
        if not matched:
            continue
        env_key = matched.group(1)
        _, _, rhs = line.partition("=")
        values[env_key] = rhs.strip()
    return values


def _decode_env_raw_value(raw_value: str) -> Any:
    text = str(raw_value or "").strip()
    if not text:
        return ""
    if text.startswith('"') and text.endswith('"'):
        try:
            return json.loads(text)
        except Exception:
            return text[1:-1]
    if text.startswith("'") and text.endswith("'"):
        return text[1:-1]
    if text.startswith("[") or text.startswith("{"):
        try:
            return json.loads(text)
        except Exception:
            return text
    return text


def build_config_from_env_file(env_path: Path, current_config: Config) -> Config:
    payload = dict(current_config.model_dump())
    env_values = parse_env_file(env_path)
    for field_name in Config.__annotations__.keys():
        env_key = env_key_for_field(field_name)
        if env_key not in env_values:
            continue
        try:
            payload[field_name] = coerce_value(field_name, _decode_env_raw_value(env_values[env_key]))
        except Exception:
            continue
    return Config(**payload)


def sync_config_instance(target: Config, source: Config) -> None:
    """Copy validated values from source config into target config object."""
    for field_name in Config.__annotations__.keys():
        value = getattr(source, field_name, None)
        try:
            setattr(target, field_name, value)
        except Exception:
            object.__setattr__(target, field_name, value)


def export_config_values(config: Config, *, include_secrets: bool) -> Dict[str, Any]:
    exported: Dict[str, Any] = {}
    for key in Config.__annotations__.keys():
        value = getattr(config, key, None)
        if key in SECRET_KEYS and not include_secrets:
            exported[key] = SECRET_PLACEHOLDER if str(value or "").strip() else ""
        else:
            exported[key] = value
    return exported


__all__ = [
    "build_config_from_env_file",
    "collect_updates",
    "export_config_values",
    "field_default",
    "field_kind",
    "parse_env_file",
    "resolve_env_path",
    "sync_config_instance",
    "write_env_updates",
]
