"""语义匹配模块（可选依赖）。

提供基于 embedding 的语义相似度匹配功能：
- 支持 fastembed（轻量级，推荐）或 sentence-transformers（本地模型）
- 依赖缺失时安全降级（不影响主流程）
- 用于检测相似问题、重复内容等场景

注意：
- fastembed / torch / sentence_transformers 缺失时不会在 import 阶段崩溃
- `init_semantic_matcher()` 在缺依赖时降级为 no-op
- 调用 `check_similarity()` 安全返回 `(False, "", 0.0)`
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from nonebot import logger as log

from ..config import plugin_config


# 可选重依赖采用 lazy import：
# - fastembed：通常更省内存（CPU 推理），适合长期运行
# - sentence-transformers/torch：兼容本地目录模型，但常驻内存更高
_HAS_FASTEMBED_DEPS: Optional[bool] = None
_FASTEMBED_IMPORT_ERROR: Optional[Exception] = None
_FastembedTextEmbedding: Any = None

_HAS_SEMANTIC_DEPS: Optional[bool] = None
_DEPS_IMPORT_ERROR: Optional[Exception] = None
_torch: Any = None
_SentenceTransformer: Any = None
_util: Any = None
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
    except Exception as e:  # pragma: no cover
        _HAS_FASTEMBED_DEPS = False
        _FASTEMBED_IMPORT_ERROR = e
        _FastembedTextEmbedding = None
        return False


def _load_semantic_deps() -> bool:
    """按需加载 torch / sentence_transformers（兼容旧调用）。"""
    return _load_sentence_transformers_deps()


def _load_sentence_transformers_deps() -> bool:
    """按需加载 torch / sentence_transformers。

    Returns:
        True if deps are available, False otherwise.
    """
    global _HAS_SEMANTIC_DEPS, _DEPS_IMPORT_ERROR, _torch, _SentenceTransformer, _util

    if _HAS_SEMANTIC_DEPS is True:
        return True
    if _HAS_SEMANTIC_DEPS is False:
        return False

    try:
        import torch as torch_mod  # type: ignore
        from sentence_transformers import SentenceTransformer as ST  # type: ignore
        from sentence_transformers import util as util_mod  # type: ignore

        _torch = torch_mod
        _SentenceTransformer = ST
        _util = util_mod
        _HAS_SEMANTIC_DEPS = True
        return True
    except Exception as e:  # pragma: no cover
        # 依赖缺失或环境不兼容（如 glibc/CPU 指令集问题）都视为“不可用”。
        _HAS_SEMANTIC_DEPS = False
        _DEPS_IMPORT_ERROR = e
        _torch = None
        _SentenceTransformer = None
        _util = None
        return False


def _semantic_backend_for_model(model_name: str) -> str:
    """根据配置与模型形态选择后端。"""
    backend = getattr(plugin_config, "gemini_semantic_backend", "auto") or "auto"
    backend = str(backend).strip().lower()
    if backend == "sentence-transformers":
        backend = "sentence_transformers"

    if backend not in {"auto", "fastembed", "sentence_transformers"}:
        backend = "auto"

    if backend == "auto":
        # 本地路径（目录/文件）通常更适配 sentence-transformers
        try:
            import os

            looks_like_path = os.path.isdir(model_name) or os.path.isfile(model_name)
        except Exception:
            looks_like_path = False

        if looks_like_path:
            if _load_sentence_transformers_deps():
                return "sentence_transformers"
            if _load_fastembed_deps():
                return "fastembed"
            return "none"

        # 否则优先 fastembed（更省内存），失败再回退 ST
        if _load_fastembed_deps():
            return "fastembed"
        if _load_sentence_transformers_deps():
            return "sentence_transformers"
        return "none"

    if backend == "fastembed":
        return "fastembed" if _load_fastembed_deps() else "none"
    if backend == "sentence_transformers":
        return "sentence_transformers" if _load_sentence_transformers_deps() else "none"
    return "none"


def _get_semantic_model_fallback() -> str:
    try:
        fallback = getattr(plugin_config, "gemini_semantic_model_fallback", "") or ""
        return str(fallback).strip()
    except Exception:
        return ""

def _use_e5_prefixes() -> bool:
    try:
        return bool(getattr(plugin_config, "gemini_semantic_use_e5_prefixes", True))
    except Exception:
        return True


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
        """显式加载语义模型。

        依赖缺失时：直接返回，不抛异常。
        """
        # 允许通过配置关闭语义匹配以降低资源占用
        if not getattr(plugin_config, "gemini_semantic_enabled", True):
            return

        # 当前语义匹配仅用于主动发言 topic 相似度判断：
        # - 未配置 topics 时无需加载模型
        # - proactive_rate=0 时语义通道永远不会触发，避免无意义加载
        if not getattr(plugin_config, "gemini_proactive_topics", None):
            return
        if getattr(plugin_config, "gemini_proactive_rate", 0.0) <= 0:
            return

        if self._model is None:
            model_name = plugin_config.gemini_semantic_model
            backend = _semantic_backend_for_model(model_name)
            if backend == "none":
                return

            self._backend = backend
            log.info(f"[SemanticMatcher] Backend: {backend}")
            log.info(f"[SemanticMatcher] Loading model: {model_name}...")

            # 如果目录缺 modules.json，可能会反复出现 warning；原逻辑尝试 save 一次。
            should_save = False
            try:
                import os

                if (
                    backend == "sentence_transformers"
                    and os.path.isdir(model_name)
                    and not os.path.exists(os.path.join(model_name, "modules.json"))
                ):
                    should_save = True
            except Exception:
                pass

            try:
                if backend == "fastembed":
                    # fastembed 通常更省内存；首次使用会下载/缓存模型
                    try:
                        cache_dir = getattr(plugin_config, "gemini_fastembed_cache_dir", "") or None
                        specific_model_path = (
                            getattr(plugin_config, "gemini_fastembed_model_dir", "") or None
                        )
                        self._model = _FastembedTextEmbedding(  # type: ignore[misc]
                            model_name=model_name,
                            cache_dir=cache_dir,
                            # 若你手动离线放置模型文件，设置该参数可绕过在线下载
                            specific_model_path=specific_model_path,
                            local_files_only=bool(specific_model_path),
                        )
                    except TypeError:
                        self._model = _FastembedTextEmbedding(model_name)  # type: ignore[misc]
                else:
                    import warnings

                    with warnings.catch_warnings():
                        warnings.filterwarnings(
                            "ignore", category=UserWarning, message=".*incorrect regex pattern.*"
                        )
                        self._model = _SentenceTransformer(model_name)  # type: ignore[misc]

                log.success("[SemanticMatcher] Model loaded successfully.")

                if should_save and backend == "sentence_transformers":
                    try:
                        log.info(
                            "[SemanticMatcher] Saving model configuration to suppress future warnings..."
                        )
                        self._model.save(model_name)
                        log.success("[SemanticMatcher] Model configuration saved.")
                    except Exception as e:
                        log.warning(f"[SemanticMatcher] Failed to save model configuration: {e}")

                self._encode_topics()
            except Exception as e:
                log.error(f"[SemanticMatcher] Failed to load model: {e}")
                self._model = None

                # 回退策略：优先尝试本地 fallback（如果配置），否则在 fastembed 失败时尝试 ST。
                fallback = _get_semantic_model_fallback()
                if fallback and fallback != model_name:
                    try:
                        if _load_sentence_transformers_deps():
                            self._backend = "sentence_transformers"
                            log.warning(
                                f"[SemanticMatcher] Falling back to sentence-transformers model: {fallback}"
                            )
                            self._model = _SentenceTransformer(fallback)  # type: ignore[misc]
                            log.success("[SemanticMatcher] Fallback model loaded successfully.")
                            self._encode_topics()
                            return
                    except Exception as e2:
                        log.error(f"[SemanticMatcher] Fallback model load failed: {e2}")
                        self._model = None

                if backend == "fastembed" and _load_sentence_transformers_deps():
                    try:
                        self._backend = "sentence_transformers"
                        log.warning(
                            "[SemanticMatcher] fastembed load failed; falling back to sentence-transformers"
                        )
                        self._model = _SentenceTransformer(model_name)  # type: ignore[misc]
                        log.success("[SemanticMatcher] Fallback model loaded successfully.")
                        self._encode_topics()
                        return
                    except Exception as e2:
                        log.error(f"[SemanticMatcher] sentence-transformers fallback failed: {e2}")
                        self._model = None

    def _encode_topics(self) -> None:
        if not self._model:
            return
        if not self._backend:
            return

        topics = plugin_config.gemini_proactive_topics
        if not topics:
            return

        log.info(f"[SemanticMatcher] Encoding {len(topics)} topics...")
        prefixed_topics = [("passage: " + t) if _use_e5_prefixes() else t for t in topics]
        if self._backend == "fastembed":
            embeddings = list(self._model.embed(prefixed_topics))
        else:
            embeddings = self._model.encode(prefixed_topics, convert_to_tensor=True)

        self._topic_embeddings = {topic: emb for topic, emb in zip(topics, embeddings)}
        log.debug("[SemanticMatcher] Topics encoded.")

    def check_similarity(self, text: str, threshold: float = None) -> Tuple[bool, str, float]:
        """检查文本与配置 topics 的语义相似度。"""
        if not getattr(plugin_config, "gemini_semantic_enabled", True):
            return False, "", 0.0

        # Auto-load if not loaded (fallback)
        if self._model is None:
            self.load_model()
            if self._model is None:
                return False, "", 0.0

        if not text or not self._topic_embeddings:
            return False, "", 0.0

        # Encode input text (E5: query prefix)
        if self._backend == "fastembed":
            q = ("query: " + text) if _use_e5_prefixes() else text
            text_embedding = next(iter(self._model.embed([q])))
        else:
            q = ("query: " + text) if _use_e5_prefixes() else text
            text_embedding = self._model.encode(q, convert_to_tensor=True)

        topic_names = list(self._topic_embeddings.keys())
        if self._backend == "fastembed":
            np = _load_numpy()
            q = np.asarray(text_embedding, dtype=float)
            q_norm = float(np.linalg.norm(q) or 1.0)
            best_topic = ""
            best_score = -1.0
            for name in topic_names:
                v = np.asarray(self._topic_embeddings[name], dtype=float)
                v_norm = float(np.linalg.norm(v) or 1.0)
                score = float(np.dot(q, v) / (q_norm * v_norm))
                if score > best_score:
                    best_score = score
                    best_topic = name
        else:
            topic_vectors = _torch.stack([self._topic_embeddings[t] for t in topic_names])
            scores = _util.cos_sim(text_embedding, topic_vectors)[0]
            max_score_idx = _torch.argmax(scores).item()
            best_score = float(scores[max_score_idx].item())
            best_topic = topic_names[max_score_idx]

        final_threshold = threshold if threshold is not None else plugin_config.gemini_semantic_threshold
        if best_score >= final_threshold:
            log.debug(
                f"[SemanticMatcher] Match: '{text}' ~ '{best_topic}' (score={best_score:.3f})"
            )
            return True, best_topic, best_score

        return False, "", best_score


# Global instance
semantic_matcher = SemanticMatcher()


async def init_semantic_matcher() -> None:
    """初始化语义匹配器并后台加载模型。

    依赖缺失时：no-op + 日志提示。
    """
    if not getattr(plugin_config, "gemini_semantic_enabled", True):
        log.info("[SemanticMatcher] Disabled by config (gemini_semantic_enabled=false)")
        return

    # 当前语义匹配仅用于主动发言；若 topic 为空或 proactive_rate=0，则不加载模型
    if not getattr(plugin_config, "gemini_proactive_topics", None):
        log.info("[SemanticMatcher] No proactive topics configured; skip loading semantic model")
        return
    if getattr(plugin_config, "gemini_proactive_rate", 0.0) <= 0:
        log.info("[SemanticMatcher] Proactive rate is 0; skip loading semantic model")
        return

    model_name = plugin_config.gemini_semantic_model
    backend = _semantic_backend_for_model(model_name)
    if backend == "none":
        desired = getattr(plugin_config, "gemini_semantic_backend", "auto") or "auto"
        if str(desired).strip().lower() == "fastembed":
            log.warning(f"[SemanticMatcher] fastembed missing, disabled: {_FASTEMBED_IMPORT_ERROR}")
        else:
            log.warning(
                f"[SemanticMatcher] Optional deps missing, disabled: {_FASTEMBED_IMPORT_ERROR or _DEPS_IMPORT_ERROR}"
            )
        return

    log.info("Initializing Semantic Matcher...")
    try:
        import asyncio

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, semantic_matcher.load_model)
    except Exception as e:
        log.error(f"Failed to initialize semantic matcher: {e}")
