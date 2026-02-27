# Mika Bot 文档

本仓库是 `onebot-llm-chat-plugin`：基于 OneBot 协议、通过 OpenAI 兼容格式 API 调用 LLM 的多模态 QQ 聊天机器人插件。

## 快速入口

| 主题 | 入口 |
|------|------|
| 快速开始 | [`guide/quickstart.md`](guide/quickstart.md) |
| 配置参考 | [`guide/configuration.md`](guide/configuration.md) |
| WebUI | [`guide/webui.md`](guide/webui.md) |
| 排错 | [`guide/troubleshooting.md`](guide/troubleshooting.md) |
| 升级（Breaking Changes） | [`guide/upgrade.md`](guide/upgrade.md) |
| 路线图 | [`roadmap.md`](roadmap.md) |

## 最短启动路径（摘要）

```bash
python3 scripts/bootstrap.py
python3 scripts/doctor.py
python3 bot.py
```

最小必填配置（`.env` / `.env.prod`）：

```env
LLM_API_KEY="YOUR_API_KEY"
MIKA_MASTER_ID=123456789
```

⚠️ 旧键（如 `MIKA_API_KEY` / `SERPER_API_KEY`）已移除，存在即启动失败。

## API 参考

- [`api/mika_api.md`](api/mika_api.md)：LLM API 客户端封装
- [`api/handlers.md`](api/handlers.md)：消息处理链路
- [`api/search_engine.md`](api/search_engine.md)：联网搜索
- [`api/context_store.md`](api/context_store.md)：上下文存储
- [`api/config.md`](api/config.md)：配置模块 API 参考

## 许可证

本项目采用 GNU AGPLv3 许可证，详见仓库根目录 `LICENSE`。
