# 双仓同步流程（开发仓 → 部署仓）

本文档用于固定以下工作流：

- 开发主仓：`/root/mika-chat-core`（或你的实际 `<PROJECT_DIR>`）
- 部署镜像仓：`/root/bot`

## 目标

1. 开发与发布职责分离，避免把部署私有配置带入开源仓。  
2. 保证每次同步都有可复现步骤与回滚点。  
3. 降低“开发仓与部署仓行为不一致”的概率。

## 同步前检查（必须）

1. 在开发仓执行并通过：
   - `pytest -q`
2. 确认改动范围只包含允许同步的文件（见下文白名单）。
3. 确认没有把本机密钥、路径、账号信息写入代码或文档。

## 文件同步白名单

建议仅同步以下路径（按需）：

- `src/nonebot_plugin_mika_chat/`
- `src/nonebot_plugin_gemini_chat/`（兼容壳，过渡期）
- `tests/`
- `README.md`
- `README_EN.md`
- `docs/deploy/onebot.md`
- `docs/deploy/repo-sync.md`
- `.env.example`
- `pyproject.toml`
- `requirements.txt`

## 文件同步黑名单（禁止）

以下内容只允许留在部署仓本机，不得回流开源仓：

- `.env.prod`
- `data/`
- `models/`
- `logs/`
- `.venv/`

## 推荐同步步骤

1. 在开发仓记录提交：
   - `git status`
   - `git log --oneline -n 5`
2. 按白名单复制文件到部署仓。
3. 在部署仓执行：
   - `pytest -q`（如部署仓保留完整测试环境）
   - 或至少运行一次启动冒烟（`python bot.py` / 现有启动脚本）
4. 部署仓验证通过后再重启服务：
   - `systemctl restart mika-bot.service`（如使用 systemd）
5. 观察关键日志：
   - 启动无类型告警（`Unknown parameter` / `ForwardRef`）
   - OneBot 连接成功
   - 私聊/群聊收发正常

## 回滚策略

若同步后出现异常：

1. 在部署仓回退到上一稳定提交。
2. 记录故障提交号、复现输入、日志指纹（request_id/response_id）。
3. 在开发仓修复后重新执行同步流程。
