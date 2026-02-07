"""兼容导入层（历史包名 `gemini_chat`）。

说明：
- 新主模块：`nonebot_plugin_mika_chat`
- 历史包名：`gemini_chat`

本模块会把 `gemini_chat.*` 的导入重定向到新主模块，避免新旧实现并存导致行为分叉。
"""

from importlib import import_module
import sys


def _load_target_module():
    try:
        return import_module("nonebot_plugin_mika_chat")
    except ModuleNotFoundError:
        return import_module("src.nonebot_plugin_mika_chat")


_target = _load_target_module()
_prefix = _target.__name__

# 为已加载子模块建立别名，兼容 `gemini_chat.*` 历史导入路径。
for module_name, module in list(sys.modules.items()):
    if module_name == _prefix or module_name.startswith(f"{_prefix}."):
        alias = module_name.replace(_prefix, __name__, 1)
        sys.modules.setdefault(alias, module)

globals().update(_target.__dict__)
sys.modules[__name__] = _target
