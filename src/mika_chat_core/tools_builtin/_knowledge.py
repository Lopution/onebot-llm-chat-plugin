"""知识库工具（检索 + 写入）。"""

from __future__ import annotations

import json

from ..infra.logging import logger
from ..runtime import get_config as get_runtime_config
from ..tools import tool


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
    from ..config import Config
    from ..utils.knowledge_store import get_knowledge_store
    from ..utils.semantic_matcher import semantic_matcher

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

    from ..config import Config
    from ..utils.knowledge_chunker import split_text_chunks
    from ..utils.knowledge_store import get_knowledge_store
    from ..utils.semantic_matcher import semantic_matcher

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
