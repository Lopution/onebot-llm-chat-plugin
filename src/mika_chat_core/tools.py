"""Tool handlers for mika_chat_core.

核心层只提供宿主无关实现；宿主特定能力（如 get_msg）通过 runtime 注入覆盖。
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict

from .infra.logging import logger
from .runtime import get_config as get_runtime_config
from .runtime import get_tool_override
from .tools_registry import ToolDefinition, get_tool_registry


TOOL_HANDLERS: Dict[str, Callable] = {}
_registry = get_tool_registry()


def tool(
    name: str,
    *,
    description: str = "",
    parameters: Dict[str, Any] | None = None,
    source: str = "builtin",
    enabled: bool = True,
):
    """工具注册装饰器。"""

    def decorator(func: Callable) -> Callable:
        TOOL_HANDLERS[name] = func
        _registry.register(
            ToolDefinition(
                name=name,
                description=description.strip() or str(getattr(func, "__doc__", "") or "").strip() or name,
                parameters=dict(parameters or {"type": "object", "properties": {}}),
                handler=func,  # type: ignore[arg-type]
                source=source,
                enabled=enabled,
            ),
            replace=True,
        )
        return func

    return decorator


def _resolve_tool_override(name: str) -> Callable | None:
    override = get_tool_override(name)
    return override if callable(override) else None


@tool(
    "search_group_history",
    description="搜索当前会话的历史消息记录。仅用于查询聊天上下文，不用于互联网实时信息。",
    parameters={
        "type": "object",
        "properties": {
            "count": {"type": "integer", "description": "要获取的历史消息数量，默认20，最大50"}
        },
    },
)
async def handle_search_group_history(args: dict, group_id: str) -> str:
    """群聊历史搜索工具（支持宿主覆盖）。"""
    override = _resolve_tool_override("search_group_history")
    if override is not None:
        return await override(args, group_id)

    from mika_chat_core.utils.context_store import get_context_store

    group_id_str = str(group_id or "").strip()
    if not group_id_str:
        return "该工具仅在群聊可用（需要 group_id）。"

    try:
        count = int(args.get("count", 20) if isinstance(args, dict) else 20)
        count = max(1, min(count, 50))

        store = get_context_store()
        history = await store.get_context(user_id="_tool_", group_id=group_id_str)
        if not history:
            return "没有找到历史消息。"

        def _content_to_text(content: Any) -> str:
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts: list[str] = []
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    item_type = item.get("type")
                    if item_type == "text":
                        parts.append(str(item.get("text") or ""))
                    elif item_type == "image_url":
                        parts.append("[图片]")
                return " ".join(p for p in parts if p)
            return str(content or "")

        lines: list[str] = []
        for msg in history[-count:]:
            role = str(msg.get("role") or "")
            content_text = _content_to_text(msg.get("content"))
            content_text = content_text.replace("\n", " ").strip()
            if not content_text:
                continue
            if role == "assistant" and not content_text.startswith("["):
                lines.append(f"[assistant]: {content_text}")
            else:
                lines.append(content_text)

        if not lines:
            return "没有找到可用的历史消息。"
        return "以下是查找到的历史消息：\n" + "\n".join(lines)
    except Exception as exc:
        logger.error(f"Failed to search group history: {exc}")
        return f"翻记录时出错了：{str(exc)}"


@tool(
    "web_search",
    description="搜索互联网获取实时信息。适用于新闻、天气、价格、赛事等时效性问题。",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词，应简洁明确"}
        },
        "required": ["query"],
    },
)
async def handle_web_search(args: dict, group_id: str = "") -> str:
    """Web 搜索工具处理器。"""
    from .utils.search_engine import google_search

    query = args.get("query", "") if isinstance(args, dict) else str(args)
    logger.debug(f"执行 web_search | query={query}")
    result = await google_search(query, "", "")
    return result if result else "未找到相关搜索结果"


@tool(
    "fetch_history_images",
    description="按消息ID回取历史图片，支持图片二阶段分析。",
    parameters={
        "type": "object",
        "properties": {
            "msg_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "需要回取图片的消息ID列表",
            },
            "max_images": {"type": "integer", "description": "最多回取图片数量"},
        },
        "required": ["msg_ids"],
    },
)
async def handle_fetch_history_images(args: dict, group_id: str = "") -> str:
    """历史图片回取工具（支持宿主覆盖）。"""
    override = _resolve_tool_override("fetch_history_images")
    if override is not None:
        return await override(args, group_id)

    from mika_chat_core.config import Config
    from mika_chat_core.metrics import metrics
    from mika_chat_core.utils.context_db import get_db
    from mika_chat_core.utils.context_schema import normalize_content
    from mika_chat_core.utils.image_processor import get_image_processor
    from mika_chat_core.utils.recent_images import get_image_cache

    try:
        try:
            plugin_config = get_runtime_config()
        except Exception:
            plugin_config = Config(  # type: ignore[call-arg]
                llm_api_key="test-api-key-12345678901234567890",
                mika_master_id="1",
            )

        max_allowed = int(getattr(plugin_config, "mika_history_image_two_stage_max", 2) or 2)

        group_id_str = str(group_id or "").strip()
        if not group_id_str:
            metrics.history_image_fetch_tool_fail_total += 1
            return json.dumps({"error": "group_id is required", "images": []})

        msg_ids = args.get("msg_ids", []) if isinstance(args, dict) else []
        max_images = min(
            int(args.get("max_images", 2) if isinstance(args, dict) else 2),
            max_allowed,
        )

        if not msg_ids:
            metrics.history_image_fetch_tool_fail_total += 1
            return json.dumps({"error": "No msg_ids provided", "images": []})

        msg_ids = msg_ids[:max_images]

        image_cache = get_image_cache()
        processor = get_image_processor()
        result_images: list[dict[str, str]] = []

        async def _append_data_url(
            *,
            msg_id: str,
            sender_name: str,
            image_url: str,
            source: str,
        ) -> None:
            if len(result_images) >= max_images:
                return
            try:
                base64_data, mime_type = await processor.download_and_encode(image_url)
                result_images.append(
                    {
                        "msg_id": msg_id,
                        "sender_name": sender_name,
                        "data_url": f"data:{mime_type};base64,{base64_data}",
                    }
                )
                if source == "cache":
                    metrics.history_image_fetch_tool_source_cache_total += 1
                elif source == "archive":
                    metrics.history_image_fetch_tool_source_archive_total += 1
            except Exception as exc:
                logger.warning(
                    f"fetch_history_images: 下载图片失败 | msg_id={msg_id} | source={source} | error={exc}"
                )

        for msg_id in msg_ids:
            if len(result_images) >= max_images:
                break

            cached_images, found = image_cache.get_images_by_message_id(
                group_id=group_id_str,
                user_id="",
                message_id=str(msg_id),
            )
            if found and cached_images:
                for img in cached_images:
                    if len(result_images) >= max_images:
                        break
                    await _append_data_url(
                        msg_id=str(msg_id),
                        sender_name=str(img.sender_name or "某人"),
                        image_url=str(img.url),
                        source="cache",
                    )
                if len(result_images) >= max_images:
                    continue

            try:
                db = await get_db()
                async with db.execute(
                    """
                    SELECT content
                    FROM message_archive
                    WHERE context_key = ? AND message_id = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (f"group:{group_id_str}", str(msg_id)),
                ) as cursor:
                    row = await cursor.fetchone()
            except Exception as exc:
                logger.warning(f"fetch_history_images: archive 回查失败 | msg_id={msg_id} | error={exc}")
                row = None

            archive_urls: list[str] = []
            if row and row[0]:
                raw_content = row[0]
                parsed_content: Any = raw_content
                if isinstance(raw_content, str):
                    try:
                        parsed_content = json.loads(raw_content)
                    except Exception:
                        parsed_content = raw_content
                normalized = normalize_content(parsed_content)
                if isinstance(normalized, list):
                    for part in normalized:
                        if not isinstance(part, dict):
                            continue
                        if str(part.get("type") or "").lower() != "image_url":
                            continue
                        image_url = part.get("image_url")
                        if isinstance(image_url, dict):
                            url = str(image_url.get("url") or "").strip()
                        else:
                            url = str(image_url or "").strip()
                        if url:
                            archive_urls.append(url)

            for img_url in archive_urls:
                if len(result_images) >= max_images:
                    break
                await _append_data_url(
                    msg_id=str(msg_id),
                    sender_name="某人",
                    image_url=img_url,
                    source="archive",
                )

        if not result_images:
            metrics.history_image_fetch_tool_fail_total += 1
            return json.dumps(
                {
                    "error": "No images found for the requested msg_ids",
                    "images": [],
                    "hint": "The images may have expired or the msg_ids are invalid.",
                }
            )

        mapping_parts = [
            f"Image {i+1} from <msg_id:{img['msg_id']}> (sent by {img['sender_name']})"
            for i, img in enumerate(result_images)
        ]

        metrics.history_image_fetch_tool_success_total += 1
        return json.dumps(
            {
                "success": True,
                "count": len(result_images),
                "mapping": mapping_parts,
                "images": [img["data_url"] for img in result_images],
            }
        )
    except Exception as exc:
        from mika_chat_core.metrics import metrics

        logger.error(f"fetch_history_images: 工具执行失败 | error={exc}", exc_info=True)
        metrics.history_image_fetch_tool_fail_total += 1
        return json.dumps({"error": str(exc), "images": []})


@tool(
    "search_knowledge",
    description="检索本地知识库（RAG）。适用于文档问答、设定查询、群规/FAQ 等非实时知识。",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "检索问题或关键词"},
            "corpus_id": {"type": "string", "description": "可选：指定知识库 corpus"},
            "top_k": {"type": "integer", "description": "可选：返回条数，默认 5"},
        },
        "required": ["query"],
    },
)
async def handle_search_knowledge(args: dict, group_id: str = "") -> str:
    from .config import Config
    from .utils.knowledge_store import get_knowledge_store
    from .utils.semantic_matcher import semantic_matcher

    try:
        try:
            runtime_cfg = get_runtime_config()
        except Exception:
            runtime_cfg = Config(  # type: ignore[call-arg]
                llm_api_key="test-api-key-12345678901234567890",
                mika_master_id="1",
            )

        if not bool(getattr(runtime_cfg, "mika_knowledge_enabled", False)):
            return "知识库功能未开启。"

        query = str((args or {}).get("query") or "").strip()
        if not query:
            return "缺少 query 参数。"

        query_embedding = semantic_matcher.encode(query)
        if query_embedding is None:
            return "语义向量不可用（请检查语义模型是否可用）。"

        corpus_id = str((args or {}).get("corpus_id") or "").strip()
        if not corpus_id:
            corpus_id = str(getattr(runtime_cfg, "mika_knowledge_default_corpus", "default") or "default")

        top_k_raw = (args or {}).get("top_k", getattr(runtime_cfg, "mika_knowledge_search_top_k", 5))
        top_k = max(1, min(int(top_k_raw or 5), 10))
        min_similarity = float(
            getattr(runtime_cfg, "mika_knowledge_min_similarity", 0.5) or 0.5
        )

        session_key = f"group:{group_id}" if str(group_id or "").strip() else ""
        store = get_knowledge_store()
        await store.init_table()
        results = await store.search(
            query_embedding,
            corpus_id=corpus_id,
            session_key=session_key or None,
            top_k=top_k,
            min_similarity=min_similarity,
        )
        if not results:
            return "没有检索到相关知识。"

        lines = []
        for idx, (entry, score) in enumerate(results, start=1):
            title = entry.title or entry.doc_id
            snippet = entry.content.replace("\n", " ").strip()
            if len(snippet) > 220:
                snippet = snippet[:220] + "..."
            lines.append(
                f"{idx}. ({score:.3f}) [{title}] {snippet} "
                f"(corpus={entry.corpus_id}, doc={entry.doc_id}, chunk={entry.chunk_id})"
            )
            await store.update_recall(entry.id)

        return "[Knowledge Search Results]\n" + "\n".join(lines)
    except Exception as exc:
        logger.error(f"search_knowledge: 工具执行失败 | error={exc}", exc_info=True)
        return f"知识库检索失败：{exc}"


@tool(
    "ingest_knowledge",
    description="写入知识库文档（文本切片并向量化存储）。通常由管理端调用，不建议模型在普通对话中频繁调用。",
    parameters={
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "要写入知识库的文档正文"},
            "doc_id": {"type": "string", "description": "文档 ID（可选，默认按内容摘要生成）"},
            "title": {"type": "string", "description": "文档标题（可选）"},
            "source": {"type": "string", "description": "来源标记（可选）"},
            "corpus_id": {"type": "string", "description": "知识库 corpus（可选）"},
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "标签（可选）",
            },
        },
        "required": ["content"],
    },
)
async def handle_ingest_knowledge(args: dict, group_id: str = "") -> str:
    import hashlib

    from .config import Config
    from .utils.knowledge_chunker import split_text_chunks
    from .utils.knowledge_store import get_knowledge_store
    from .utils.semantic_matcher import semantic_matcher

    try:
        try:
            runtime_cfg = get_runtime_config()
        except Exception:
            runtime_cfg = Config(  # type: ignore[call-arg]
                llm_api_key="test-api-key-12345678901234567890",
                mika_master_id="1",
            )

        if not bool(getattr(runtime_cfg, "mika_knowledge_enabled", False)):
            return json.dumps({"ok": False, "error": "knowledge_disabled"}, ensure_ascii=False)

        content = str((args or {}).get("content") or "").strip()
        if not content:
            return json.dumps({"ok": False, "error": "content_required"}, ensure_ascii=False)

        if len(content) > 120000:
            return json.dumps({"ok": False, "error": "content_too_large"}, ensure_ascii=False)

        corpus_id = str((args or {}).get("corpus_id") or "").strip()
        if not corpus_id:
            corpus_id = str(getattr(runtime_cfg, "mika_knowledge_default_corpus", "default") or "default")

        title = str((args or {}).get("title") or "").strip()
        source = str((args or {}).get("source") or "").strip()
        tags = (args or {}).get("tags")

        doc_id = str((args or {}).get("doc_id") or "").strip()
        if not doc_id:
            digest = hashlib.sha1(content.encode("utf-8")).hexdigest()[:16]
            doc_id = f"doc_{digest}"

        chunks = split_text_chunks(
            content,
            max_chars=int(getattr(runtime_cfg, "mika_knowledge_chunk_max_chars", 450) or 450),
            overlap_chars=int(
                getattr(runtime_cfg, "mika_knowledge_chunk_overlap_chars", 80) or 80
            ),
        )
        if not chunks:
            return json.dumps({"ok": False, "error": "empty_chunks"}, ensure_ascii=False)

        embeddings = semantic_matcher.encode_batch(chunks)
        if not embeddings or len(embeddings) != len(chunks):
            return json.dumps(
                {"ok": False, "error": "embedding_failed", "chunks": len(chunks)},
                ensure_ascii=False,
            )

        session_key = f"group:{group_id}" if str(group_id or "").strip() else ""
        store = get_knowledge_store()
        await store.init_table()
        inserted = await store.upsert_document(
            corpus_id=corpus_id,
            doc_id=doc_id,
            chunks=chunks,
            embeddings=embeddings,
            title=title,
            source=source,
            tags=tags,
            session_key=session_key,
        )

        return json.dumps(
            {
                "ok": inserted > 0,
                "corpus_id": corpus_id,
                "doc_id": doc_id,
                "chunks": inserted,
            },
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.error(f"ingest_knowledge: 工具执行失败 | error={exc}", exc_info=True)
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)


from .utils.search_engine import TIME_SENSITIVE_KEYWORDS  # noqa: E402


def needs_search(message: str) -> bool:
    """兼容旧 tests：基于旧关键词策略判断是否需要外部搜索。"""
    from .utils.search_engine import should_search

    return should_search(message)


def extract_images(message: Any, max_images: int = 10):
    """兼容旧 tests：从消息中提取图片 URL。"""
    from .utils.image_processor import extract_images as _extract

    return _extract(message, max_images=max_images)
