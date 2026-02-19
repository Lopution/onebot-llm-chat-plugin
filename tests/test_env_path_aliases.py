from __future__ import annotations

from pathlib import Path


def test_get_data_root_prefers_mika_data_dir(monkeypatch):
    from mika_chat_core.infra.paths import get_data_root

    monkeypatch.setenv("MIKA_DATA_DIR", "/tmp/mika-data")

    assert get_data_root("mika_chat") == Path("/tmp/mika-data/mika_chat")


def test_get_data_root_falls_back_to_project_default_when_env_missing(monkeypatch):
    from mika_chat_core.infra.paths import get_data_root

    monkeypatch.delenv("MIKA_DATA_DIR", raising=False)

    assert str(get_data_root("mika_chat")).endswith("/data/mika_chat")


def test_context_db_path_prefers_mika_context_db_path(monkeypatch):
    from mika_chat_core.utils import context_db

    monkeypatch.setenv("MIKA_CONTEXT_DB_PATH", "/tmp/mika-contexts.db")
    context_db.set_db_path(None)

    assert context_db.get_db_path() == Path("/tmp/mika-contexts.db")


def test_context_db_path_falls_back_to_mika_data_dir(monkeypatch):
    from mika_chat_core.utils import context_db

    monkeypatch.delenv("MIKA_CONTEXT_DB_PATH", raising=False)
    monkeypatch.setenv("MIKA_DATA_DIR", "/tmp/mika-data")
    context_db.set_db_path(None)

    assert context_db.get_db_path() == Path("/tmp/mika-data/mika_chat/contexts.db")


def test_image_cache_dir_prefers_mika_image_cache_dir(monkeypatch):
    from mika_chat_core.utils.image_processor import _get_default_cache_dir

    monkeypatch.setenv("MIKA_IMAGE_CACHE_DIR", "/tmp/mika-image-cache")

    assert _get_default_cache_dir() == Path("/tmp/mika-image-cache")
