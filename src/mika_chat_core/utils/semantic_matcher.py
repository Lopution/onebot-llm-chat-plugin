"""语义匹配模块（fastembed + ONNX Runtime）。

提供轻量级 embedding 语义匹配能力：
- 仅使用 fastembed（无 torch / sentence-transformers）
- 依赖缺失时安全降级（不影响主流程）
- 支持主动发言主题匹配与长期记忆向量编码
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from ..config import plugin_config
from ..infra.logging import logger as log


_HAS_FASTEMBED_DEPS: Optional[bool] = None
_FASTEMBED_IMPORT_ERROR: Optional[Exception] = None
_FastembedTextEmbedding: Any = None
_np: Any = None


def _load_numpy() -> Any:
    global _np
    if _np is not None:
        return _np
    import numpy as np  # type: ignore

    _np = np
    return np


def _load_fastembed_deps() -> bool:
    """按需加载 fastembed。"""
    global _HAS_FASTEMBED_DEPS, _FASTEMBED_IMPORT_ERROR, _FastembedTextEmbedding

    if _HAS_FASTEMBED_DEPS is True:
        return True
    if _HAS_FASTEMBED_DEPS is False:
        return False

    try:
        from fastembed import TextEmbedding  # type: ignore

        _FastembedTextEmbedding = TextEmbedding
        _HAS_FASTEMBED_DEPS = True
        return True
    except Exception as exc:  # pragma: no cover
        _HAS_FASTEMBED_DEPS = False
        _FASTEMBED_IMPORT_ERROR = exc
        _FastembedTextEmbedding = None
        return False


def _semantic_backend_for_model(model_name: str) -> str:
    """根据配置选择后端。去除 torch 后只有 fastembed 一条路径。"""
    del model_name
    backend = getattr(plugin_config, "mika_semantic_backend", "auto") or "auto"
    backend = str(backend).strip().lower()
    if backend in {"auto", "fastembed"}:
        return "fastembed" if _load_fastembed_deps() else "none"
    return "none"


def _use_e5_prefixes() -> bool:
    try:
        return bool(getattr(plugin_config, "mika_semantic_use_e5_prefixes", True))
    except Exception:
        return True


def _semantic_required() -> bool:
    if not getattr(plugin_config, "mika_semantic_enabled", True):
        return False

    memory_enabled = bool(getattr(plugin_config, "mika_memory_enabled", False))
    knowledge_enabled = bool(getattr(plugin_config, "mika_knowledge_enabled", False))
    proactive_topics = list(getattr(plugin_config, "mika_proactive_topics", []) or [])
    proactive_rate = float(getattr(plugin_config, "mika_proactive_rate", 0.0) or 0.0)
    return memory_enabled or knowledge_enabled or (bool(proactive_topics) and proactive_rate > 0)


class SemanticMatcher:
    _instance = None
    _model = None
    _topic_embeddings: Dict[str, object] = {}
    _backend: Optional[str] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SemanticMatcher, cls).__new__(cls)
        return cls._instance

    def load_model(self) -> None:
        """显式加载语义模型（fastembed-only）。"""
        if not _semantic_required():
            return
        if self._model is not None:
            return

        model_name = str(getattr(plugin_config, "mika_semantic_model", "") or "").strip()
        if not model_name:
            return

        backend = _semantic_backend_for_model(model_name)
        if backend == "none":
            return
        self._backend = backend

        log.info(f"[SemanticMatcher] Backend: {backend}")
        log.info(f"[SemanticMatcher] Loading model: {model_name}...")

        try:
            cache_dir = getattr(plugin_config, "mika_fastembed_cache_dir", "") or None
            specific_model_path = getattr(plugin_config, "mika_fastembed_model_dir", "") or None

            kwargs: dict[str, Any] = {"model_name": model_name}
            if cache_dir:
                kwargs["cache_dir"] = cache_dir
            if specific_model_path:
                kwargs["specific_model_path"] = specific_model_path
                kwargs["local_files_only"] = True

            try:
                self._model = _FastembedTextEmbedding(**kwargs)  # type: ignore[misc]
            except (TypeError, ValueError):
                onnx_path = getattr(plugin_config, "mika_semantic_onnx_path", "") or ""
                if onnx_path:
                    import os

                    if not os.path.isdir(onnx_path):
                        raise ValueError(f"ONNX path does not exist: {onnx_path}")
                    local_kwargs: dict[str, Any] = {
                        "model_name": model_name,
                        "specific_model_path": onnx_path,
                        "local_files_only": True,
                    }
                    if cache_dir:
                        local_kwargs["cache_dir"] = cache_dir
                    self._model = _FastembedTextEmbedding(**local_kwargs)  # type: ignore[misc]
                else:
                    self._model = _FastembedTextEmbedding(model_name)  # type: ignore[misc]

            log.success("[SemanticMatcher] Model loaded successfully.")
            self._encode_topics()
        except Exception as exc:
            log.error(f"[SemanticMatcher] Failed to load model: {exc}")
            self._model = None
            self._backend = None

    def _encode_topics(self) -> None:
        if not self._model or not self._backend:
            return
        topics = list(getattr(plugin_config, "mika_proactive_topics", []) or [])
        if not topics:
            self._topic_embeddings = {}
            return

        log.info(f"[SemanticMatcher] Encoding {len(topics)} topics...")
        prefixed_topics = [("passage: " + t) if _use_e5_prefixes() else t for t in topics]
        embeddings = list(self._model.embed(prefixed_topics))
        self._topic_embeddings = {topic: emb for topic, emb in zip(topics, embeddings)}
        log.debug("[SemanticMatcher] Topics encoded.")

    def check_similarity(self, text: str, threshold: float = None) -> Tuple[bool, str, float]:
        """检查文本与配置 topics 的语义相似度。"""
        if not getattr(plugin_config, "mika_semantic_enabled", True):
            return False, "", 0.0

        if self._model is None:
            self.load_model()
            if self._model is None:
                return False, "", 0.0

        if not text or not self._topic_embeddings:
            return False, "", 0.0

        query = ("query: " + text) if _use_e5_prefixes() else text
        text_embedding = next(iter(self._model.embed([query])))

        np = _load_numpy()
        q_vec = np.asarray(text_embedding, dtype=np.float32)
        q_norm = float(np.linalg.norm(q_vec) or 1.0)

        best_topic = ""
        best_score = -1.0
        for topic, emb in self._topic_embeddings.items():
            vec = np.asarray(emb, dtype=np.float32)
            vec_norm = float(np.linalg.norm(vec) or 1.0)
            score = float(np.dot(q_vec, vec) / (q_norm * vec_norm))
            if score > best_score:
                best_score = score
                best_topic = topic

        final_threshold = threshold if threshold is not None else plugin_config.mika_semantic_threshold
        if best_score >= final_threshold:
            log.debug(f"[SemanticMatcher] Match: '{text}' ~ '{best_topic}' (score={best_score:.3f})")
            return True, best_topic, best_score
        return False, "", best_score

    def encode(self, text: str) -> Any:
        """将文本编码为向量。模型未加载或禁用时返回 None。"""
        if not text:
            return None
        if not getattr(plugin_config, "mika_semantic_enabled", True):
            return None
        if self._model is None:
            self.load_model()
            if self._model is None:
                return None
        query = ("query: " + text) if _use_e5_prefixes() else text
        np = _load_numpy()
        return np.asarray(next(iter(self._model.embed([query]))), dtype=np.float32)

    def encode_batch(self, texts: list[str]) -> list[Any]:
        """批量编码。模型未加载或禁用时返回空列表。"""
        if not texts:
            return []
        if not getattr(plugin_config, "mika_semantic_enabled", True):
            return []
        if self._model is None:
            self.load_model()
            if self._model is None:
                return []
        prefix = _use_e5_prefixes()
        queries = [("query: " + text) if prefix else text for text in texts]
        np = _load_numpy()
        return [np.asarray(emb, dtype=np.float32) for emb in self._model.embed(queries)]


semantic_matcher = SemanticMatcher()


async def init_semantic_matcher() -> None:
    """初始化语义匹配器并后台加载模型。"""
    if not getattr(plugin_config, "mika_semantic_enabled", True):
        log.info("[SemanticMatcher] Disabled by config (mika_semantic_enabled=false)")
        return

    if not _semantic_required():
        log.info("[SemanticMatcher] Semantic model not required by current feature flags")
        return

    model_name = str(getattr(plugin_config, "mika_semantic_model", "") or "").strip()
    backend = _semantic_backend_for_model(model_name)
    if backend == "none":
        log.warning(f"[SemanticMatcher] fastembed not available, semantic disabled: {_FASTEMBED_IMPORT_ERROR}")
        return

    log.info("Initializing Semantic Matcher...")
    try:
        import asyncio

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, semantic_matcher.load_model)
    except Exception as exc:
        log.error(f"Failed to initialize semantic matcher: {exc}")
