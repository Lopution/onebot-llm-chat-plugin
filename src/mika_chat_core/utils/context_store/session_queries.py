"""ContextStore - 会话查询与清理辅助逻辑。"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List


def preview_text(
    raw_content: Any,
    *,
    textify_content_for_snapshot_fn,
    max_length: int = 120,
) -> str:
    """将消息内容转换为可展示的单行预览文本。"""
    text = ""
    if isinstance(raw_content, str):
        candidate = raw_content.strip()
        if candidate and candidate[:1] in {"[", "{"}:
            try:
                parsed = json.loads(candidate)
                text = textify_content_for_snapshot_fn(parsed)
            except Exception:
                text = candidate
        else:
            text = candidate
    else:
        text = textify_content_for_snapshot_fn(raw_content)

    text = re.sub(r"\s+", " ", str(text or "").strip())
    if len(text) > max_length:
        return text[: max_length - 1] + "…"
    return text


async def list_sessions(
    *,
    query: str,
    page: int,
    page_size: int,
    get_db_fn,
    log_obj,
) -> Dict[str, Any]:
    """分页列出会话（用于 WebUI 会话管理）。"""
    resolved_page = max(1, int(page or 1))
    resolved_page_size = max(1, min(100, int(page_size or 20)))
    resolved_query = str(query or "").strip()
    like_expr = f"%{resolved_query}%"
    offset = (resolved_page - 1) * resolved_page_size

    try:
        db = await get_db_fn()
        async with db.execute(
            "SELECT COUNT(*) FROM contexts WHERE context_key LIKE ?",
            (like_expr,),
        ) as cursor:
            total_row = await cursor.fetchone()
        total = int(total_row[0] or 0) if total_row else 0

        async with db.execute(
            """
            SELECT
                c.context_key,
                c.updated_at,
                COALESCE(a.message_count, 0) AS message_count,
                COALESCE(a.last_message_at, 0) AS last_message_at
            FROM contexts c
            LEFT JOIN (
                SELECT
                    context_key,
                    COUNT(*) AS message_count,
                    MAX(COALESCE(timestamp, 0)) AS last_message_at
                FROM message_archive
                GROUP BY context_key
            ) a ON a.context_key = c.context_key
            WHERE c.context_key LIKE ?
            ORDER BY
                COALESCE(a.last_message_at, 0) DESC,
                c.updated_at DESC
            LIMIT ? OFFSET ?
            """,
            (like_expr, resolved_page_size, offset),
        ) as cursor:
            rows = await cursor.fetchall()

        items: List[Dict[str, Any]] = []
        for row in rows:
            session_key = str(row[0] or "")
            items.append(
                {
                    "session_key": session_key,
                    "updated_at": row[1],
                    "message_count": int(row[2] or 0),
                    "last_message_at": float(row[3] or 0),
                    "is_group": session_key.startswith("group:"),
                }
            )

        return {
            "items": items,
            "total": total,
            "page": resolved_page,
            "page_size": resolved_page_size,
            "query": resolved_query,
        }
    except Exception as exc:
        log_obj.error(f"列出会话失败: {exc}", exc_info=True)
        return {
            "items": [],
            "total": 0,
            "page": resolved_page,
            "page_size": resolved_page_size,
            "query": resolved_query,
        }


async def get_session_stats(
    session_key: str,
    *,
    preview_limit: int,
    get_db_fn,
    preview_text_fn,
    log_obj,
) -> Dict[str, Any]:
    """获取单个会话统计信息与消息预览。"""
    resolved_session_key = str(session_key or "").strip()
    if not resolved_session_key:
        return {"exists": False, "session_key": ""}

    resolved_preview_limit = max(1, min(20, int(preview_limit or 5)))

    message_count = 0
    user_message_count = 0
    assistant_message_count = 0
    tool_message_count = 0
    last_message_at = 0.0
    memory_count = 0
    topic_count = 0
    preview: List[Dict[str, Any]] = []
    updated_at = None
    snapshot_message_count = 0
    context_exists = False

    try:
        db = await get_db_fn()

        async with db.execute(
            "SELECT messages, updated_at FROM contexts WHERE context_key = ? LIMIT 1",
            (resolved_session_key,),
        ) as cursor:
            context_row = await cursor.fetchone()
        if context_row:
            context_exists = True
            updated_at = context_row[1]
            try:
                snapshot_messages = json.loads(context_row[0] or "[]")
            except Exception:
                snapshot_messages = []
            if isinstance(snapshot_messages, list):
                snapshot_message_count = len(snapshot_messages)

        async with db.execute(
            """
            SELECT
                COUNT(*) AS total_count,
                SUM(CASE WHEN role = 'user' THEN 1 ELSE 0 END) AS user_count,
                SUM(CASE WHEN role = 'assistant' THEN 1 ELSE 0 END) AS assistant_count,
                SUM(CASE WHEN role = 'tool' THEN 1 ELSE 0 END) AS tool_count,
                MAX(COALESCE(timestamp, 0)) AS last_message_at
            FROM message_archive
            WHERE context_key = ?
            """,
            (resolved_session_key,),
        ) as cursor:
            archive_row = await cursor.fetchone()
        if archive_row:
            message_count = int(archive_row[0] or 0)
            user_message_count = int(archive_row[1] or 0)
            assistant_message_count = int(archive_row[2] or 0)
            tool_message_count = int(archive_row[3] or 0)
            last_message_at = float(archive_row[4] or 0)
            if message_count > 0:
                context_exists = True

        try:
            async with db.execute(
                """
                SELECT role, content, message_id, timestamp
                FROM message_archive
                WHERE context_key = ?
                ORDER BY COALESCE(timestamp, 0) DESC, id DESC
                LIMIT ?
                """,
                (resolved_session_key, resolved_preview_limit),
            ) as cursor:
                preview_rows = await cursor.fetchall()
            for row in reversed(preview_rows):
                preview.append(
                    {
                        "role": str(row[0] or ""),
                        "content": preview_text_fn(row[1]),
                        "message_id": str(row[2] or ""),
                        "timestamp": float(row[3] or 0),
                    }
                )
        except Exception:
            preview = []

        try:
            async with db.execute(
                "SELECT COUNT(*) FROM memory_embeddings WHERE session_key = ?",
                (resolved_session_key,),
            ) as cursor:
                row = await cursor.fetchone()
            memory_count = int(row[0] or 0) if row else 0
        except Exception:
            memory_count = 0

        try:
            async with db.execute(
                "SELECT COUNT(*) FROM topic_summaries WHERE session_key = ?",
                (resolved_session_key,),
            ) as cursor:
                row = await cursor.fetchone()
            topic_count = int(row[0] or 0) if row else 0
        except Exception:
            topic_count = 0
    except Exception as exc:
        log_obj.error(f"获取会话统计失败: {exc}", exc_info=True)

    return {
        "exists": context_exists,
        "session_key": resolved_session_key,
        "updated_at": updated_at,
        "snapshot_message_count": snapshot_message_count,
        "message_count": message_count,
        "user_message_count": user_message_count,
        "assistant_message_count": assistant_message_count,
        "tool_message_count": tool_message_count,
        "memory_count": memory_count,
        "topic_count": topic_count,
        "last_message_at": last_message_at,
        "preview": preview,
    }


async def clear_session(
    session_key: str,
    *,
    purge_archive: bool,
    purge_topic_state: bool,
    cache_delete_fn,
    get_db_fn,
    log_obj,
) -> Dict[str, int]:
    """按会话键清空上下文数据（用于 WebUI）。"""
    resolved_session_key = str(session_key or "").strip()
    if not resolved_session_key:
        return {
            "contexts": 0,
            "archive": 0,
            "summaries": 0,
            "topic_summaries": 0,
            "topic_state": 0,
        }

    cache_delete_fn(resolved_session_key)

    deleted: Dict[str, int] = {
        "contexts": 0,
        "archive": 0,
        "summaries": 0,
        "topic_summaries": 0,
        "topic_state": 0,
    }

    try:
        db = await get_db_fn()
        cursor = await db.execute(
            "DELETE FROM contexts WHERE context_key = ?",
            (resolved_session_key,),
        )
        deleted["contexts"] = int(cursor.rowcount or 0)

        cursor = await db.execute(
            "DELETE FROM context_summaries WHERE context_key = ?",
            (resolved_session_key,),
        )
        deleted["summaries"] = int(cursor.rowcount or 0)

        if purge_archive:
            cursor = await db.execute(
                "DELETE FROM message_archive WHERE context_key = ?",
                (resolved_session_key,),
            )
            deleted["archive"] = int(cursor.rowcount or 0)

        if purge_topic_state:
            try:
                cursor = await db.execute(
                    "DELETE FROM topic_summaries WHERE session_key = ?",
                    (resolved_session_key,),
                )
                deleted["topic_summaries"] = int(cursor.rowcount or 0)
            except Exception:
                deleted["topic_summaries"] = 0
            try:
                cursor = await db.execute(
                    "DELETE FROM topic_summary_state WHERE session_key = ?",
                    (resolved_session_key,),
                )
                deleted["topic_state"] = int(cursor.rowcount or 0)
            except Exception:
                deleted["topic_state"] = 0

        await db.commit()
        log_obj.info(f"会话已清空: {resolved_session_key} | deleted={deleted}")
    except Exception as exc:
        log_obj.error(f"清空会话失败: {exc}", exc_info=True)

    return deleted


async def get_all_keys(
    *,
    get_db_fn,
    log_obj,
) -> List[str]:
    """获取所有上下文键（用于调试）。"""
    try:
        db = await get_db_fn()
        async with db.execute("SELECT context_key FROM contexts") as cursor:
            rows = await cursor.fetchall()
            keys = [row[0] for row in rows]
            log_obj.debug(f"获取所有键: 共 {len(keys)} 个")
            return keys
    except Exception as exc:
        log_obj.error(f"获取键列表失败: {exc}", exc_info=True)
        return []


async def get_stats(
    *,
    get_db_fn,
    get_db_path_fn,
    cache_len: int,
    max_cache_size: int,
    log_obj,
) -> Dict[str, Any]:
    """获取存储统计信息。"""
    try:
        db = await get_db_fn()
        async with db.execute("SELECT COUNT(*) FROM contexts") as cursor:
            row = await cursor.fetchone()
            total_contexts = row[0] if row else 0

        stats = {
            "total_contexts": total_contexts,
            "cached_contexts": cache_len,
            "max_cache_size": max_cache_size,
            "db_path": str(get_db_path_fn()),
        }
        log_obj.debug(f"存储统计: {stats}")
        return stats
    except Exception as exc:
        log_obj.error(f"获取统计信息失败: {exc}", exc_info=True)
        return {"error": str(exc)}
