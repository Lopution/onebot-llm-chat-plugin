from __future__ import annotations

import asyncio
import contextlib
import inspect
import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

fastapi = pytest.importorskip("fastapi")
httpx = pytest.importorskip("httpx")

FastAPI = fastapi.FastAPI

from mika_chat_core.config import Config
from mika_chat_core.tools_registry import ToolDefinition, ToolRegistry
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


class _DummyUserProfileStore:
    def __init__(self) -> None:
        self._profile = {
            "platform_user_id": "u1",
            "nickname": "Nick",
            "real_name": "Real",
            "identity": "student",
            "occupation": "dev",
            "age": "20",
            "location": "CN",
            "birthday": "01-01",
            "preferences": ["cat"],
            "dislikes": ["noise"],
            "extra_info": {"k": "v"},
            "created_at": "2026-01-01",
            "updated_at": "2026-01-02",
        }

    async def list_profiles(self, *, page: int, page_size: int, query: str):
        return {
            "items": [self._profile],
            "total": 1,
            "page": page,
            "page_size": page_size,
            "query": query,
        }

    async def get_profile(self, platform_user_id: str):
        if platform_user_id != "u1":
            return {}
        return dict(self._profile)

    async def update_profile(self, platform_user_id: str, payload: dict):
        if platform_user_id != "u1":
            return False
        self._profile.update(payload)
        return True

    async def clear_profile(self, platform_user_id: str):
        return platform_user_id == "u1"


class _DummyRuntimeClient:
    async def chat(self, message: str, **_kwargs):
        return f"echo:{message}"

    async def chat_stream(self, message: str, **_kwargs):
        yield "echo:"
        yield message


class _ASGIWebSocketClient:
    def __init__(self, app, path: str) -> None:
        self._app = app
        self._path = path
        self._to_app: asyncio.Queue[dict] = asyncio.Queue()
        self._from_app: asyncio.Queue[dict] = asyncio.Queue()
        self._task: asyncio.Task | None = None

    async def _receive(self) -> dict:
        return await self._to_app.get()

    async def _send(self, message: dict) -> None:
        await self._from_app.put(message)

    async def connect(self) -> None:
        scope = {
            "type": "websocket",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "scheme": "ws",
            "path": self._path,
            "raw_path": self._path.encode("utf-8"),
            "query_string": b"",
            "root_path": "",
            "headers": [(b"host", b"testserver")],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "subprotocols": [],
            "state": {},
        }
        self._task = asyncio.create_task(self._app(scope, self._receive, self._send))
        await self._to_app.put({"type": "websocket.connect"})

        # Wait for accept/close
        msg = await asyncio.wait_for(self._from_app.get(), timeout=2.0)
        assert msg["type"] == "websocket.accept", msg

    async def send_json(self, payload: dict) -> None:
        await self._to_app.put({"type": "websocket.receive", "text": json.dumps(payload)})

    async def receive_json(self, *, timeout: float = 2.0) -> dict:
        while True:
            msg = await asyncio.wait_for(self._from_app.get(), timeout=timeout)
            msg_type = msg.get("type")
            if msg_type == "websocket.send":
                text = msg.get("text")
                if isinstance(text, str):
                    return json.loads(text)
                data = msg.get("bytes") or b""
                return json.loads(bytes(data).decode("utf-8"))
            if msg_type == "websocket.close":
                raise AssertionError(f"websocket closed: {msg!r}")

    async def close(self) -> None:
        await self._to_app.put({"type": "websocket.disconnect", "code": 1000})
        if self._task is None:
            return
        try:
            await asyncio.wait_for(self._task, timeout=2.0)
        except TimeoutError:
            self._task.cancel()
            with contextlib.suppress(Exception):
                await self._task


async def _dummy_tool_handler(_args: dict, _group_id: str) -> str:
    return "ok"


@pytest.mark.asyncio
async def test_webui_tools_toggle_and_user_profile_endpoints(monkeypatch):
    config = _make_config()
    app = FastAPI()
    app.include_router(create_webui_router(settings_getter=lambda: config))
    transport = httpx.ASGITransport(app=app)

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="web_search",
            description="search",
            parameters={"type": "object", "properties": {}},
            handler=_dummy_tool_handler,
            source="builtin",
            enabled=True,
        )
    )
    tool_state_store = SimpleNamespace(set_enabled=AsyncMock())
    monkeypatch.setattr("mika_chat_core.webui.api_tools.get_tool_registry", lambda: registry)
    monkeypatch.setattr("mika_chat_core.webui.api_tools.get_tool_state_store", lambda: tool_state_store)

    profile_store = _DummyUserProfileStore()
    monkeypatch.setattr("mika_chat_core.webui.api_user_profile.get_user_profile_store", lambda: profile_store)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        tools_resp = await client.get("/webui/api/tools")
    assert tools_resp.status_code == 200
    assert tools_resp.json()["data"]["total"] == 1

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        toggle_resp = await client.post("/webui/api/tools/web_search/toggle", json={"enabled": False})
    assert toggle_resp.status_code == 200
    assert toggle_resp.json()["data"]["enabled"] is False
    assert registry.get("web_search").enabled is False
    assert tool_state_store.set_enabled.await_count == 1

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        list_resp = await client.get(
            "/webui/api/user-profile",
            params={"page": 1, "page_size": 20, "query": ""},
        )
    assert list_resp.status_code == 200
    assert list_resp.json()["data"]["total"] == 1

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        detail_resp = await client.get("/webui/api/user-profile/u1")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["data"]["nickname"] == "Nick"

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        update_resp = await client.put("/webui/api/user-profile/u1", json={"nickname": "NewNick"})
    assert update_resp.status_code == 200
    assert update_resp.json()["data"]["nickname"] == "NewNick"

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        delete_resp = await client.delete("/webui/api/user-profile/u1")
    assert delete_resp.status_code == 200
    assert delete_resp.json()["data"]["ok"] is True


@pytest.mark.asyncio
async def test_webui_backup_export_and_import(monkeypatch, tmp_path: Path):
    config = _make_config()
    app = FastAPI()
    app.include_router(create_webui_router(settings_getter=lambda: config))

    db_path = tmp_path / "contexts.db"
    db_path.write_bytes(b"db-data")
    env_path = tmp_path / ".env"
    env_path.write_text('LLM_PROVIDER="openai_compat"\n', encoding="utf-8")
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / "system.yaml").write_text("name: test\ncharacter_prompt: hi\n", encoding="utf-8")

    monkeypatch.setattr("mika_chat_core.webui.api_backup.get_db_path", lambda: db_path)
    monkeypatch.setattr("mika_chat_core.webui.api_backup._resolve_env_path", lambda: env_path)
    monkeypatch.setattr("mika_chat_core.webui.api_backup._prompts_dir", lambda: prompts_dir)
    monkeypatch.setattr("mika_chat_core.webui.api_backup.close_database", AsyncMock())
    monkeypatch.setattr("mika_chat_core.webui.api_backup.init_database", AsyncMock())
    monkeypatch.setattr(
        "mika_chat_core.webui.api_backup._build_config_from_env_file",
        lambda _path, current_config: current_config,
    )
    monkeypatch.setattr("mika_chat_core.webui.api_backup.set_runtime_config", lambda _cfg: None)

    export_endpoint = None
    import_endpoint = None
    for route in app.router.routes:
        path = str(getattr(route, "path", "") or "")
        if path == "/webui/api/backup/export":
            export_endpoint = getattr(route, "endpoint", None)
        if path == "/webui/api/backup/import":
            import_endpoint = getattr(route, "endpoint", None)
    assert callable(export_endpoint)
    assert callable(import_endpoint)

    export_response = await export_endpoint()
    export_path = Path(getattr(export_response, "path", ""))
    export_bytes = export_path.read_bytes()
    export_path.unlink(missing_ok=True)
    with zipfile.ZipFile(io.BytesIO(export_bytes), "r") as archive:
        names = set(archive.namelist())
    assert "contexts.db" in names
    assert ".env" in names
    assert "prompts/system.yaml" in names
    assert "manifest.json" in names

    upload_bytes = io.BytesIO()
    with zipfile.ZipFile(upload_bytes, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("contexts.db", b"new-db")
        archive.writestr(".env", b'LLM_PROVIDER="anthropic"\n')
        archive.writestr("prompts/system.yaml", "name: restored\ncharacter_prompt: ok\n")

    params = inspect.signature(import_endpoint).parameters
    if "file" not in params:
        import_response = await import_endpoint()
        assert getattr(import_response, "status_code", 0) == 400
        payload = json.loads(bytes(getattr(import_response, "body", b"{}")).decode("utf-8"))
        assert payload["status"] == "error"
        assert "python-multipart" in str(payload.get("message") or "")
        return

    class _DummyUploadFile:
        def __init__(self, *, filename: str, payload: bytes) -> None:
            self.filename = filename
            self._payload = payload

        async def read(self) -> bytes:
            return self._payload

        async def close(self) -> None:
            return None

    upload_file = _DummyUploadFile(filename="backup.zip", payload=upload_bytes.getvalue())
    import_result = await import_endpoint(file=upload_file, apply_runtime=True)
    assert import_result["status"] == "ok"
    data = import_result["data"]
    assert data["restored_db"] is True
    assert data["restored_env"] is True
    assert data["restored_prompts"] == 1


@pytest.mark.asyncio
async def test_webui_live_chat_http_and_ws(monkeypatch):
    config = _make_config()
    app = FastAPI()
    app.include_router(create_webui_router(settings_getter=lambda: config))
    transport = httpx.ASGITransport(app=app)

    monkeypatch.setattr(
        "mika_chat_core.webui.api_live_chat.get_runtime_client",
        lambda: _DummyRuntimeClient(),
    )

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        http_resp = await client.post(
            "/webui/api/live-chat/message",
            json={"message": "hello", "session_id": "private:test", "user_id": "test", "group_id": ""},
        )
    assert http_resp.status_code == 200
    assert http_resp.json()["data"]["reply"] == "echo:hello"

    websocket = _ASGIWebSocketClient(app, "/webui/api/live-chat/ws")
    await websocket.connect()
    await websocket.send_json(
        {
            "request_id": "ws-1",
            "message": "world",
            "session_id": "private:test",
            "user_id": "test",
            "group_id": "",
        }
    )
    reply = await websocket.receive_json()
    assert reply["type"] == "reply"
    assert reply["reply"] == "echo:world"

    await websocket.send_json(
        {
            "request_id": "ws-2",
            "message": "stream",
            "session_id": "private:test",
            "user_id": "test",
            "group_id": "",
            "stream": True,
        }
    )
    delta1 = await websocket.receive_json()
    delta2 = await websocket.receive_json()
    final_reply = await websocket.receive_json()
    assert delta1["type"] == "delta"
    assert delta2["type"] == "delta"
    assert delta1["request_id"] == "ws-2"
    assert delta2["request_id"] == "ws-2"
    assert final_reply["type"] == "reply"
    assert final_reply["request_id"] == "ws-2"
    assert final_reply["reply"] == "echo:stream"
    await websocket.close()


@pytest.mark.asyncio
async def test_dashboard_timeline_endpoint(monkeypatch):
    config = _make_config()
    app = FastAPI()
    app.include_router(create_webui_router(settings_getter=lambda: config))
    transport = httpx.ASGITransport(app=app)

    monkeypatch.setattr(
        "mika_chat_core.webui.api_dashboard.get_metrics_timeline_store",
        lambda: SimpleNamespace(
            get_timeseries=lambda **_kwargs: {
                "hours": 24,
                "bucket_seconds": 3600,
                "points": [{"timestamp": 1700000000.0, "messages": 2, "llm_count": 1, "llm_p50_ms": 120.0, "llm_p95_ms": 120.0, "prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}],
            }
        ),
    )

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/webui/api/dashboard/timeline",
            params={"hours": 24, "bucket_seconds": 3600},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["data"]["hours"] == 24
    assert len(body["data"]["points"]) == 1
