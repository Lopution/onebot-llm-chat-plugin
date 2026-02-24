from __future__ import annotations

import pytest

from mika_chat_core.contracts import ContentPart, SendMessageAction


def test_load_cli_config_from_env(monkeypatch):
    from mika_chat_cli.cli_config import load_cli_config

    monkeypatch.setenv("LLM_API_KEY", "A" * 32)
    monkeypatch.setenv("LLM_MODEL", "gemini-3-flash")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("MIKA_MASTER_ID", "cli_master")
    monkeypatch.setenv("MIKA_MASTER_NAME", "Sensei")

    cfg = load_cli_config()
    assert cfg.llm_api_key == "A" * 32
    assert cfg.llm_model == "gemini-3-flash"
    assert cfg.mika_master_id == "cli_master"


def test_load_cli_config_rejects_removed_env_keys(monkeypatch):
    from mika_chat_cli.cli_config import load_cli_config

    monkeypatch.setenv("LLM_API_KEY", "A" * 32)
    monkeypatch.setenv("MIKA_API_KEY", "A" * 32)
    monkeypatch.setenv("MIKA_MASTER_ID", "cli_master")

    with pytest.raises(RuntimeError, match="MIKA_API_KEY"):
        load_cli_config()


@pytest.mark.asyncio
async def test_cli_runtime_ports_send_message_collects_output():
    from mika_chat_cli.cli_ports import CliRuntimePorts

    outputs: list[str] = []
    ports = CliRuntimePorts(output=outputs.append)
    action = SendMessageAction(
        type="send_message",
        session_id="private:cli_user",
        parts=[
            ContentPart(kind="text", text="hello"),
            ContentPart(kind="image", asset_ref="https://example.com/a.png"),
        ],
    )
    result = await ports.send_message(action)
    assert result["ok"] is True
    assert outputs
    assert "[Mika]:" in outputs[0]
    assert "hello" in outputs[0]


def test_cli_private_envelope_builder():
    from mika_chat_cli import _build_private_envelope

    envelope = _build_private_envelope(
        session_id="private:cli_user",
        platform="cli",
        user_id="cli_user",
        user_name="User",
        text="你好",
    )
    assert envelope.protocol == "cli"
    assert envelope.author.id == "cli_user"
    assert envelope.content_parts and envelope.content_parts[0].text == "你好"
