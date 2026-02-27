from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_db_maintenance_prunes_archive_and_traces(tmp_path: Path, monkeypatch):
    from mika_chat_core.utils import context_db
    from mika_chat_core.utils.db_maintenance import DBMaintenanceService

    db_path = tmp_path / "contexts.db"
    monkeypatch.setenv("MIKA_CONTEXT_DB_PATH", str(db_path))
    # Ensure we follow env-path resolution in this test, avoiding any stale global overrides.
    context_db.set_db_path(None)
    try:
        await context_db.init_database()
        db = await context_db.get_db()

        now = time.time()
        old_ts = now - 20 * 86400

        # message_archive: 3 rows per session + 1 old row.
        for i in range(3):
            await db.execute(
                """
                INSERT INTO message_archive(context_key, user_id, role, content, message_id, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("group:1", "u1", "user", f"m{i}", f"m{i}", now - i),
            )
        for i in range(3):
            await db.execute(
                """
                INSERT INTO message_archive(context_key, user_id, role, content, message_id, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("group:2", "u2", "user", f"n{i}", f"n{i}", now - i),
            )
        await db.execute(
            """
            INSERT INTO message_archive(context_key, user_id, role, content, message_id, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("group:1", "u1", "user", "old", "old", old_ts),
        )

        # agent_traces: 1 old + 3 recent.
        await db.execute(
            """
            INSERT INTO agent_traces(request_id, session_key, user_id, group_id, created_at, plan_json, events_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("r-old", "group:1", "u1", "g1", old_ts, "", "[]"),
        )
        for i in range(3):
            await db.execute(
                """
                INSERT INTO agent_traces(request_id, session_key, user_id, group_id, created_at, plan_json, events_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (f"r{i}", "group:1", "u1", "g1", now - i, "", "[]"),
            )

        await db.commit()

        plugin_cfg = SimpleNamespace(
            mika_db_maintenance_enabled=True,
            mika_db_prune_archive_max_days=14,
            mika_db_prune_archive_max_rows_per_session=2,
            mika_db_vacuum_interval_hours=72,
            mika_trace_retention_days=1,
            mika_trace_max_rows=2,
            mika_memory_max_age_days=90,
        )

        result = await DBMaintenanceService().run_once(plugin_cfg=plugin_cfg, request_id="req-test")
        assert result.get("error") in {"", None}

        async with db.execute(
            "SELECT COUNT(*) FROM message_archive WHERE context_key = ?",
            ("group:1",),
        ) as cur:
            row = await cur.fetchone()
        assert int(row[0] or 0) <= 2

        async with db.execute(
            "SELECT COUNT(*) FROM message_archive WHERE context_key = ?",
            ("group:2",),
        ) as cur:
            row = await cur.fetchone()
        assert int(row[0] or 0) <= 2

        # old trace row removed; total capped to 2 rows
        async with db.execute("SELECT COUNT(*) FROM agent_traces") as cur:
            row = await cur.fetchone()
        assert int(row[0] or 0) <= 2
    finally:
        await context_db.close_database()
        context_db.set_db_path(None)
