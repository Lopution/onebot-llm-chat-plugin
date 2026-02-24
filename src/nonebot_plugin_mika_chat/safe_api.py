"""OneBot best-effort API helpers.

适配层专用：提供兼容型 call_api/send 包装，失败时优雅降级。
"""

from __future__ import annotations

from typing import Any

from mika_chat_core.infra.logging import logger


async def safe_call_api(bot: Any, api: str, **data: Any) -> Any | None:
    """best-effort 调用 ``bot.call_api``。

    - 适配器不支持 / 调用失败 / 抛异常：返回 None
    - 调用成功：返回原始结果
    """
    if bot is None:
        return None
    call_api = getattr(bot, "call_api", None)
    if not callable(call_api):
        return None
    try:
        return await call_api(api, **data)
    except Exception as exc:
        logger.debug(f"safe_call_api 调用失败 | api={api} | error={exc}")
        return None


async def safe_send(bot: Any, event: Any, message: Any, **kwargs: Any) -> bool:
    """best-effort 发送消息（可选携带 reply/at 等参数）。

    发送策略：
    1) 先尝试 ``bot.send(event, message, **kwargs)``
    2) 若失败再尝试 ``bot.send(event, message)``（去掉 kwargs）
    """
    if bot is None:
        return False
    send = getattr(bot, "send", None)
    if not callable(send):
        return False

    try:
        await send(event, message, **kwargs)
        return True
    except Exception as exc:
        if kwargs:
            logger.debug(f"safe_send 带参数发送失败，尝试降级重试 | error={exc}")
        else:
            logger.debug(f"safe_send 发送失败 | error={exc}")

    try:
        await send(event, message)
        return True
    except Exception as exc:
        logger.debug(f"safe_send 降级发送仍失败 | error={exc}")
        return False
