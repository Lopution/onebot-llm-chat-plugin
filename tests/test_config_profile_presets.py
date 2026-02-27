import pytest


def test_agentic_profile_applies_defaults(valid_api_key: str):
    from mika_chat_core.config import Config

    cfg = Config(
        llm_api_key=valid_api_key,
        mika_master_id=123456789,
        mika_profile="agentic",
    )

    assert cfg.mika_memory_retrieval_enabled is True
    assert cfg.mika_knowledge_enabled is True
    assert cfg.mika_knowledge_auto_inject is True
    assert cfg.mika_planner_mode == "llm"


def test_profile_does_not_override_explicit_fields(valid_api_key: str):
    from mika_chat_core.config import Config

    cfg = Config(
        llm_api_key=valid_api_key,
        mika_master_id=123456789,
        mika_profile="agentic",
        mika_memory_retrieval_enabled=False,
    )

    assert cfg.mika_memory_retrieval_enabled is False


def test_dev_profile_enables_context_trace(valid_api_key: str):
    from mika_chat_core.config import Config

    cfg = Config(
        llm_api_key=valid_api_key,
        mika_master_id=123456789,
        mika_profile="dev",
    )

    assert cfg.mika_context_trace_enabled is True
    assert cfg.mika_context_trace_sample_rate == 1.0


def test_stable_profile_does_not_override_explicit_planner_mode(valid_api_key: str):
    from mika_chat_core.config import Config

    cfg = Config(
        llm_api_key=valid_api_key,
        mika_master_id=123456789,
        mika_profile="stable",
        mika_planner_mode="llm",
    )

    assert cfg.mika_planner_mode == "llm"

