"""NoneBot 运行时类型别名。

目的：
- 避免在 matcher / driver hook 注解中使用 `typing.Any`，触发 NoneBot 依赖解析告警。
- 提供稳定导入路径，兼容不同 NoneBot 版本的类型暴露位置。
"""

from __future__ import annotations

# 优先使用公开导出；失败时按“旧路径 -> 测试 stub -> 最终兜底”回退。
try:  # pragma: no cover - 运行时分支
    from nonebot.adapters import Bot as BotT  # type: ignore
    from nonebot.adapters import Event as EventT  # type: ignore
except Exception:  # pragma: no cover - 版本兼容分支
    try:
        from nonebot.internal.adapter import Bot as BotT  # type: ignore
        from nonebot.internal.adapter import Event as EventT  # type: ignore
    except Exception:  # pragma: no cover - tests/stubs 分支
        try:
            from nonebot.adapters.onebot.v11 import Bot as BotT  # type: ignore
            from nonebot.adapters.onebot.v11 import GroupMessageEvent as EventT  # type: ignore
        except Exception:  # pragma: no cover - 极端兜底，避免导入期崩溃
            class BotT:  # type: ignore[no-redef]
                pass

            class EventT:  # type: ignore[no-redef]
                pass
