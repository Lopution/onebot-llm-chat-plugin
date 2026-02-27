# 快速开始

> 推荐路径：先用脚本生成最小可运行配置，再用 WebUI 做可视化管理与排障。

## 你需要准备什么

- Python 3.10+
- 一个 OneBot 实现/客户端（例如 NapCat 等），并支持“反向 WebSocket（WS Client）”

## 3 步跑起来（推荐）

1. 克隆并初始化

```bash
git clone https://github.com/Lopution/onebot-llm-chat-plugin.git
cd onebot-llm-chat-plugin
python3 scripts/bootstrap.py
```

2. 填写最小配置（只需要 2 项）

复制 `.env.example` 为 `.env`，至少填这两项：

```env
LLM_API_KEY="YOUR_API_KEY"
MIKA_MASTER_ID=123456789
```

说明：
- `LLM_API_KEY` 与 `LLM_API_KEY_LIST` 二选一即可。
- ⚠️ 旧键（如 `MIKA_API_KEY` / `SERPER_API_KEY`）已移除，存在即启动失败。迁移见：[`upgrade.md`](upgrade.md)。

3. 自检并启动

```bash
python3 scripts/doctor.py
python3 bot.py
```

## 配置 OneBot 连接（反向 WebSocket）

Bot 启动后，在你的 OneBot 实现/客户端侧配置“反向 WebSocket（WS Client）”：

- OneBot v11：`ws://<HOST>:<PORT>/onebot/v11/ws`
- OneBot v12：`ws://<HOST>:<PORT>/onebot/v12/ws`

其中 `<HOST>/<PORT>` 来自你的 `.env`（默认 `0.0.0.0:8080`）。

详细说明见：[`../deploy/onebot.md`](../deploy/onebot.md)

## 下一步

- WebUI 使用：[`webui.md`](webui.md)
- 全量配置参考：[`configuration.md`](configuration.md)
- 常见问题排错：[`troubleshooting.md`](troubleshooting.md)

