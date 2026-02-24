from __future__ import annotations

import json
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
testclient = pytest.importorskip("fastapi.testclient")

FastAPI = fastapi.FastAPI
TestClient = testclient.TestClient

from mika_chat_core.config import Config
from mika_chat_core.runtime import get_config as get_runtime_config
from mika_chat_core.webui import create_webui_router


def _make_config(**overrides: object) -> Config:
    payload: dict[str, object] = {
        "mika_master_id": "1",
        "llm_api_key": "A" * 32,
        "mika_webui_enabled": True,
        "mika_webui_base_path": "/webui",
        "mika_webui_token": "",
        "mika_health_check_api_probe_enabled": False,
    }
    payload.update(overrides)
    return Config(**payload)


def test_webui_config_get_sections_contains_llm_provider():
    config = _make_config()
    app = FastAPI()
    app.include_router(create_webui_router(settings_getter=lambda: config))
    client = TestClient(app)

    response = client.get("/webui/api/config")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "sections" in body["data"]

    keys = {
        field["key"]
        for section in body["data"]["sections"]
        for field in section.get("fields", [])
    }
    assert "llm_provider" in keys
    assert "mika_webui_enabled" in keys


def test_webui_config_get_marks_message_stream_fields_as_advanced():
    config = _make_config()
    app = FastAPI()
    app.include_router(create_webui_router(settings_getter=lambda: config))
    client = TestClient(app)

    response = client.get("/webui/api/config")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"

    field_map = {
        field["key"]: field
        for section in body["data"]["sections"]
        for field in section.get("fields", [])
    }
    assert field_map["mika_message_split_max_chunks"]["type"] == "integer"
    assert field_map["mika_reply_stream_enabled"]["advanced"] is True
    assert field_map["mika_reply_stream_mode"]["advanced"] is True
    assert field_map["mika_message_split_enabled"].get("advanced") is None


def test_webui_config_put_updates_env_file(monkeypatch, tmp_path):
    config = _make_config()
    app = FastAPI()
    app.include_router(create_webui_router(settings_getter=lambda: config))
    client = TestClient(app)

    env_path = tmp_path / ".env"
    env_path.write_text("LLM_PROVIDER=\"openai_compat\"\n", encoding="utf-8")
    monkeypatch.setenv("DOTENV_PATH", str(env_path))

    response = client.put(
        "/webui/api/config",
        json={
            "llm_provider": "anthropic",
            "mika_webui_enabled": True,
            "mika_group_whitelist": ["10001", "10002"],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["data"]["ok"] is True
    assert body["data"]["restart_required"] is True

    content = env_path.read_text(encoding="utf-8")
    assert 'LLM_PROVIDER="anthropic"' in content
    assert "MIKA_WEBUI_ENABLED=true" in content
    assert f"MIKA_GROUP_WHITELIST={json.dumps(['10001', '10002'])}" in content


def test_webui_config_put_rejects_unknown_key():
    config = _make_config()
    app = FastAPI()
    app.include_router(create_webui_router(settings_getter=lambda: config))
    client = TestClient(app)

    response = client.put("/webui/api/config", json={"unknown_field_x": 1})
    assert response.status_code == 400
    body = response.json()
    assert body["status"] == "error"


def test_webui_config_reload_from_env_file(monkeypatch, tmp_path: Path):
    config = _make_config()
    app = FastAPI()
    app.include_router(create_webui_router(settings_getter=lambda: config))
    client = TestClient(app)

    env_path = tmp_path / ".env"
    env_path.write_text(
        'LLM_PROVIDER="anthropic"\nMIKA_WEBUI_ENABLED=false\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("DOTENV_PATH", str(env_path))

    response = client.post("/webui/api/config/reload")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["data"]["reloaded"] is True

    runtime_cfg = get_runtime_config()
    assert runtime_cfg.llm_provider == "anthropic"
    assert runtime_cfg.mika_webui_enabled is False
    # reload 应同步到当前 settings_getter 返回的配置对象，避免“重载成功但仍用旧值”
    assert config.llm_provider == "anthropic"
    assert config.mika_webui_enabled is False


def test_webui_config_export_masks_secrets_by_default():
    real_key = "real-secret-key-1234567890"
    config = _make_config(llm_api_key=real_key)
    app = FastAPI()
    app.include_router(create_webui_router(settings_getter=lambda: config))
    client = TestClient(app)

    response = client.get("/webui/api/config/export")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["data"]["config"]["llm_api_key"] == "••••••••"

    response = client.get("/webui/api/config/export", params={"include_secrets": "true"})
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["config"]["llm_api_key"] == real_key


def test_webui_config_import_writes_env_and_applies_runtime(monkeypatch, tmp_path: Path):
    config = _make_config()
    app = FastAPI()
    app.include_router(create_webui_router(settings_getter=lambda: config))
    client = TestClient(app)

    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")
    monkeypatch.setenv("DOTENV_PATH", str(env_path))

    response = client.post(
        "/webui/api/config/import",
        json={
            "config": {
                "llm_provider": "azure_openai",
                "mika_webui_enabled": False,
            },
            "apply_runtime": True,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["data"]["ok"] is True
    assert set(body["data"]["updated_keys"]) == {"llm_provider", "mika_webui_enabled"}
    assert body["data"]["applied_runtime"] is True

    content = env_path.read_text(encoding="utf-8")
    assert 'LLM_PROVIDER="azure_openai"' in content
    assert "MIKA_WEBUI_ENABLED=false" in content
    assert config.llm_provider == "azure_openai"
    assert config.mika_webui_enabled is False
