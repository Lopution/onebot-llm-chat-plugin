"""兼容导入层（旧模块名）。

说明：
- 新主模块：`nonebot_plugin_mika_chat`
- 旧模块名：`nonebot_plugin_gemini_chat`
"""

from importlib import import_module


try:
    _target = import_module("nonebot_plugin_mika_chat")
except ModuleNotFoundError:
    _target = import_module("src.nonebot_plugin_mika_chat")

globals().update(_target.__dict__)
