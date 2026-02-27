# WebUI 使用指南

WebUI 用于“可视化查看与修改配置、查看日志与运行状态、导出/导入配置备份”等。

## 启用 WebUI

在 `.env` 或 `.env.prod` 中配置：

```env
MIKA_WEBUI_ENABLED=true
# 空=仅允许本机访问；要远程访问必须设置 token
MIKA_WEBUI_TOKEN="CHANGE_ME"
MIKA_WEBUI_BASE_PATH="/webui"
```

说明：
- `MIKA_WEBUI_TOKEN` 为空时，仅允许 loopback（`127.0.0.1/localhost`）访问。
- 远程访问建议使用反向代理并启用 HTTPS，同时设置强随机 token。

## 访问地址

默认情况下（`HOST=0.0.0.0`、`PORT=8080`、`MIKA_WEBUI_BASE_PATH=/webui`）：

- `http://127.0.0.1:8080/webui/`

## 快速配置向导（推荐）

WebUI 顶部提供“快速配置向导”（2-3 步跑起来）：

1. LLM：`LLM_PROVIDER / LLM_BASE_URL / LLM_API_KEY(or list) / LLM_MODEL / LLM_FAST_MODEL`
2. 身份：`MIKA_MASTER_ID / MIKA_MASTER_NAME / MIKA_BOT_DISPLAY_NAME`
3. 可选：联网搜索 `SEARCH_PROVIDER / SEARCH_API_KEY`
4. 可选：WebUI 安全 `MIKA_WEBUI_TOKEN`

保存后通常需要重启进程才能完全生效（取决于具体配置项与宿主加载方式）。

## 基础/高级与搜索

WebUI 配置页右上角提供：

- “基础/高级”开关：默认仅展示常用项；高级项默认隐藏但随时可打开查看/修改。
- 搜索框：按 `key / 说明 / 提示 / ENV KEY` 关键字过滤配置项，快速定位开关。

每个配置字段会展示：

- `ENV KEY`：对应的环境变量名（例如 `llm_api_key -> LLM_API_KEY`）
- 默认值：鼠标悬浮在“默认”标记上可查看（不会泄露密钥）

## 查看“生效配置（effective snapshot）”

很多配置有默认值与派生值（例如“模型能力推断”“预算计算”等）。WebUI 提供“生效配置”视图，用于回答：

- 我到底开了什么？
- 哪些配置互相冲突？
- 本次运行的预算/阈值是多少？

当你排障或提 Issue 时，优先提供该视图导出的脱敏信息。

## WebUI 读写哪个 env 文件？

WebUI 的配置读写会使用以下规则选择 env 文件：

1. 若设置了 `DOTENV_PATH`：读写该路径指向的文件。
2. 否则若 `ENVIRONMENT=prod` 且存在 `.env.prod`：读写 `.env.prod`。
3. 否则：读写 `.env`。

部署建议：

- 如果你用 `.env.prod` 跑生产环境，建议在启动脚本/服务里设置 `DOTENV_PATH=/path/to/.env.prod`，避免 WebUI 写到 `.env` 导致“看起来保存了但运行没变”。

## 常见安全问题

- 不要把真实 `LLM_API_KEY` 写进公开的文档、截图或仓库文件。
- 如果要分享日志/配置，优先使用 WebUI 的脱敏导出能力。
