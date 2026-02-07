# WSL2 使用指南（可选）

适用场景：你在 Windows 上运行 OneBot 实现（例如 NapCat），希望把 Bot 放在 WSL2 的 Linux 环境里运行。

本项目仅提供“可选 WSL2 运行”说明，不内置 `systemd` / 开机自启 / 长期守护模板。

## 1) 放置项目目录（重要）

强烈建议把项目放在 WSL 的 Linux 文件系统里（例如 `/home/<user>/mika-chat-core` 或 `/root/mika-chat-core`），不要放在 `/mnt/c/...`，否则 SQLite 性能和文件锁会变差。

下文用 `<PROJECT_DIR>` 表示项目目录。

## 2) 启动 Bot

在 WSL2 里：

```bash
cd <PROJECT_DIR>
./start.sh
# 或
python3 bot.py
```

建议启动前先自检一次：

```bash
python3 scripts/doctor.py
```

配置文件建议：

- 使用 `.env` 或 `.env.prod` 都可以
- 若两者同时存在，`start.sh` 会优先按 `.env.prod` 做检查

## 3) 配置 OneBot 反向 WS

默认 WS 路径：

- OneBot v11: `ws://<HOST>:<PORT>/onebot/v11/ws`
- OneBot v12: `ws://<HOST>:<PORT>/onebot/v12/ws`

其中 `<PORT>` 默认是 `8080`，可在 `.env`/`.env.prod` 里配置 `PORT=xxxx`。

### Windows 侧应该填什么 `<HOST>`？

通常有两种情况：

1) OneBot 实现在 Windows 本机运行（常见：NapCat）

- 优先尝试：`127.0.0.1`
- 如果连不上：在 WSL2 里执行 `hostname -I` 获取 WSL2 的 IP，然后用该 IP

2) OneBot 实现在 Docker 里运行

- 优先尝试：`host.docker.internal`
- 或者使用你环境里的实际可达地址（不同 Docker/网络模式可能不同）

## 4) (可选) 降低内存占用

语义匹配默认可能使用 `sentence-transformers + torch`，内存占用较大。你可以：

- 换后端(更省内存)：`fastembed`
- 或直接关闭语义：`GEMINI_SEMANTIC_ENABLED=false`

fastembed 示例：

```bash
pip install fastembed
```

```env
GEMINI_SEMANTIC_BACKEND=fastembed
GEMINI_SEMANTIC_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
```

如果你是离线/受限网络环境：把模型准备到本地目录，再按配置使用对应的 `*_MODEL_FALLBACK` 或本地路径参数。
