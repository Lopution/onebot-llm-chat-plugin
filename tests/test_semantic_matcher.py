"""semantic_matcher 单元测试。"""

from __future__ import annotations

from unittest.mock import patch

from mika_chat_core.utils.semantic_matcher import SemanticMatcher, _semantic_backend_for_model


class TestBackendSelection:
    """_semantic_backend_for_model 后端选择逻辑。"""

    def test_auto_with_fastembed_available(self):
        with patch("mika_chat_core.utils.semantic_matcher._load_fastembed_deps", return_value=True):
            with patch("mika_chat_core.utils.semantic_matcher.plugin_config") as cfg:
                cfg.mika_semantic_backend = "auto"
                assert _semantic_backend_for_model("BAAI/bge-small-zh-v1.5") == "fastembed"

    def test_auto_without_fastembed(self):
        with patch("mika_chat_core.utils.semantic_matcher._load_fastembed_deps", return_value=False):
            with patch("mika_chat_core.utils.semantic_matcher.plugin_config") as cfg:
                cfg.mika_semantic_backend = "auto"
                assert _semantic_backend_for_model("any-model") == "none"

    def test_explicit_fastembed(self):
        with patch("mika_chat_core.utils.semantic_matcher._load_fastembed_deps", return_value=True):
            with patch("mika_chat_core.utils.semantic_matcher.plugin_config") as cfg:
                cfg.mika_semantic_backend = "fastembed"
                assert _semantic_backend_for_model("any") == "fastembed"

    def test_sentence_transformers_falls_back_to_none(self):
        with patch("mika_chat_core.utils.semantic_matcher._load_fastembed_deps", return_value=True):
            with patch("mika_chat_core.utils.semantic_matcher.plugin_config") as cfg:
                cfg.mika_semantic_backend = "sentence_transformers"
                assert _semantic_backend_for_model("any") == "none"


class TestCheckSimilarityDisabled:
    """语义匹配禁用时安全降级。"""

    def test_returns_false_when_disabled(self):
        matcher = SemanticMatcher.__new__(SemanticMatcher)
        matcher._model = None
        matcher._topic_embeddings = {}
        matcher._backend = None
        with patch("mika_chat_core.utils.semantic_matcher.plugin_config") as cfg:
            cfg.mika_semantic_enabled = False
            result = matcher.check_similarity("任何文本")
            assert result == (False, "", 0.0)

    def test_returns_false_when_no_model(self):
        matcher = SemanticMatcher.__new__(SemanticMatcher)
        matcher._model = None
        matcher._topic_embeddings = {}
        matcher._backend = None
        with patch("mika_chat_core.utils.semantic_matcher.plugin_config") as cfg:
            cfg.mika_semantic_enabled = True
            cfg.mika_memory_enabled = False
            cfg.mika_proactive_topics = []
            cfg.mika_proactive_rate = 0.0
            result = matcher.check_similarity("test")
            assert result == (False, "", 0.0)


class TestEncode:
    """encode() 和 encode_batch() 方法。"""

    def test_encode_returns_none_when_no_model(self):
        matcher = SemanticMatcher.__new__(SemanticMatcher)
        matcher._model = None
        matcher._backend = None
        matcher._topic_embeddings = {}
        with patch("mika_chat_core.utils.semantic_matcher.plugin_config") as cfg:
            cfg.mika_semantic_enabled = True
            cfg.mika_memory_enabled = False
            cfg.mika_proactive_topics = []
            cfg.mika_proactive_rate = 0.0
            assert matcher.encode("hello") is None

    def test_encode_batch_returns_empty_when_no_model(self):
        matcher = SemanticMatcher.__new__(SemanticMatcher)
        matcher._model = None
        matcher._backend = None
        matcher._topic_embeddings = {}
        with patch("mika_chat_core.utils.semantic_matcher.plugin_config") as cfg:
            cfg.mika_semantic_enabled = True
            cfg.mika_memory_enabled = False
            cfg.mika_proactive_topics = []
            cfg.mika_proactive_rate = 0.0
            assert matcher.encode_batch(["hello", "world"]) == []
