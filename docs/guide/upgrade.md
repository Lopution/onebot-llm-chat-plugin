# 升级指南（Breaking Changes）

本页描述“会导致启动失败/行为变化”的升级点，帮助你从旧配置迁移到当前版本。

## 1) 旧环境变量键名已切断（存在即启动失败）

以下旧键已被移除，继续配置会直接失败（不会自动兼容/回读）：

| 旧键 | 新键 |
|------|------|
| `MIKA_API_KEY` | `LLM_API_KEY` |
| `MIKA_API_KEY_LIST` | `LLM_API_KEY_LIST` |
| `MIKA_BASE_URL` | `LLM_BASE_URL` |
| `MIKA_MODEL` | `LLM_MODEL` |
| `MIKA_FAST_MODEL` | `LLM_FAST_MODEL` |
| `SERPER_API_KEY` | `SEARCH_API_KEY` |
| `MIKA_HISTORY_IMAGE_ENABLE_COLLAGE` | `MIKA_HISTORY_COLLAGE_ENABLED` |

建议迁移方式：
1. 以当前仓库的 `.env.example` 为模板重新生成 `.env`/`.env.prod`。
2. 只把“你确实需要的值”填回去（最小必填：`LLM_API_KEY` + `MIKA_MASTER_ID`）。
3. 运行自检：

```bash
python3 scripts/doctor.py
```

## 2) 配置前缀从“单一 MIKA_*”变为三类单一入口

当前配置使用三类前缀作为单一入口：

- `LLM_*`：LLM Provider/Base URL/API Key/模型
- `SEARCH_*`：联网搜索（可选）
- `MIKA_*`：插件功能与行为开关

不要再混用旧的 `MIKA_API_*` 与新的 `LLM_*`，否则会直接报错。

## 3) WebUI 访问策略更严格

如果 `MIKA_WEBUI_TOKEN` 为空：
- 只允许本机 loopback 访问（`127.0.0.1/localhost`）
- 远程访问必须设置 token（并建议配合 HTTPS/反代）

## 4) 常见“升级后不工作”的快速检查

1. `.env/.env.prod` 是否还残留旧键名（如 `MIKA_API_KEY=`）？
2. `LLM_BASE_URL` 是否为你的上游/中转站真实地址？
3. `LLM_MODEL` 是否是该上游可用的模型名？
4. 如果你使用中转站：
   - 必要时手动设置能力覆盖（例如 `MIKA_LLM_SUPPORTS_IMAGES=false`）

