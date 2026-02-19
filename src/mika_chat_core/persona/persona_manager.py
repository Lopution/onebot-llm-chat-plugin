"""Persona manager backed by SQLite."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from typing import Any, Dict, Optional

from ..infra.logging import logger as log
from ..utils.context_db import get_db, get_db_path
from .persona_model import Persona


def _json_dumps(value: Any, fallback: str) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return fallback


def _json_loads(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _normalize_examples(value: Any) -> list[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _normalize_error_messages(value: Any) -> Dict[str, str]:
    if not isinstance(value, dict):
        return {}
    normalized: Dict[str, str] = {}
    for key, item in value.items():
        normalized[str(key)] = str(item)
    return normalized


class PersonaManager:
    """CRUD manager for personas."""

    def __init__(self) -> None:
        self._init_lock = asyncio.Lock()
        self._initialized = False
        self._initialized_db_path = ""

    async def init_table(self, *, seed_prompt_file: str = "system.yaml") -> None:
        current_db_path = str(get_db_path())
        if self._initialized and self._initialized_db_path == current_db_path:
            return
        async with self._init_lock:
            current_db_path = str(get_db_path())
            if self._initialized and self._initialized_db_path == current_db_path:
                return
            db = await get_db()
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS personas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    character_prompt TEXT NOT NULL,
                    dialogue_examples TEXT NOT NULL DEFAULT '[]',
                    error_messages TEXT NOT NULL DEFAULT '{}',
                    is_active INTEGER NOT NULL DEFAULT 0,
                    temperature_override REAL,
                    model_override TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_personas_active ON personas(is_active)"
            )
            await db.commit()
            await self._seed_if_empty(prompt_file=seed_prompt_file)
            self._initialized = True
            self._initialized_db_path = current_db_path

    async def _seed_if_empty(self, *, prompt_file: str = "system.yaml") -> None:
        db = await get_db()
        async with db.execute("SELECT COUNT(*) FROM personas") as cursor:
            row = await cursor.fetchone()
        if row and int(row[0] or 0) > 0:
            return

        from ..utils.prompt_loader import FALLBACK_SYSTEM_PROMPT, load_prompt_yaml

        cfg = load_prompt_yaml(prompt_file)
        name = str(cfg.get("name") or "").strip() or "Mika"
        character_prompt = str(cfg.get("character_prompt") or "").strip() or FALLBACK_SYSTEM_PROMPT
        dialogue_examples = _normalize_examples(cfg.get("dialogue_examples"))
        error_messages = _normalize_error_messages(cfg.get("error_messages"))

        now = time.time()
        await db.execute(
            """
            INSERT INTO personas
            (name, character_prompt, dialogue_examples, error_messages, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, 1, ?, ?)
            """,
            (
                name,
                character_prompt,
                _json_dumps(dialogue_examples, "[]"),
                _json_dumps(error_messages, "{}"),
                now,
                now,
            ),
        )
        await db.commit()
        log.info(f"[Persona] seeded from prompt file: {prompt_file}")

    def _row_to_persona(self, row: sqlite3.Row | tuple[Any, ...] | None) -> Optional[Persona]:
        if row is None:
            return None
        if isinstance(row, tuple):
            data = {
                "id": row[0],
                "name": row[1],
                "character_prompt": row[2],
                "dialogue_examples": row[3],
                "error_messages": row[4],
                "is_active": row[5],
                "temperature_override": row[6],
                "model_override": row[7],
                "created_at": row[8],
                "updated_at": row[9],
            }
        else:
            data = dict(row)
        return Persona(
            id=int(data.get("id") or 0),
            name=str(data.get("name") or "").strip(),
            character_prompt=str(data.get("character_prompt") or ""),
            dialogue_examples=_normalize_examples(_json_loads(data.get("dialogue_examples"), [])),
            error_messages=_normalize_error_messages(_json_loads(data.get("error_messages"), {})),
            is_active=bool(int(data.get("is_active") or 0)),
            temperature_override=(
                None
                if data.get("temperature_override") is None
                else float(data.get("temperature_override"))
            ),
            model_override=str(data.get("model_override") or "").strip(),
            created_at=float(data.get("created_at") or 0.0),
            updated_at=float(data.get("updated_at") or 0.0),
        )

    async def list_personas(self) -> list[Persona]:
        await self.init_table()
        db = await get_db()
        db.row_factory = sqlite3.Row
        async with db.execute(
            """
            SELECT id, name, character_prompt, dialogue_examples, error_messages, is_active,
                   temperature_override, model_override, created_at, updated_at
            FROM personas
            ORDER BY is_active DESC, updated_at DESC, id DESC
            """
        ) as cursor:
            rows = await cursor.fetchall()
        return [item for item in (self._row_to_persona(row) for row in rows) if item is not None]

    async def get_persona(self, persona_id: int) -> Optional[Persona]:
        await self.init_table()
        db = await get_db()
        db.row_factory = sqlite3.Row
        async with db.execute(
            """
            SELECT id, name, character_prompt, dialogue_examples, error_messages, is_active,
                   temperature_override, model_override, created_at, updated_at
            FROM personas WHERE id = ?
            """,
            (int(persona_id),),
        ) as cursor:
            row = await cursor.fetchone()
        return self._row_to_persona(row)

    async def get_active_persona(self) -> Optional[Persona]:
        await self.init_table()
        db = await get_db()
        db.row_factory = sqlite3.Row
        async with db.execute(
            """
            SELECT id, name, character_prompt, dialogue_examples, error_messages, is_active,
                   temperature_override, model_override, created_at, updated_at
            FROM personas WHERE is_active = 1
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """
        ) as cursor:
            row = await cursor.fetchone()
        return self._row_to_persona(row)

    def get_active_persona_sync(self) -> Optional[Persona]:
        db_path = get_db_path()
        if not db_path.exists():
            return None
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                """
                SELECT id, name, character_prompt, dialogue_examples, error_messages, is_active,
                       temperature_override, model_override, created_at, updated_at
                FROM personas WHERE is_active = 1
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """
            )
            row = cur.fetchone()
            conn.close()
            return self._row_to_persona(row)
        except Exception:
            return None

    async def create_persona(
        self,
        *,
        name: str,
        character_prompt: str,
        dialogue_examples: Any = None,
        error_messages: Any = None,
        temperature_override: float | None = None,
        model_override: str = "",
        is_active: bool = False,
    ) -> Persona:
        await self.init_table()
        normalized_name = str(name or "").strip()
        normalized_prompt = str(character_prompt or "").strip()
        if not normalized_name:
            raise ValueError("name is required")
        if not normalized_prompt:
            raise ValueError("character_prompt is required")

        examples = _normalize_examples(dialogue_examples)
        errors = _normalize_error_messages(error_messages)
        now = time.time()

        db = await get_db()
        cursor = await db.execute(
            """
            INSERT INTO personas
            (name, character_prompt, dialogue_examples, error_messages, is_active, temperature_override, model_override, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                normalized_name,
                normalized_prompt,
                _json_dumps(examples, "[]"),
                _json_dumps(errors, "{}"),
                1 if bool(is_active) else 0,
                temperature_override,
                str(model_override or "").strip(),
                now,
                now,
            ),
        )
        persona_id = int(cursor.lastrowid or 0)
        await db.commit()

        if bool(is_active):
            await self.set_active(persona_id)
        else:
            active = await self.get_active_persona()
            if active is None:
                await self.set_active(persona_id)
        created = await self.get_persona(persona_id)
        if created is None:
            raise RuntimeError("failed to create persona")
        return created

    async def update_persona(
        self,
        persona_id: int,
        *,
        name: Optional[str] = None,
        character_prompt: Optional[str] = None,
        dialogue_examples: Any = None,
        error_messages: Any = None,
        temperature_override: float | None = None,
        model_override: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> Optional[Persona]:
        await self.init_table()
        current = await self.get_persona(persona_id)
        if current is None:
            return None

        new_name = current.name if name is None else str(name or "").strip()
        new_prompt = current.character_prompt if character_prompt is None else str(character_prompt or "").strip()
        if not new_name or not new_prompt:
            raise ValueError("name and character_prompt must not be empty")

        new_examples = current.dialogue_examples if dialogue_examples is None else _normalize_examples(dialogue_examples)
        new_errors = current.error_messages if error_messages is None else _normalize_error_messages(error_messages)
        new_model_override = current.model_override if model_override is None else str(model_override or "").strip()
        new_temperature = current.temperature_override if temperature_override is None else temperature_override

        db = await get_db()
        await db.execute(
            """
            UPDATE personas
            SET name = ?, character_prompt = ?, dialogue_examples = ?, error_messages = ?,
                temperature_override = ?, model_override = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                new_name,
                new_prompt,
                _json_dumps(new_examples, "[]"),
                _json_dumps(new_errors, "{}"),
                new_temperature,
                new_model_override,
                time.time(),
                int(persona_id),
            ),
        )
        await db.commit()

        if is_active is True:
            await self.set_active(persona_id)
        elif is_active is False and current.is_active:
            personas = await self.list_personas()
            fallback = next((item for item in personas if item.id != int(persona_id)), None)
            if fallback is not None:
                await self.set_active(fallback.id)
        return await self.get_persona(persona_id)

    async def delete_persona(self, persona_id: int) -> bool:
        await self.init_table()
        current = await self.get_persona(persona_id)
        if current is None:
            return False

        db = await get_db()
        await db.execute("DELETE FROM personas WHERE id = ?", (int(persona_id),))
        await db.commit()

        if current.is_active:
            personas = await self.list_personas()
            if personas:
                await self.set_active(personas[0].id)
        return True

    async def set_active(self, persona_id: int) -> bool:
        await self.init_table()
        db = await get_db()
        await db.execute("UPDATE personas SET is_active = 0")
        cursor = await db.execute(
            "UPDATE personas SET is_active = 1, updated_at = ? WHERE id = ?",
            (time.time(), int(persona_id)),
        )
        await db.commit()
        return int(cursor.rowcount or 0) > 0


_manager: PersonaManager | None = None


def get_persona_manager() -> PersonaManager:
    global _manager
    if _manager is None:
        _manager = PersonaManager()
    return _manager


__all__ = ["PersonaManager", "get_persona_manager", "Persona"]
