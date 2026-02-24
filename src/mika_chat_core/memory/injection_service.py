"""Memory/knowledge injection and extraction services.

从 MikaClient 抽离的业务逻辑服务：不持有运行时状态，通过依赖注入复用原有行为。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from ..infra.logging import logger as log
from ..utils.prompt_context import update_prompt_context


async def inject_memory_retrieval_context(
    *,
    message: str,
    user_id: str,
    group_id: Optional[str],
    request_id: str,
    system_injection: Optional[str],
    plugin_cfg: Any,
    resolve_model_for_task: Callable[[str, Optional[Dict[str, Any]]], str],
    memory_session_key: Callable[[str, Optional[str]], str],
    retrieval_agent_getter: Callable[[], Any],
) -> Optional[str]:
    """ReAct 多源记忆检索注入。"""
    if not bool(getattr(plugin_cfg, "mika_memory_retrieval_enabled", False)):
        update_prompt_context({"retrieval_context": ""})
        return system_injection

    try:
        llm_cfg = plugin_cfg.get_llm_config()
        model = resolve_model_for_task("memory", llm_cfg=llm_cfg)
        if not model:
            update_prompt_context({"retrieval_context": ""})
            return system_injection

        session_key = memory_session_key(user_id, group_id)
        min_similarity = float(getattr(plugin_cfg, "mika_memory_min_similarity", 0.5) or 0.5)
        retrieval_text = await retrieval_agent_getter().retrieve(
            question=message,
            session_key=session_key,
            user_id=str(user_id or ""),
            group_id=group_id,
            llm_cfg=llm_cfg,
            model=model,
            max_iterations=int(
                getattr(plugin_cfg, "mika_memory_retrieval_max_iterations", 3) or 3
            ),
            timeout_seconds=float(
                getattr(plugin_cfg, "mika_memory_retrieval_timeout", 15.0) or 15.0
            ),
            min_similarity=min_similarity,
            default_corpus=str(
                getattr(plugin_cfg, "mika_knowledge_default_corpus", "default") or "default"
            ),
        )
        retrieval_text = str(retrieval_text or "").strip()
        if not retrieval_text:
            update_prompt_context({"retrieval_context": ""})
            return system_injection

        update_prompt_context({"retrieval_context": retrieval_text})
        context_text = "[多源记忆检索结果]\n" + retrieval_text
        log.info(f"[req:{request_id}] ReAct 记忆检索命中 | session={session_key}")
        if system_injection:
            return f"{system_injection}\n\n{context_text}"
        return context_text
    except Exception as exc:
        log.warning(f"[req:{request_id}] ReAct 记忆检索失败: {exc}")
        update_prompt_context({"retrieval_context": ""})
        return system_injection


async def inject_long_term_memory(
    *,
    message: str,
    user_id: str,
    group_id: Optional[str],
    request_id: str,
    system_injection: Optional[str],
    plugin_cfg: Any,
    memory_session_key: Callable[[str, Optional[str]], str],
) -> Optional[str]:
    """检索长期记忆并注入 system_injection。"""
    if not getattr(plugin_cfg, "mika_memory_enabled", False):
        update_prompt_context({"memory_snippets": ""})
        return system_injection

    try:
        from mika_chat_core.utils.memory_store import get_memory_store
        from mika_chat_core.utils.semantic_matcher import semantic_matcher

        memory_store = get_memory_store()
        await memory_store.init_table()
        query_embedding = semantic_matcher.encode(message)
        if query_embedding is None:
            update_prompt_context({"memory_snippets": ""})
            return system_injection

        session_key = memory_session_key(user_id, group_id)
        memories = await memory_store.search(
            query_embedding,
            session_key=session_key,
            top_k=int(getattr(plugin_cfg, "mika_memory_search_top_k", 5) or 5),
            min_similarity=float(
                getattr(plugin_cfg, "mika_memory_min_similarity", 0.5) or 0.5
            ),
        )
        if not memories:
            update_prompt_context({"memory_snippets": ""})
            return system_injection

        memory_lines = [f"- {entry.fact}" for entry, _ in memories if entry.fact.strip()]
        if not memory_lines:
            update_prompt_context({"memory_snippets": ""})
            return system_injection

        memory_text = "[你记得的相关信息（长期记忆）]\n" + "\n".join(memory_lines)
        update_prompt_context({"memory_snippets": "\n".join(memory_lines)})
        for entry, _ in memories:
            await memory_store.update_recall(entry.id)
        top_score = memories[0][1] if memories else 0.0
        log.info(f"[req:{request_id}] 长期记忆命中 {len(memories)} 条 | top_score={top_score:.3f}")

        if system_injection:
            return f"{system_injection}\n\n{memory_text}"
        return memory_text
    except Exception as exc:
        log.warning(f"[req:{request_id}] 长期记忆检索失败: {exc}")
        update_prompt_context({"memory_snippets": ""})
        return system_injection


async def inject_knowledge_context(
    *,
    message: str,
    user_id: str,
    group_id: Optional[str],
    request_id: str,
    system_injection: Optional[str],
    plugin_cfg: Any,
    memory_session_key: Callable[[str, Optional[str]], str],
) -> Optional[str]:
    """检索知识库并自动注入 system（可选开启）。"""
    if not bool(getattr(plugin_cfg, "mika_knowledge_enabled", False)):
        update_prompt_context({"knowledge_context": ""})
        return system_injection
    if not bool(getattr(plugin_cfg, "mika_knowledge_auto_inject", False)):
        update_prompt_context({"knowledge_context": ""})
        return system_injection

    try:
        from mika_chat_core.utils.knowledge_store import get_knowledge_store
        from mika_chat_core.utils.semantic_matcher import semantic_matcher

        query_embedding = semantic_matcher.encode(message)
        if query_embedding is None:
            update_prompt_context({"knowledge_context": ""})
            return system_injection

        store = get_knowledge_store()
        await store.init_table()

        session_key = memory_session_key(user_id, group_id)
        corpus_id = str(
            getattr(plugin_cfg, "mika_knowledge_default_corpus", "default") or "default"
        )
        top_k = max(
            1,
            min(
                int(getattr(plugin_cfg, "mika_knowledge_auto_inject_top_k", 3) or 3),
                10,
            ),
        )
        min_similarity = float(
            getattr(plugin_cfg, "mika_knowledge_min_similarity", 0.5) or 0.5
        )
        results = await store.search(
            query_embedding,
            corpus_id=corpus_id,
            session_key=session_key,
            top_k=top_k,
            min_similarity=min_similarity,
        )
        if not results:
            update_prompt_context({"knowledge_context": ""})
            return system_injection

        lines: List[str] = []
        for entry, score in results:
            snippet = str(entry.content or "").replace("\n", " ").strip()
            if len(snippet) > 260:
                snippet = snippet[:260] + "..."
            title = entry.title or entry.doc_id
            lines.append(f"- ({score:.3f}) [{title}] {snippet}")
            await store.update_recall(entry.id)

        knowledge_text = (
            "[Knowledge Context | Retrieved]\n"
            "以下是从本地知识库检索到的相关片段，可作为事实参考：\n"
            + "\n".join(lines)
        )
        update_prompt_context({"knowledge_context": "\n".join(lines)})
        log.info(f"[req:{request_id}] 知识库自动注入命中 {len(results)} 条")
        if system_injection:
            return f"{system_injection}\n\n{knowledge_text}"
        return knowledge_text
    except Exception as exc:
        log.warning(f"[req:{request_id}] 知识库自动注入失败: {exc}")
        update_prompt_context({"knowledge_context": ""})
        return system_injection


async def extract_and_store_memories(
    *,
    messages: List[Dict[str, Any]],
    user_id: str,
    group_id: Optional[str],
    request_id: str,
    plugin_cfg: Any,
    resolve_model_for_task: Callable[[str, Optional[Dict[str, Any]]], str],
    memory_session_key: Callable[[str, Optional[str]], str],
) -> None:
    """后台提取并存储长期记忆。"""
    try:
        from mika_chat_core.utils.memory_extractor import MemoryExtractor
        from mika_chat_core.utils.memory_store import get_memory_store
        from mika_chat_core.utils.semantic_matcher import semantic_matcher

        llm_cfg = plugin_cfg.get_llm_config()
        api_keys = list(llm_cfg.get("api_keys") or [])
        if not api_keys:
            return

        model = resolve_model_for_task("memory", llm_cfg=llm_cfg)
        if not model:
            return

        extractor = MemoryExtractor()
        facts = await extractor.extract(
            messages,
            api_key=str(api_keys[0] or ""),
            base_url=str(llm_cfg.get("base_url") or ""),
            model=model,
            provider=str(llm_cfg.get("provider") or "openai_compat"),
            extra_headers=dict(llm_cfg.get("extra_headers") or {}),
            max_facts=int(
                getattr(plugin_cfg, "mika_memory_max_facts_per_extract", 5) or 5
            ),
        )
        if not facts:
            return

        memory_store = get_memory_store()
        await memory_store.init_table()
        session_key = memory_session_key(user_id, group_id)
        stored = 0
        for fact_user_id, fact_text in facts:
            text = str(fact_text or "").strip()
            if not text:
                continue
            embedding = semantic_matcher.encode(text)
            if embedding is None:
                continue
            memory_user_id = str(fact_user_id or "").strip()
            if not memory_user_id or memory_user_id == "unknown":
                memory_user_id = str(user_id or "")
            memory_id = await memory_store.add_memory(
                session_key=session_key,
                user_id=memory_user_id,
                fact=text,
                embedding=embedding,
                source="extract",
            )
            if memory_id:
                stored += 1
        if stored:
            log.info(f"[req:{request_id}] 长期记忆提取成功 | stored={stored}/{len(facts)}")
    except Exception as exc:
        log.warning(f"[req:{request_id}] 长期记忆提取失败: {exc}")


async def run_topic_summary(
    *,
    session_key: str,
    messages: List[Dict[str, Any]],
    llm_cfg: Dict[str, Any],
    request_id: str,
    plugin_cfg: Any,
    chat_history_summarizer: Any,
    resolve_model_for_task: Callable[[str, Optional[Dict[str, Any]]], str],
) -> None:
    """后台执行话题化摘要。"""
    if chat_history_summarizer is None:
        return
    try:
        model = resolve_model_for_task("summarizer", llm_cfg=llm_cfg)
        if not model:
            return
        stored = await chat_history_summarizer.maybe_summarize(
            session_key=session_key,
            messages=messages,
            llm_cfg=llm_cfg,
            model=model,
            batch_size=int(getattr(plugin_cfg, "mika_topic_summary_batch", 25) or 25),
            request_id=request_id,
        )
        if stored > 0:
            log.info(
                f"[req:{request_id}] 话题摘要更新完成 | session={session_key} | topics={stored}"
            )
    except Exception as exc:
        log.warning(f"[req:{request_id}] 话题摘要后台任务失败: {exc}")

