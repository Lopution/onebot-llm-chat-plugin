from __future__ import annotations

from pathlib import Path


def _parse_env_keys_from_env_file(content: str) -> set[str]:
    keys: set[str] = set()
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        if key:
            keys.add(key)
    return keys


def test_env_example_does_not_define_removed_legacy_env_keys():
    from mika_chat_core.config import _REMOVED_LEGACY_ENV_KEYS

    env_example_path = Path(__file__).resolve().parent.parent / ".env.example"
    content = env_example_path.read_text(encoding="utf-8")
    defined_keys = _parse_env_keys_from_env_file(content)

    removed_keys = set(_REMOVED_LEGACY_ENV_KEYS.keys())
    assert not (defined_keys & removed_keys)

