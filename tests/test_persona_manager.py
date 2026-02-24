"""persona_manager 单元测试。"""

from __future__ import annotations

import pytest

from mika_chat_core.persona.persona_manager import get_persona_manager


@pytest.fixture
async def persona_manager(tmp_path, monkeypatch):
    db_path = tmp_path / "persona_test.db"
    monkeypatch.setenv("MIKA_CONTEXT_DB_PATH", str(db_path))

    from mika_chat_core.utils import context_db
    from mika_chat_core.persona import persona_manager as persona_manager_module

    if context_db._db_connection is not None:
        await context_db._db_connection.close()
    context_db._db_connection = None
    context_db._db_connection_path = None
    persona_manager_module._manager = None

    manager = get_persona_manager()
    await manager.init_table(seed_prompt_file="system.yaml")
    yield manager

    if context_db._db_connection is not None:
        await context_db._db_connection.close()
    context_db._db_connection = None
    context_db._db_connection_path = None
    persona_manager_module._manager = None


@pytest.mark.asyncio
async def test_seed_and_get_active_persona(persona_manager):
    active = await persona_manager.get_active_persona()
    assert active is not None
    assert bool(active.is_active) is True
    assert str(active.name).strip() != ""
    assert str(active.character_prompt).strip() != ""


@pytest.mark.asyncio
async def test_create_update_activate_delete_persona(persona_manager):
    created = await persona_manager.create_persona(
        name="测试人设A",
        character_prompt="你是测试人设A。",
        dialogue_examples=[{"scenario": "问候", "user": "hi", "bot": "hello"}],
        error_messages={"default": "出错了"},
        is_active=False,
    )
    assert created.id > 0
    assert created.name == "测试人设A"

    updated = await persona_manager.update_persona(
        created.id,
        character_prompt="你是更新后的测试人设A。",
        is_active=True,
    )
    assert updated is not None
    assert "更新后" in updated.character_prompt
    assert updated.is_active is True

    active = await persona_manager.get_active_persona()
    assert active is not None
    assert active.id == created.id

    deleted = await persona_manager.delete_persona(created.id)
    assert deleted is True
    assert await persona_manager.get_persona(created.id) is None


@pytest.mark.asyncio
async def test_prompt_loader_prefers_active_persona(tmp_path, monkeypatch):
    db_path = tmp_path / "persona_prompt.db"
    monkeypatch.setenv("MIKA_CONTEXT_DB_PATH", str(db_path))

    from mika_chat_core.utils import context_db
    from mika_chat_core.persona import persona_manager as persona_manager_module
    from mika_chat_core.utils.prompt_loader import get_character_name, get_system_prompt

    if context_db._db_connection is not None:
        await context_db._db_connection.close()
    context_db._db_connection = None
    context_db._db_connection_path = None
    persona_manager_module._manager = None

    manager = get_persona_manager()
    await manager.init_table(seed_prompt_file="system.yaml")
    custom = await manager.create_persona(
        name="数据库人设",
        character_prompt="你是数据库人设，称呼{master_name}。",
        is_active=True,
    )
    assert custom.is_active is True

    prompt = get_system_prompt("system.yaml", master_name="老师", current_date="2026年02月13日")
    assert "数据库人设" in get_character_name("system.yaml")
    assert "称呼老师" in prompt

