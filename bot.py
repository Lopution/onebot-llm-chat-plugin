"""项目入口（模板仓库）。

目标：开箱即用
- 不硬编码 HOST/PORT：完全由 `.env` / `.env.prod` 控制
- OneBot v11/v12 适配器 best-effort 注册：用户只装其一也能跑
"""

import nonebot

nonebot.init()

driver = nonebot.get_driver()

# 尽量加载 localstore（用于跨平台统一 data/cache 目录）
try:
    nonebot.load_plugin("nonebot_plugin_localstore")
except Exception:
    pass

# best-effort 注册 OneBot v11/v12
try:
    from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter

    driver.register_adapter(OneBotV11Adapter)
except Exception:
    pass

try:
    from nonebot.adapters.onebot.v12 import Adapter as OneBotV12Adapter

    driver.register_adapter(OneBotV12Adapter)
except Exception:
    pass

nonebot.load_plugins("src/plugins")

if __name__ == "__main__":
    # HOST/PORT 由 NoneBot 配置加载（默认读取 .env / .env.prod）
    nonebot.run()
