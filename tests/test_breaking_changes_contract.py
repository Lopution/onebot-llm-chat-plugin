from __future__ import annotations

import importlib

import pytest
from pydantic import ValidationError


def test_removed_mika_api_compat_import_fails():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("mika_chat_core.mika_api_messages")


def test_removed_legacy_env_key_fails_fast(monkeypatch):
    from mika_chat_core.config import Config

    monkeypatch.setenv("MIKA_API_KEY", "A" * 32)
    with pytest.raises(ValidationError, match="MIKA_API_KEY"):
        Config(llm_api_key="B" * 32, mika_master_id=123456789)


def test_removed_legacy_payload_key_fails_fast():
    from mika_chat_core.config import Config

    legacy_key = "".join(["mika_", "api_key"])
    payload = {
        "llm_api_key": "A" * 32,
        "mika_master_id": 123456789,
        legacy_key: "B" * 32,
    }
    with pytest.raises(ValidationError):
        Config(**payload)
