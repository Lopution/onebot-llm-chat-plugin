# 常见问题排错

本页只描述“当前代码真实行为”，不依赖过时 README/计划文档。

## 1) 启动失败：提示旧键 / 校验错误

现象：
- 启动时报 `ValidationError`，错误里包含 `MIKA_API_KEY` / `SERPER_API_KEY` 等旧键
- 或 `start.sh` / `scripts/doctor.py` 明确提示“旧键已移除”

原因：
- 本项目已切断旧键兼容。旧键存在即 fail-fast（不会静默迁移）。

处理：
1. 删除旧键（从 `.env` / `.env.prod` 里移除）
2. 改用新键：
   - `MIKA_API_KEY` -> `LLM_API_KEY`
   - `SERPER_API_KEY` -> `SEARCH_API_KEY`
3. 运行自检：

```bash
python3 scripts/doctor.py
```

迁移清单见：[`upgrade.md`](upgrade.md)。

## 2) WebUI 打不开 / 403 / 401

现象：
- 403：`webui token is required for non-loopback access`
- 401：`invalid webui token`

原因：
- `MIKA_WEBUI_TOKEN` 为空时只允许本机（loopback）访问。
- token 不匹配会直接 401。

处理：
- 本机访问：用 `http://127.0.0.1:<PORT><MIKA_WEBUI_BASE_PATH>/`
- 远程访问：设置 `MIKA_WEBUI_TOKEN`，并用请求头携带 token。

## 3) “请求成功(HTTP 200)但回复是空/报错”

现象：
- 日志里显示请求完成，但 bot 发出“发生了错误/抱歉我这次没有成功生成有效回复”
- 日志可能包含 `empty_fingerprint`、`provider_empty`、`content=None`

常见原因：
1. 上游/中转站返回了空内容（content 为 `null`），但 HTTP 状态仍为 200。
2. 上游不支持某些能力（tools/images/response_format），导致响应异常或被网关吞掉。
3. 请求体过大（尤其是群聊多图 + base64），上游返回了空内容或网关兜底文案。

建议排查顺序：
1. 先换模型/渠道验证（同一个 prompt 下对比 `LLM_MODEL`）。
2. 明确能力开关（对中转站尤其重要）：
   - `MIKA_LLM_SUPPORTS_IMAGES=true/false`
   - `MIKA_LLM_SUPPORTS_TOOLS=true/false`
3. 若你启用了 caption：
   - `MIKA_MEDIA_CAPTION_ENABLED=true`
   - 确保 caption provider 真的“能看图”（否则会记录 warning 并降级为占位符）。

## 4) 群聊“越聊越容易坏”/疑似上下文爆了

现象：
- 群聊前几条还能回，后面越来越容易空回复或错误
- `context_trace` 里 `history_count/total_chars` 很大

原因（常见）：
- 群聊消息量大，累计上下文过长；再叠加图片 base64 时，请求体会快速膨胀。

处理建议（优先级从高到低）：
1. 限制请求体大小（对中转站更友好）：
   - `MIKA_REQUEST_BODY_MAX_BYTES=1800000`（默认 1.8MB）
2. 限制 transcript 每行长度：
   - `MIKA_CHATROOM_TRANSCRIPT_LINE_MAX_CHARS=240`（默认 240）
3. 检查是否把“原图(base64)”塞进了主请求：
   - 推荐以 `caption` 为主，必要时才附带原图。

## 5) 工具不怎么调用 / 调用不稳定

现象：
- 模型很少触发 tool_calls
- 或一触发就失败（上游报 tools 不支持）

处理：
1. 明确上游是否支持 tools：
   - 不支持就设置 `MIKA_LLM_SUPPORTS_TOOLS=false`
2. 观察日志中工具链路（tool start/end、结果长度等），必要时先降低工具数量与复杂度。

## 6) 搜索不工作 / 没有结果

现象：
- 日志里显示搜索失败或返回 0 条

处理：
- 确认已配置：
  - `SEARCH_PROVIDER=serper|tavily`
  - `SEARCH_API_KEY="..."`
- 若你处于代理环境，检查 `HTTP_PROXY/HTTPS_PROXY/NO_PROXY`。

## 7) 离线同步一直跳过

现象：
- `离线同步跳过：平台未返回历史记录`

原因：
- 离线同步依赖 OneBot 实现的非标准接口（例如 `get_group_msg_history`），不是所有实现都提供或默认开启。

处理：
- 先确认你的 OneBot 实现是否支持并已启用对应接口。
- 若不支持，建议关闭离线同步（默认就是关闭）：`MIKA_OFFLINE_SYNC_ENABLED=false`。

## 8) `fastembed not available, semantic disabled`

现象：
- 日志提示：`fastembed not available, semantic disabled`

说明：
- 这是可选依赖。缺失时语义匹配会自动关闭，但不影响基础对话。

