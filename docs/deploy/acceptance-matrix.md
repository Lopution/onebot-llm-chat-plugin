# 跨平台验收矩阵（OneBot 通用）

目标：保证项目在不同平台、不同 OneBot 实现下都能稳定运行，不依赖 Docker、systemd 或特定实现。

## 部署方式

- 方案 A：Linux/Windows 本机 + 任意 OneBot 实现（无 Docker）
- 方案 B：WSL2 + 任意 OneBot 实现（可选 Docker；NapCat 常见）

## 通用前置检查

1. 安装 Python 3.10+
2. 初始化项目（推荐）：
   - Linux/WSL：`python3 scripts/bootstrap.py`
   - Windows：`python scripts\bootstrap.py`
3. 启动前自检（推荐）：
   - Linux/WSL：`python3 scripts/doctor.py`
   - Windows：`python scripts\doctor.py`
4. 启动 Bot：
   - Linux/WSL：`python bot.py`（或 `./start.sh`）
   - Windows：`python bot.py`（或 `start.ps1`）
5. 在 OneBot 实现侧配置反向 WS：
   - v11：`ws://<HOST>:<PORT>/onebot/v11/ws`
   - v12：`ws://<HOST>:<PORT>/onebot/v12/ws`

## 验收场景

### 1) Linux 本机（无 Docker）

- 启动方式：`python bot.py`
- 验收点：
  - 能连接 OneBot（日志出现 bot connected）
  - 私聊与群聊都能回复
  - 图片消息失败时能自动降级，不中断

### 2) Windows 本机（无 WSL）

- 启动方式：`start.ps1` 或 `python bot.py`
- 验收点：
  - 能连接 OneBot
  - 长消息发送策略按顺序执行（引用/forward/图片/文本兜底）
  - 重启后配置不丢失

### 3) WSL2（可选 Docker）

- 启动方式：`./start.sh`（或 `python bot.py`）
- 验收点：
  - WSL2 环境内可正常启动并连接 OneBot
  - 若使用 Docker 客户端，WS 地址可达
  - 日志无 `Unknown parameter`/`ForwardRef` 启动告警

### 4) 协议兼容（v11/v12）

- v11：@ 提及、引用、图片、主动发言均可用
- v12：mention/reply/file_id 场景可用或平滑降级

## 回归清单（每次发布前）

1. `pytest -q` 全绿
2. 手动发一条短文本（引用）
3. 手动发一条长文本（forward 或降级链）
4. 发送一条图片并做引用回复测试
5. 观察 `/health` 与 `/metrics` 正常
