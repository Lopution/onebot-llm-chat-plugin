"""项目入口（模板仓库）。

目标：开箱即用
- 不硬编码 HOST/PORT：完全由 `.env` / `.env.prod` 控制
- OneBot v11/v12 适配器 best-effort 注册：用户只装其一也能跑
"""

import os

import nonebot

nonebot.init()

driver = nonebot.get_driver()
STRICT_STARTUP = os.getenv("MIKA_STRICT_STARTUP", "0").strip().lower() in {"1", "true", "yes", "on"}


def _handle_optional_error(stage: str, exc: Exception) -> None:
    if STRICT_STARTUP:
        raise exc
    nonebot.logger.warning(
        f"[startup] {stage} 失败，已跳过（可设置 MIKA_STRICT_STARTUP=1 强制失败）| error={exc}"
    )

# 尽量加载 localstore（用于跨平台统一 data/cache 目录）
try:
    nonebot.load_plugin("nonebot_plugin_localstore")
except Exception as exc:
    _handle_optional_error("加载 nonebot_plugin_localstore", exc)

# best-effort 注册 OneBot v11/v12
registered_adapters = 0
try:
    from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter

    driver.register_adapter(OneBotV11Adapter)
    registered_adapters += 1
except Exception as exc:
    _handle_optional_error("注册 OneBot v11 适配器", exc)

try:
    from nonebot.adapters.onebot.v12 import Adapter as OneBotV12Adapter

    driver.register_adapter(OneBotV12Adapter)
    registered_adapters += 1
except Exception as exc:
    _handle_optional_error("注册 OneBot v12 适配器", exc)

if registered_adapters == 0:
    message = "未成功注册任何 OneBot 适配器，Bot 将无法接收协议事件。"
    if STRICT_STARTUP:
        raise RuntimeError(message)
    nonebot.logger.warning(f"[startup] {message}")

nonebot.load_plugins("src/plugins")

if __name__ == "__main__":
    # HOST/PORT 由 NoneBot 配置加载（默认读取 .env / .env.prod）
    nonebot.run()
