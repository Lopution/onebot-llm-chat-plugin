
import asyncio
import sys
from pathlib import Path

# 添加 src 到路径以模拟 Bot 环境
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src" / "plugins"))

# 模拟 NoneBot 驱动
class MockDriver:
    def on_startup(self, func): return func
    def on_shutdown(self, func): return func

import nonebot
nonebot.get_driver = lambda: MockDriver()

from mika_chat_core.utils.context_store import init_database, close_database

async def main():
    print("正在初始化数据库表结构...")
    await init_database()
    await close_database()
    print("完成！")

if __name__ == "__main__":
    asyncio.run(main())
