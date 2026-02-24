"""CLI configuration loader."""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - fallback for minimal test env
    def load_dotenv(*_args, **_kwargs):  # type: ignore[override]
        return False

from mika_chat_core.config import Config


def _parse_csv_list(raw: str) -> List[str]:
    return [item.strip() for item in str(raw or "").split(",") if item.strip()]


def _env(name: str, default: str = "") -> str:
    return str(os.getenv(name, default) or "").strip()


_REMOVED_ENV_KEYS: dict[str, str] = {
    "MIKA_API_KEY": "LLM_API_KEY",
    "MIKA_API_KEY_LIST": "LLM_API_KEY_LIST",
    "MIKA_BASE_URL": "LLM_BASE_URL",
    "MIKA_MODEL": "LLM_MODEL",
    "MIKA_FAST_MODEL": "LLM_FAST_MODEL",
    "SERPER_API_KEY": "SEARCH_API_KEY",
}


def _ensure_no_removed_env_keys() -> None:
    for old_key, new_key in _REMOVED_ENV_KEYS.items():
        value = _env(old_key)
        if not value:
            continue
        raise RuntimeError(
            f"检测到已移除环境变量 {old_key}，请改用 {new_key}。"
        )


def load_cli_config(env_file: Optional[str] = None) -> Config:
    """Load minimal runtime config for CLI adapter."""
    if env_file:
        load_dotenv(Path(env_file), override=False)
    else:
        load_dotenv(override=False)

    _ensure_no_removed_env_keys()

    api_key = _env("LLM_API_KEY")
    api_key_list = _parse_csv_list(_env("LLM_API_KEY_LIST"))
    if not api_key and api_key_list:
        api_key = api_key_list[0]
        api_key_list = api_key_list[1:]

    if not api_key:
        raise RuntimeError("CLI 模式需要配置 LLM_API_KEY（或 LLM_API_KEY_LIST）。")

    model = _env("LLM_MODEL", "gemini-3-flash")
    fast_model = _env("LLM_FAST_MODEL", "gemini-2.5-flash-lite")
    base_url = _env("LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
    prompt_file = _env("MIKA_PROMPT_FILE", "system.yaml")
    master_id = _env("MIKA_MASTER_ID", "cli_master")
    master_name = _env("MIKA_MASTER_NAME", "Sensei")
    search_api_key = _env("SEARCH_API_KEY")

    config = Config(
        llm_api_key=api_key,
        llm_api_key_list=api_key_list,
        llm_base_url=base_url,
        llm_model=model,
        llm_fast_model=fast_model,
        mika_master_id=master_id,
        mika_master_name=master_name,
        mika_prompt_file=prompt_file,
        mika_validate_on_startup=False,
        mika_reply_private=True,
        mika_reply_at=False,
        mika_offline_sync_enabled=False,
        mika_group_whitelist=[],
        search_api_key=search_api_key,
    )
    return config
