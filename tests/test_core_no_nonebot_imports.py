from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CORE_ROOT = PROJECT_ROOT / "src" / "mika_chat_core"


HOST_IMPORT_PREFIXES = (
    "nonebot",
    "nonebot_plugin",
    "nonebot_plugin_localstore",
)


ALLOWED_HOST_IMPORT_PATHS = {
    "src/mika_chat_core/deps.py",
    "src/mika_chat_core/lifecycle.py",
    "src/mika_chat_core/matchers.py",
    "src/mika_chat_core/tools.py",
    "src/mika_chat_core/utils/nb_types.py",
}


def _is_host_import(module_name: str) -> bool:
    return any(
        module_name == prefix or module_name.startswith(f"{prefix}.")
        for prefix in HOST_IMPORT_PREFIXES
    )


def _imports_host_packages(py_file: Path) -> bool:
    tree = ast.parse(py_file.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_host_import(alias.name):
                    return True
        if isinstance(node, ast.ImportFrom) and node.module:
            if _is_host_import(node.module):
                return True
    return False


def test_core_host_imports_are_whitelisted():
    violating_paths: list[str] = []
    for py_file in CORE_ROOT.rglob("*.py"):
        rel = py_file.relative_to(PROJECT_ROOT).as_posix()
        if _imports_host_packages(py_file) and rel not in ALLOWED_HOST_IMPORT_PATHS:
            violating_paths.append(rel)

    assert violating_paths == [], (
        "mika_chat_core 新增了未登记的宿主依赖，请迁移到适配层或更新白名单: "
        + ", ".join(sorted(violating_paths))
    )
