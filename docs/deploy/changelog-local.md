# 本地部署变更记录（Private）

本文档用于记录 `bot` 私有部署仓的关键变更，方便后续排障、回滚和交接。

## 2026-02-07

### `b1179e1`
**主题**：移除“WSL2 长期守护默认方案”导向  
**核心变化**：
- 文档口径改为：WSL2 仅作为可选运行环境
- 不再把 `systemd` / 开机自启当默认路径
- 保留 `.env.prod` 优先检查与现有启动逻辑

### `8c4521c`
**主题**：安装与部署文档简化  
**核心变化**：
- README 与文档入口术语统一
- 新手流程更聚焦“能快速启动”
- 降低对复杂运维背景的依赖

### `23dc65e`
**主题**：替换旧 WSL2 运维模板，改为本地开箱工具  
**核心变化**：
- 新增 `scripts/bootstrap.py`（初始化环境）
- 新增 `scripts/config_wizard.py`（交互式配置）
- 新增 `scripts/doctor.py`（启动前自检）
- 新增 `start.bat`（Windows 调起 WSL 启动入口）
- 更新 `start.ps1`（更偏本机启动与配置检查）
- 删除 `deploy/wsl2/*` 下旧 `systemd`/守护模板

## 当前推荐运行路径

### 首次初始化
```bash
python scripts/bootstrap.py
python scripts/doctor.py
python bot.py
```

### 日常运行
- Linux / WSL：`./start.sh` 或 `python bot.py`
- Windows：`start.ps1` 或 `python bot.py`

## 维护约定
- 私有敏感信息（如 `.env.prod`）不进入公开仓
- 开发改动先在公开开发仓验证，再按白名单同步到私有部署仓
- 每次影响部署行为的变更，追加一条记录到本文件
