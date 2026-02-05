# WSL2 + NapCat 长期运行部署（systemd）

适用场景：你在 Windows 本机部署，但希望 Bot 与 NapCat 都运行在 WSL2 中，并做到“开机自动拉起 + 异常自动重启”。

## 关键端口与连接方式（本仓库默认）

- Bot：`0.0.0.0:8080`（见 `bot.py`）
- NapCat（Docker）WebUI：默认 `6099`（见 `napcat/config/webui.json` 或 `napcat/data/webui.json`）
- NapCat → Bot：OneBot v11 WebSocket Client  
  本仓库示例配置为 `ws://172.17.0.1:8080/onebot/v11/ws`（见 `napcat/data/onebot11_*.json`）

> `172.17.0.1` 是 Docker 默认 bridge 网络下“容器访问宿主机”的常用网关地址；如果你的 Docker 网络模式不同，需改成可达的地址（例如 `host.docker.internal` 或直接使用宿主机 IP）。

## 1) 建议的目录与数据位置

强烈建议把项目放在 WSL 的 ext4 文件系统里（例如 `/root/bot` 或 `/home/<user>/bot`），不要放在 `/mnt/c/...`，SQLite 性能与锁竞争会差很多。

本项目数据库默认落在：

- `bot/data/gemini_chat/contexts.db`（可用 `GEMINI_DATA_DIR` 或 `GEMINI_CONTEXT_DB_PATH` 覆盖）

## 低内存建议（项目侧）

如果你不关心性能，但希望 **尽可能少吃内存**，建议优先用“语义后端替换”来降内存（功能尽量不受影响），其次才是直接关功能。

### 方案 A：保留语义功能，但显著降内存（推荐：fastembed）

语义匹配默认使用 `sentence-transformers + torch`，在 WSL2 长期运行时常驻内存会比较大。

本项目已支持 `fastembed` 后端（通常更省内存，CPU 推理；首次会下载/缓存模型）：

1) 安装依赖（在 venv 内，二选一）：

```bash
pip install fastembed
# 或者
pip install -e ".[semantic]"
```

2) 把语义配置切到 fastembed（示例：多语 MiniLM，覆盖中/日/英）：

```env
GEMINI_SEMANTIC_BACKEND=fastembed
GEMINI_SEMANTIC_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
GEMINI_SEMANTIC_MODEL_FALLBACK=/root/bot/models/semantic_model
GEMINI_SEMANTIC_USE_E5_PREFIXES=false
```

> 注意：`fastembed.TextEmbedding` **不支持** `intfloat/multilingual-e5-small`（可用 `TextEmbedding.list_supported_models()` 验证）。  
> 如果你想继续用本地目录模型（例如 `/root/bot/models/semantic_model`），建议保持 `GEMINI_SEMANTIC_BACKEND=sentence-transformers`（或 `auto`）。

> 如果你当前 `GEMINI_SEMANTIC_MODEL` 配的是本地目录（例如 `/root/bot/models/semantic_model`），那更适合继续用 `sentence-transformers`。

如果你遇到下载失败（例如 systemd 下无法访问 HuggingFace）：

- 你也可以手动下载并离线放置 fastembed 模型文件，然后配置 `GEMINI_FASTEMBED_MODEL_DIR` 直接从本地加载（不走任何下载逻辑）
- 在 `.env` / `.env.prod` 里配置 `HTTP_PROXY/HTTPS_PROXY`（或 `HF_ENDPOINT` 镜像地址），再重启服务
- 重新安装 systemd unit 并重启：

```bash
sudo /root/bot/deploy/wsl2/install-systemd.sh
sudo systemctl restart mika-bot.service
```

### 方案 B：直接关功能换内存（极限省内存）

如果你只需要 Bot 正常跑起来、**不在乎性能/功能完整性**，可以通过配置进一步降低内存占用（尤其是关闭语义模型）：

- 关闭语义模型（最大头）：`GEMINI_SEMANTIC_ENABLED=false`
- 关闭“非关键词”主动发言通道：`GEMINI_PROACTIVE_RATE=0`
- （可选）关闭用户档案 LLM 抽取：`PROFILE_EXTRACT_ENABLED=false`
- （可选）关闭历史图片增强：`GEMINI_HISTORY_IMAGE_MODE=off`

> 说明：语义模型依赖 `torch/sentence-transformers`，加载后会长期占用较多内存；关闭后，主动发言只剩关键词触发或完全关闭。

如果你使用 systemd 部署（`mika-bot.service`），建议把这些开关直接写进 `.env.prod`（或你自己的环境文件）即可。

## Windows 侧：限制 WSL2 内存（推荐）

WSL2 的 `VmmemWSL` 会把 Linux 页缓存也算在内存占用里，长期运行/大量 I/O 后“看起来吃满”是常见现象。

如果你只求稳定运行 Bot、并尽量少吃内存，推荐在 Windows 用户目录创建/修改 `~/.wslconfig`
（例如 `C:\\Users\\<你>\\.wslconfig`），加入类似配置：

```ini
[wsl2]
memory=6GB
processors=2
swap=0

# 需要较新 WSL 版本才支持（不支持则忽略这一行）
autoMemoryReclaim=dropcache
```

然后执行一次让配置生效：

```powershell
wsl --shutdown
```

## 2) 启用 WSL2 的 systemd

在 WSL2 发行版内执行：

1. 编辑 `/etc/wsl.conf`：

```ini
[boot]
systemd=true
```

2. 在 Windows 里重启 WSL：

```powershell
wsl --shutdown
```

然后重新打开该 distro。

## 3) 安装 systemd 服务（模板）

本仓库提供了服务模板与安装脚本：

- `deploy/wsl2/systemd/napcat.service`
- `deploy/wsl2/systemd/mika-bot.service`
- `deploy/wsl2/install-systemd.sh`

如果你的目录不是 `/root/bot` 与 `/root/napcat`：

- 先编辑 `deploy/wsl2/systemd/*.service` 里的路径（`MIKA_BOT_DIR` / `NAPCAT_DIR` / `EnvironmentFile` / `ExecStart` / `WorkingDirectory`）。

安装（需要 root）：

```bash
sudo /root/bot/deploy/wsl2/install-systemd.sh
```

安装后常用命令：

```bash
systemctl status mika-bot.service
systemctl status napcat.service
journalctl -u mika-bot.service -f
```

### NapCat 启动脚本做了什么

`napcat.service` 调用 `deploy/wsl2/bin/napcat-up.sh`，它会：

- 等待 Docker 可用（默认最多 180 秒，可用 `DOCKER_WAIT_TIMEOUT_SECONDS` 覆盖）
- 自动把 `napcat/data/onebot11_*.json` 的 `network.websocketClients[].url` 指向 Docker bridge 网关（获取失败时回退 `172.17.0.1`）

## 4) Windows 开机自动启动 WSL 并拉起服务

提供了 PowerShell 脚本模板：

- `deploy/wsl2/windows/start-wsl-services.ps1`

用法（在 Windows PowerShell 里）：

```powershell
.\start-wsl-services.ps1 -DistroName "Ubuntu-22.04" -DelaySeconds 45
```

你需要把它配置进“任务计划程序”（开机/登录触发）。

> 发行版名称用 `wsl -l -v` 查看。

## 5) NapCat 首次登录（扫码）说明

NapCat 容器首次登录/掉线后通常需要扫码，你可以用：

```bash
docker logs -f napcat
```

来查看二维码与登录状态。  
`systemd` 只负责“拉起进程与重启”，不会替你完成扫码。
