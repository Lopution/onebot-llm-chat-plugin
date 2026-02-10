# Node Core Service Demo

最小跨语言验证：使用 Node.js 调用 `mika_chat_core` 的 `POST /v1/events`。

## 1. 前置条件

- Bot 正在运行（默认 `http://127.0.0.1:8080`）
- 已暴露 `POST /v1/events`
- Node.js >= 18（内置 `fetch`）

## 2. 运行

```bash
cd examples/node-core-service-demo
node index.mjs
```

可选环境变量：

- `CORE_URL`：默认 `http://127.0.0.1:8080`
- `CORE_TOKEN`：若服务端配置 `MIKA_CORE_SERVICE_TOKEN`，这里填相同 token

## 3. 预期结果

会打印 HTTP 状态码与返回的 `actions` JSON，用于验证跨语言调用链路。
