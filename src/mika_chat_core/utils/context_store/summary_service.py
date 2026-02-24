"""ContextStore - 摘要与关键信息提取辅助逻辑。"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


def extract_key_info_from_history(
    messages: List[Dict[str, Any]],
    *,
    extract_user_identity_from_message_fn,
    extract_key_info_from_message_fn,
) -> Dict[str, Dict[str, str]]:
    """从历史消息中提取所有用户的关键信息。"""
    user_info: Dict[str, Dict[str, str]] = {}

    for msg in messages:
        if msg.get("role") != "user":
            continue

        content = msg.get("content", "")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    content = item.get("text", "")
                    break
            else:
                continue

        if not isinstance(content, str):
            continue

        user_id, nickname = extract_user_identity_from_message_fn(content)
        if not user_id:
            continue

        if user_id not in user_info:
            user_info[user_id] = {}
        if nickname:
            user_info[user_id]["__nickname__"] = nickname

        info = extract_key_info_from_message_fn(content)
        if info:
            user_info[user_id].update(info)

    return user_info


def build_key_info_summary(user_info: Dict[str, Dict[str, str]]) -> str:
    """构建关键信息摘要。"""
    if not user_info:
        return ""

    summary_parts: List[str] = []
    for user_id, info in user_info.items():
        public_info = {k: v for k, v in info.items() if not k.startswith("__")}
        if not public_info:
            continue

        user_desc: List[str] = []
        if "name" in info:
            user_desc.append(f"自称{info['name']}")
        if "identity" in info:
            user_desc.append(f"是{info['identity']}")
        if "occupation" in info:
            user_desc.append(f"职业是{info['occupation']}")
        if "age" in info:
            user_desc.append(f"{info['age']}岁")
        if "preference" in info:
            user_desc.append(f"喜欢{info['preference']}")

        nickname = info.get("__nickname__", "未知")
        if user_desc:
            if user_id == "MASTER":
                summary_parts.append(f"Sensei: {', '.join(user_desc)}")
            else:
                summary_parts.append(f"用户 [{nickname}({user_id})]: {', '.join(user_desc)}")

    return "; ".join(summary_parts)


def resolve_summary_runtime_config(*, get_runtime_config_fn) -> Tuple[str, str, str, Dict[str, str]]:
    """解析摘要调用所需的 provider/base_url/model/key。"""
    try:
        cfg = get_runtime_config_fn()
        llm_cfg = cfg.get_llm_config()
        provider = str(llm_cfg.get("provider") or "openai_compat")
        base_url = str(llm_cfg.get("base_url") or cfg.llm_base_url or "").strip()
        model = str(cfg.resolve_task_model("summarizer", llm_cfg=llm_cfg) or "").strip()
        api_keys = list(llm_cfg.get("api_keys") or [])
        api_key = str(api_keys[0] if api_keys else cfg.llm_api_key or "").strip()
        extra_headers = dict(llm_cfg.get("extra_headers") or {})
        return provider, base_url, model, {"api_key": api_key, **extra_headers}
    except Exception:
        return "openai_compat", "", "", {"api_key": ""}


async def get_cached_summary(
    context_key: str,
    *,
    get_db_fn,
) -> Tuple[str, int]:
    try:
        db = await get_db_fn()
        async with db.execute(
            """
            SELECT summary, source_message_count
            FROM context_summaries
            WHERE context_key = ?
            LIMIT 1
            """,
            (context_key,),
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            return "", 0
        return str(row[0] or ""), int(row[1] or 0)
    except Exception:
        return "", 0


async def save_cached_summary(
    context_key: str,
    summary: str,
    source_message_count: int,
    *,
    get_db_fn,
    log_obj,
) -> None:
    try:
        db = await get_db_fn()
        await db.execute(
            """
            INSERT INTO context_summaries (context_key, summary, source_message_count, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(context_key) DO UPDATE SET
                summary = excluded.summary,
                source_message_count = excluded.source_message_count,
                updated_at = CURRENT_TIMESTAMP
            """,
            (context_key, summary, int(source_message_count)),
        )
        await db.commit()
    except Exception as exc:
        log_obj.debug(f"写入 context summary 失败 | key={context_key} | error={exc}")


async def build_summary_for_messages(
    *,
    context_key: str,
    messages: List[Dict[str, Any]],
    summary_enabled: bool,
    context_summarizer: Any,
    summary_max_chars: int,
    get_cached_summary_caller,
    resolve_summary_runtime_config_caller,
    save_cached_summary_caller,
) -> str:
    """按需生成或复用历史摘要。"""
    if not summary_enabled or context_summarizer is None:
        return ""

    summary_source_messages: List[Dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        if str(message.get("role") or "").strip().lower() == "system":
            content = message.get("content", "")
            if isinstance(content, str) and content.strip().startswith("[历史摘要]"):
                continue
        summary_source_messages.append(message)

    source_count = len(summary_source_messages)
    cached_summary, cached_count = await get_cached_summary_caller(context_key)
    if source_count <= 0:
        return cached_summary
    if cached_summary and source_count <= cached_count:
        return cached_summary

    provider, base_url, model, meta = resolve_summary_runtime_config_caller()
    api_key = str(meta.pop("api_key", "") or "").strip()
    if not api_key or not base_url or not model:
        return cached_summary

    summary = await context_summarizer.summarize(
        summary_source_messages,
        api_key=api_key,
        base_url=base_url,
        model=model,
        provider=provider,
        extra_headers=meta,
        max_chars=summary_max_chars,
        existing_summary=cached_summary,
    )
    if summary:
        await save_cached_summary_caller(context_key, summary, source_count)
        return summary
    return cached_summary
