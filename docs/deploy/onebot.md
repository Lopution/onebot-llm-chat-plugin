# OneBot v11 / v12 兼容性说明

本项目希望尽可能兼容不同的 OneBot 实现（NapCat / go-cqhttp / 其它实现，以及 OneBot v12 适配器）。
因此在一些**非标准/可选**能力上采用 **best-effort + 自动降级**：能用就用，不能用就回退为更通用的行为，保证 Bot 稳定运行。

## 推荐部署方式

- 方案 A：Linux/Windows 本机 + 任意 OneBot 实现（无 Docker）
- 方案 B：WSL2 + 任意 OneBot 实现（可选 Docker）

## 最短启动路径（开箱即用）

如果你是第一次部署，推荐先用项目自带脚本完成环境准备：

```bash
python3 scripts/bootstrap.py
python3 scripts/doctor.py
python3 bot.py
```

Windows 等价命令：

```powershell
python scripts\bootstrap.py
python scripts\doctor.py
python bot.py
```

> 如果你已经有稳定的运行方式（如 `start.sh` / `start.ps1`），可以继续沿用。

## Prompt 配置（V2）

当前默认角色提示词文件为 `system.yaml`（`prompts/` 目录下），由 `MIKA_PROMPT_FILE` 指定。  
Prompt V2 仅要求：

```yaml
name: "角色名"
character_prompt: |
  角色定义自由文本
```

可选字段：
- `dialogue_examples`（few-shot 示例）
- `error_messages`（错误提示模板）

旧结构化字段（`role/personality/instructions/...`）与旧 `system_prompt` 字段已不再作为正式 schema。

## 模块说明

- 中立核心模块：`mika_chat_core`
- 当前 NoneBot 适配层：`nonebot_plugin_mika_chat`

当前版本默认由 NoneBot 加载 `nonebot_plugin_mika_chat`，并调用 `mika_chat_core` 内的核心能力：

```python
nonebot.load_plugin("nonebot_plugin_mika_chat")
```

> 说明：NoneBot 是当前默认宿主，不是唯一方向。后续可基于 `mika_chat_core` 增加其它宿主适配层。

### 已有 NoneBot 宿主时（最短接入）

如果你已经有自己的 NoneBot2 项目，不需要使用本仓库的 `bot.py`：

```bash
pip install -e .
```

然后在宿主入口加载：

```python
nonebot.load_plugin("nonebot_plugin_mika_chat")
```

## 如何连接到 Bot（反向 WebSocket）

Bot 启动后，需要在你的 OneBot 实现/客户端侧配置“反向 WebSocket（WS Client）”，连接到 Bot 的 WS 地址：

- **OneBot v11**：`ws://<HOST>:<PORT>/onebot/v11/ws`
- **OneBot v12**：`ws://<HOST>:<PORT>/onebot/v12/ws`

其中 `<HOST>/<PORT>` 对应你的 `.env` 配置（默认 `0.0.0.0:8080`）。

### NapCat（OneBot v11）最小配置示例

NapCat 通常会把 OneBot v11 配置放在挂载目录里（例如 `napcat/data/onebot11_<你的QQ号>.json`）。
只要确保存在 WebSocket Client，并指向上面的 v11 地址即可：

```json
{
  "network": {
    "websocketClients": [
      {
        "name": "mika-bot",
        "enable": true,
        "url": "ws://<HOST>:<PORT>/onebot/v11/ws"
      }
    ]
  }
}
```

> 提示：如果 NapCat 跑在 Docker 里，而 Bot 跑在宿主机/WSL2 中，`<HOST>` 可能需要写宿主机网关 IP（例如 `172.17.0.1`），而不是 `127.0.0.1`。

## 关键差异（v11 vs v12）

### 1) `@` 提及（mention）
- **v11**：消息段 `type="at"`，目标 ID 在 `data["qq"]`
- **v12**：消息段 `type="mention"`，目标 ID 在 `data["user_id"]`

插件会在以下位置兼容两种段类型：
- `@` 检测（触发群聊回复）
- 群聊消息解析（把 `@xxx` 还原成文本，避免模型误解“谁被提到”）

### 2) 引用/回复（reply）
- **v11**：`reply` 段通常使用 `data["id"]`
- **v12**：`reply` 段通常使用 `data["message_id"]`

插件会在解析时 **优先取 `id`，否则取 `message_id`**，并尝试 best-effort 拉取被引用消息内容（如果适配器不支持相关 API，会自动跳过，不影响主流程）。

### 3) 图片（image）
- **v11**：`image` 段通常直接提供 `data["url"]`（http/https）
- **v12**：`image` 段可能只提供 `data["file_id"]`，不一定有 `url`

插件策略：
1. 优先使用消息段中已提供的 `url`/`file`（仅接受 http/https）。
2. 若仅有 `file_id`：会尝试调用 OneBot v12 的 `get_file`（best-effort）获取可下载 `url`。
3. 若无法解析：不会报错，只会把图片当作 `[图片]` 占位处理，确保 Bot 正常运行。

### 4) ID 类型
- **v11**：`group_id/user_id` 常为 `int`
- **v12**：`group_id/user_id` 常为 `str`

插件内部统一转成字符串处理，并保持上下文存储 key 不变：
- 群聊：`group:{group_id}`
- 私聊：`private:{user_id}`

这意味着你不需要迁移历史数据库；v11/v12 只要群号一致即可复用同一份上下文。

### 5) 结构化上下文（增强图片/工具连续理解）
- 默认启用 `MIKA_CONTEXT_MODE=structured`
- 上下文按“轮次优先 + 软 token 阈值”裁剪，避免只按条数粗截断导致语义断裂
- 工具调用轨迹会写入会话历史，减少多轮工具场景“失忆”问题
- 当模型/平台不支持对应多模态能力时，`MIKA_MULTIMODAL_STRICT=true` 会自动清洗不合法块，优先保证可用性

## 兼容策略（best-effort + 降级）

### 1) 发送策略：短消息引用，长消息 Forward
- 短消息：优先走引用回复（Quote）
- 长消息：优先尝试合并转发（Forward）

Forward 调用的典型 API：
- `send_group_forward_msg`
- `send_private_forward_msg`

若 Forward 或引用发送失败，会自动回退到“渲染图片并引用发送”；若图片发送仍失败，再回退为“单条纯文本引用发送”。
  
`MIKA_LONG_MESSAGE_CHUNK_SIZE` 当前仅作为兼容保留，不再是默认主链路兜底。

### 2) 引用回复（Quote）优先，但不强依赖
优先使用：
- `bot.send(event, text, reply_message=True, at_sender=False)`

若适配器不支持该参数/失败，则降级为普通发送：
- `bot.send(event, text)`

### 3) 工具：群历史查询改为读本地 SQLite 上下文
`search_group_history` 工具不再依赖远端历史 API（不同实现差异很大），而是读取本地 SQLite 上下文：
- 优点：跨实现一致、离线可用
- 注意：只能检索“Bot 记住的上下文范围内”的历史

### 4) 离线同步（可选，默认关闭）
离线消息同步通常依赖 `get_group_msg_history`，属于**并非所有实现都支持**的 API。

因此插件默认关闭离线同步：
- `MIKA_OFFLINE_SYNC_ENABLED=false`

如果你的实现支持该 API，并且确实需要离线同步，可以手动开启：
- `MIKA_OFFLINE_SYNC_ENABLED=true`

开启后仍是 best-effort：某个群同步失败会跳过，不影响 Bot 上线与其它群的处理。

## 可观测性端点

- `GET /health`：返回数据库状态、客户端状态，以及可选的 API 主动探测结果。  
- `GET /metrics`：默认返回 JSON 指标快照；当 `Accept: text/plain` 或 `?format=prometheus` 时，可返回 Prometheus 文本（需启用 `MIKA_METRICS_PROMETHEUS_ENABLED=true`）。  
- `GET /metrics/prometheus`：固定返回 Prometheus 文本格式（若禁用会返回 404）。

可选开关（默认保守）：
- `MIKA_METRICS_PROMETHEUS_ENABLED=true`
- `MIKA_HEALTH_CHECK_API_PROBE_ENABLED=false`
- `MIKA_HEALTH_CHECK_API_PROBE_TIMEOUT_SECONDS=3.0`
- `MIKA_HEALTH_CHECK_API_PROBE_TTL_SECONDS=30`

## 常见排错

### “图片解析不到 / 只显示 `[图片]`”
说明当前适配器/实现没有给出可下载的图片 URL，且 `get_file` 无法获取到 `url`（或被网络/权限拦截）。
这不会影响 Bot 正常回复，只是多模态能力降级。

### “合并转发失败”
不同实现对 Forward 支持差异较大；失败后插件会自动降级为“图片引用 -> 单条文本引用”。

若你希望关闭图片兜底，可设置：
- `MIKA_LONG_REPLY_IMAGE_FALLBACK_ENABLED=false`

### “API 经常空回复，且反复重试”
P0 之后默认策略是“传输层先收敛，业务层不盲重试”：
- `MIKA_EMPTY_REPLY_LOCAL_RETRIES=1`
- `MIKA_EMPTY_REPLY_LOCAL_RETRY_DELAY_SECONDS=0.4`
- `MIKA_TRANSPORT_TIMEOUT_RETRIES=1`
- `MIKA_TRANSPORT_TIMEOUT_RETRY_DELAY_SECONDS=0.6`
- `MIKA_EMPTY_REPLY_CONTEXT_DEGRADE_ENABLED=false`

若你确认不是网络/上游问题，才建议临时开启业务级上下文降级：
- `MIKA_EMPTY_REPLY_CONTEXT_DEGRADE_ENABLED=true`
- `MIKA_EMPTY_REPLY_CONTEXT_DEGRADE_MAX_LEVEL=2`

### “想要排查上下文构建是否异常”
可临时开启上下文 trace：
- `MIKA_CONTEXT_TRACE_ENABLED=true`
- `MIKA_CONTEXT_TRACE_SAMPLE_RATE=1.0`

在线上环境建议将采样率降到 0.1 或更低，避免日志过量。

### “主动发言在某些群太频繁/不希望触发”
可使用主动回复门控：
- `MIKA_ACTIVE_REPLY_LTM_ENABLED=true`
- `MIKA_ACTIVE_REPLY_PROBABILITY=0.3`
- `MIKA_ACTIVE_REPLY_WHITELIST=["123456789"]`

其中 `MIKA_ACTIVE_REPLY_WHITELIST` 留空表示不额外限制群范围（仍受主白名单与原有 proactive 规则控制）。
