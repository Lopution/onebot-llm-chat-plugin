from __future__ import annotations

import importlib
import importlib.abc
import sys


HOST_MODULE_PREFIXES = (
    "nonebot",
    "nonebot_plugin",
    "nonebot_plugin_localstore",
)


class _BlockHostImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path=None, target=None):  # type: ignore[override]
        if any(
            fullname == prefix or fullname.startswith(f"{prefix}.")
            for prefix in HOST_MODULE_PREFIXES
        ):
            raise ModuleNotFoundError(f"blocked host import during test: {fullname}")
        return None


def test_core_runtime_imports_without_host_packages(monkeypatch):
    blocker = _BlockHostImports()
    monkeypatch.setattr(sys, "meta_path", [blocker, *sys.meta_path])

    removed_modules: dict[str, object] = {}
    for module_name in list(sys.modules):
        if any(
            module_name == prefix or module_name.startswith(f"{prefix}.")
            for prefix in HOST_MODULE_PREFIXES
        ):
            removed_modules[module_name] = sys.modules.pop(module_name)

    # Remove target modules to force a fresh import path.
    for target in (
        "mika_chat_core.infra.paths",
        "mika_chat_core.utils.context_db",
        "mika_chat_core.utils.image_processor",
    ):
        sys.modules.pop(target, None)

    try:
        assert importlib.import_module("mika_chat_core.infra.paths")
        assert importlib.import_module("mika_chat_core.utils.context_db")
        assert importlib.import_module("mika_chat_core.utils.image_processor")
    finally:
        sys.modules.update(removed_modules)

