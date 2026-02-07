"""Mika Chat Core.

中立核心包（过渡版）：
- 业务实现代码位于本包内
- NoneBot 适配入口位于 `nonebot_plugin_mika_chat`

注意：本包不在 import 时注册任何 NoneBot 生命周期/匹配器副作用。
"""

from .config import Config

__all__ = ["Config"]
