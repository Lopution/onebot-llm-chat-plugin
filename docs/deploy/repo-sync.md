# 双仓同步流程（开发仓 -> 部署仓）

这份文档用于固定一个简单规则：

- 开发主仓：`/root/onebot-llm-chat-plugin`
- 本地部署仓：`/root/bot`

核心原则：先在开发仓改好并验证，再把“允许同步的文件”复制到部署仓。

## 为什么要双仓

1. 开发仓用于迭代与开源，不带你的本机私有配置。  
2. 部署仓用于本机运行，允许有你自己的环境与数据。  
3. 出问题时更容易回滚，不会把线上环境和开发环境绑死。

## 同步前必须做的 3 件事

1. 在开发仓跑测试：`pytest -q`。  
2. 确认改动不含密钥、账号、机器路径。  
3. 只同步白名单文件（见下文）。

## 白名单（可同步）

- `src/nonebot_plugin_mika_chat/`
- `src/mika_chat_core/`
- `tests/`
- `README.md`
- `README_EN.md`
- `docs/deploy/onebot.md`
- `docs/deploy/repo-sync.md`
- `.env.example`
- `pyproject.toml`
- `requirements.txt`

## 黑名单（禁止同步）

以下内容只应留在本机部署仓：

- `.env.prod`
- `data/`
- `models/`
- `logs/`
- `.venv/`

## 推荐同步步骤（通俗版）

1. 在开发仓确认本次改动：`git status`。  
2. 按白名单把文件复制到部署仓。  
3. 在部署仓做一次最小验证：
   - `python3 scripts/doctor.py`
   - `python3 bot.py`（或你已有启动脚本）
4. 确认日志正常：
   - OneBot 已连接
   - 私聊/群聊能正常收发
   - 没有新的启动异常
5. 验证通过后按你当前习惯启动（例如 `start.sh`、`start.ps1` 或 `python bot.py`）。

## 出问题怎么回滚

1. 先把部署仓回到上一个稳定提交。  
2. 记录问题信息（时间、日志、复现步骤）。  
3. 回到开发仓修复后，再按本流程同步一次。
