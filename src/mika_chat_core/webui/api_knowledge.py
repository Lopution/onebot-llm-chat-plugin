"""WebUI knowledge APIs."""

from __future__ import annotations

import hashlib
from typing import Any, Callable, Dict, List

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..config import Config
from ..runtime import get_config as get_runtime_config
from ..utils.knowledge_chunker import split_text_chunks
from ..utils.knowledge_store import get_knowledge_store
from ..utils.semantic_matcher import semantic_matcher
from .auth import create_webui_auth_dependency
from .base_route import BaseRouteHelper


class KnowledgeIngestPayload(BaseModel):
    corpus_id: str = "default"
    doc_id: str | None = None
    title: str = ""
    source: str = ""
    content: str = Field(min_length=1)
    tags: List[str] = Field(default_factory=list)
    session_key: str = ""


def create_knowledge_router(
    *,
    settings_getter: Callable[[], Config] = get_runtime_config,
) -> APIRouter:
    auth_dependency = create_webui_auth_dependency(settings_getter=settings_getter)
    router = APIRouter(
        prefix="/knowledge",
        tags=["mika-webui-knowledge"],
        dependencies=[Depends(auth_dependency)],
    )

    @router.get("/corpora")
    async def list_corpora() -> Dict[str, Any]:
        store = get_knowledge_store()
        await store.init_table()
        return BaseRouteHelper.ok(await store.list_corpora())

    @router.get("/documents")
    async def list_documents(corpus_id: str | None = None) -> Dict[str, Any]:
        cfg = settings_getter()
        resolved_corpus = str(
            corpus_id or getattr(cfg, "mika_knowledge_default_corpus", "default") or "default"
        )
        store = get_knowledge_store()
        await store.init_table()
        return BaseRouteHelper.ok(await store.list_documents(resolved_corpus))

    @router.get("/documents/{doc_id}/chunks")
    async def list_document_chunks(doc_id: str, corpus_id: str | None = None) -> Dict[str, Any]:
        if not str(doc_id or "").strip():
            return BaseRouteHelper.error_response("doc_id is required")
        cfg = settings_getter()
        resolved_corpus = str(
            corpus_id or getattr(cfg, "mika_knowledge_default_corpus", "default") or "default"
        )
        store = get_knowledge_store()
        await store.init_table()
        return BaseRouteHelper.ok(await store.list_chunks(resolved_corpus, str(doc_id).strip()))

    @router.post("/ingest")
    async def ingest_document(payload: KnowledgeIngestPayload):
        cfg = settings_getter()
        if not bool(getattr(cfg, "mika_knowledge_enabled", False)):
            return BaseRouteHelper.error_response("knowledge is disabled")

        content = str(payload.content or "").strip()
        if not content:
            return BaseRouteHelper.error_response("content is required")
        if len(content) > 120000:
            return BaseRouteHelper.error_response("content is too large")

        corpus_id = str(payload.corpus_id or "").strip() or str(
            getattr(cfg, "mika_knowledge_default_corpus", "default") or "default"
        )
        doc_id = str(payload.doc_id or "").strip()
        if not doc_id:
            doc_id = f"doc_{hashlib.sha1(content.encode('utf-8')).hexdigest()[:16]}"

        chunks = split_text_chunks(
            content,
            max_chars=int(getattr(cfg, "mika_knowledge_chunk_max_chars", 450) or 450),
            overlap_chars=int(getattr(cfg, "mika_knowledge_chunk_overlap_chars", 80) or 80),
        )
        if not chunks:
            return BaseRouteHelper.error_response("empty chunks")

        embeddings = semantic_matcher.encode_batch(chunks)
        if not embeddings or len(embeddings) != len(chunks):
            return BaseRouteHelper.error_response("embedding failed", status_code=500)

        store = get_knowledge_store()
        await store.init_table()
        inserted = await store.upsert_document(
            corpus_id=corpus_id,
            doc_id=doc_id,
            chunks=chunks,
            embeddings=embeddings,
            title=str(payload.title or "").strip(),
            source=str(payload.source or "").strip(),
            tags=payload.tags,
            session_key=str(payload.session_key or "").strip(),
        )
        return BaseRouteHelper.ok(
            {
                "ok": inserted > 0,
                "corpus_id": corpus_id,
                "doc_id": doc_id,
                "chunks": inserted,
            }
        )

    @router.delete("/documents/{doc_id}")
    async def delete_document(doc_id: str, corpus_id: str | None = None):
        if not str(doc_id or "").strip():
            return BaseRouteHelper.error_response("doc_id is required")
        cfg = settings_getter()
        resolved_corpus = str(
            corpus_id or getattr(cfg, "mika_knowledge_default_corpus", "default") or "default"
        )
        store = get_knowledge_store()
        await store.init_table()
        deleted = await store.delete_document(corpus_id=resolved_corpus, doc_id=str(doc_id).strip())
        return BaseRouteHelper.ok({"ok": True, "deleted": int(deleted)})

    return router


__all__ = ["KnowledgeIngestPayload", "create_knowledge_router"]
