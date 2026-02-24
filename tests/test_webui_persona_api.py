from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

fastapi = pytest.importorskip("fastapi")
httpx = pytest.importorskip("httpx")

FastAPI = fastapi.FastAPI

from mika_chat_core.config import Config
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


@dataclass
class _DummyPersona:
    id: int
    name: str
    character_prompt: str
    is_active: bool = False
    dialogue_examples: list[dict[str, Any]] = field(default_factory=list)
    error_messages: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "character_prompt": self.character_prompt,
            "is_active": self.is_active,
            "dialogue_examples": self.dialogue_examples,
            "error_messages": self.error_messages,
        }


class _DummyPersonaManager:
    def __init__(self) -> None:
        self._items = [_DummyPersona(id=1, name="默认", character_prompt="默认人设", is_active=True)]
        self._seq = 1

    async def init_table(self, **_kwargs) -> None:
        return None

    async def list_personas(self):
        return list(self._items)

    async def get_active_persona(self):
        return next((item for item in self._items if item.is_active), None)

    async def create_persona(self, **kwargs):
        self._seq += 1
        item = _DummyPersona(
            id=self._seq,
            name=str(kwargs["name"]),
            character_prompt=str(kwargs["character_prompt"]),
            is_active=bool(kwargs.get("is_active")),
            dialogue_examples=list(kwargs.get("dialogue_examples") or []),
            error_messages=dict(kwargs.get("error_messages") or {}),
        )
        self._items.append(item)
        if item.is_active:
            await self.set_active(item.id)
        return item

    async def update_persona(self, persona_id: int, **kwargs):
        target = next((item for item in self._items if item.id == persona_id), None)
        if target is None:
            return None
        if kwargs.get("name") is not None:
            target.name = str(kwargs["name"])
        if kwargs.get("character_prompt") is not None:
            target.character_prompt = str(kwargs["character_prompt"])
        if kwargs.get("is_active") is True:
            await self.set_active(target.id)
        return target

    async def set_active(self, persona_id: int):
        target = next((item for item in self._items if item.id == persona_id), None)
        if target is None:
            return False
        for item in self._items:
            item.is_active = item.id == persona_id
        return True

    async def delete_persona(self, persona_id: int):
        before = len(self._items)
        self._items = [item for item in self._items if item.id != persona_id]
        if len(self._items) == before:
            return False
        if self._items and not any(item.is_active for item in self._items):
            self._items[0].is_active = True
        return True


@pytest.mark.asyncio
async def test_webui_persona_crud(monkeypatch):
    config = _make_config()
    app = FastAPI()
    app.include_router(create_webui_router(settings_getter=lambda: config))
    transport = httpx.ASGITransport(app=app)

    manager = _DummyPersonaManager()
    monkeypatch.setattr(
        "mika_chat_core.webui.api_persona.get_persona_manager",
        lambda: manager,
    )

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        list_resp = await client.get("/webui/api/persona")
    assert list_resp.status_code == 200
    assert list_resp.json()["status"] == "ok"

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        create_resp = await client.post(
            "/webui/api/persona",
            json={
                "name": "新角色",
                "character_prompt": "你是新角色。",
                "is_active": False,
            },
        )
    assert create_resp.status_code == 200
    created = create_resp.json()["data"]
    assert created["name"] == "新角色"

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        activate_resp = await client.post(f"/webui/api/persona/{created['id']}/activate")
    assert activate_resp.status_code == 200
    assert activate_resp.json()["data"]["is_active"] is True

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        update_resp = await client.put(
            f"/webui/api/persona/{created['id']}",
            json={"character_prompt": "你是更新后的角色。"},
        )
    assert update_resp.status_code == 200
    assert "更新后" in update_resp.json()["data"]["character_prompt"]

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        delete_resp = await client.delete(f"/webui/api/persona/{created['id']}")
    assert delete_resp.status_code == 200
    assert delete_resp.json()["data"]["ok"] is True
