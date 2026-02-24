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
        if _imports_host_packages(py_file):
            violating_paths.append(rel)

    assert violating_paths == [], (
        "mika_chat_core 不应直接导入宿主框架依赖，请迁移到适配层: "
        + ", ".join(sorted(violating_paths))
    )
