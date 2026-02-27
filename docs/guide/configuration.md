# 配置参考

> 本页由 `scripts/gen_config_docs.py` 自动生成。请勿手改，以免再次过时。

## 最小必填

```env
LLM_API_KEY="YOUR_API_KEY"
MIKA_MASTER_ID=123456789
```

说明：`LLM_API_KEY` 与 `LLM_API_KEY_LIST` 二选一即可。

## LLM 提供商

| 字段 | 环境变量 | 类型 | 默认值 | 说明 |
|------|----------|------|--------|------|
| `llm_provider` | `LLM_PROVIDER` | `string` | `openai_compat` | LLM 提供商<br/>与 LLM API 通信的适配器类型。 |
| `llm_base_url` | `LLM_BASE_URL` | `string` | `https://generativelanguage.googleapis.com/v1beta/openai/` | API Base URL<br/>LLM 服务的 API 地址。OpenAI 兼容模式支持第三方中转。 |
| `llm_api_key` | `LLM_API_KEY` | `string` | `` | [secret] API Key<br/>LLM 服务的认证密钥。 |
| `llm_api_key_list` | `LLM_API_KEY_LIST` | `array` | `[]` | [secret, advanced] API Key 列表（可选）<br/>用于 Key 轮换的列表（JSON 数组或逗号分隔）。与 LLM_API_KEY 二选一即可。 |
| `llm_model` | `LLM_MODEL` | `string` | `gemini-3-pro-high` | 主模型<br/>默认对话使用的模型名称（如 gpt-4o、claude-sonnet-4-20250514）。 |
| `llm_fast_model` | `LLM_FAST_MODEL` | `string` | `gemini-2.5-flash-lite` | 快速模型<br/>用于记忆抽取、摘要等轻量任务的模型，留空则使用主模型。 |
| `mika_task_filter_model` | `MIKA_TASK_FILTER_MODEL` | `string` | `` | [advanced] 任务模型：过滤（高级）<br/>用于相关性过滤/轻量判定；留空则回退到快速模型。 |
| `mika_task_summarizer_model` | `MIKA_TASK_SUMMARIZER_MODEL` | `string` | `` | [advanced] 任务模型：摘要（高级）<br/>用于上下文摘要；留空则回退到快速模型。 |
| `mika_task_memory_model` | `MIKA_TASK_MEMORY_MODEL` | `string` | `` | [advanced] 任务模型：记忆（高级）<br/>用于长期记忆提取；留空则回退到快速模型。 |
| `llm_extra_headers_json` | `LLM_EXTRA_HEADERS_JSON` | `string` | `` | [advanced] 额外请求头（高级）<br/>JSON 格式的额外 HTTP 头，例如 {"X-Custom": "value"}。 |

## 身份与权限

| 字段 | 环境变量 | 类型 | 默认值 | 说明 |
|------|----------|------|--------|------|
| `mika_master_id` | `MIKA_MASTER_ID` | `string` | `` | 管理员 QQ 号<br/>Bot 主人的 QQ 号，拥有最高权限。 |
| `mika_master_name` | `MIKA_MASTER_NAME` | `string` | `Sensei` | 管理员昵称<br/>在对话中称呼管理员的名字。 |
| `mika_bot_display_name` | `MIKA_BOT_DISPLAY_NAME` | `string` | `Mika` | Bot 显示名称<br/>Bot 在对话中的自称。 |
| `mika_group_whitelist` | `MIKA_GROUP_WHITELIST` | `array` | `[]` | 群白名单<br/>允许 Bot 响应的群号列表，为空则响应所有群。逗号分隔或 JSON 数组。 |

## 对话上下文

| 字段 | 环境变量 | 类型 | 默认值 | 说明 |
|------|----------|------|--------|------|
| `mika_max_context` | `MIKA_MAX_CONTEXT` | `integer` | `40` | [advanced] 最大上下文消息数（高级）<br/>单次请求携带的最大历史消息条数。 |
| `mika_context_mode` | `MIKA_CONTEXT_MODE` | `string` | `structured` | [advanced] 上下文模式（高级）<br/>structured: 结构化消息列表; legacy: 纯文本拼接（兼容 plain）。 |
| `mika_context_max_turns` | `MIKA_CONTEXT_MAX_TURNS` | `integer` | `30` | [advanced] 最大对话轮数（高级）<br/>上下文中保留的最大对话轮数。 |
| `mika_context_max_tokens_soft` | `MIKA_CONTEXT_MAX_TOKENS_SOFT` | `integer` | `100000` | [advanced] 上下文软 Token 上限（高级）<br/>超过此值时自动截断旧消息（估算值）。 |
| `mika_context_summary_enabled` | `MIKA_CONTEXT_SUMMARY_ENABLED` | `boolean` | `false` | [advanced] 启用上下文摘要（高级）<br/>超出轮数限制时用 LLM 生成摘要代替截断。 |
| `mika_topic_summary_enabled` | `MIKA_TOPIC_SUMMARY_ENABLED` | `boolean` | `false` | [advanced] 启用话题摘要（高级）<br/>按批次将群聊消息整理为结构化话题摘要。 |
| `mika_topic_summary_batch` | `MIKA_TOPIC_SUMMARY_BATCH` | `integer` | `25` | [advanced] 话题摘要批次大小（高级）<br/>每累计 N 条新消息触发一次话题摘要。 |

## 语义匹配

| 字段 | 环境变量 | 类型 | 默认值 | 说明 |
|------|----------|------|--------|------|
| `mika_semantic_enabled` | `MIKA_SEMANTIC_ENABLED` | `boolean` | `true` | [advanced] 启用语义匹配（高级）<br/>使用 embedding 模型对触发词做语义相似度匹配。 |
| `mika_semantic_model` | `MIKA_SEMANTIC_MODEL` | `string` | `` | [advanced] Embedding 模型（高级）<br/>本地 embedding 模型名称，首次使用时自动下载。 |
| `mika_semantic_backend` | `MIKA_SEMANTIC_BACKEND` | `string` | `auto` | [advanced] 推理后端（高级）<br/>auto: 自动选择（当前等价于 fastembed）; fastembed: CPU 推理，首次自动下载模型。 |
| `mika_semantic_threshold` | `MIKA_SEMANTIC_THRESHOLD` | `number` | `0.4` | [advanced] 匹配阈值（高级）<br/>语义相似度超过此值才触发匹配，范围 0.0 ~ 1.0。 |

## 长期记忆

| 字段 | 环境变量 | 类型 | 默认值 | 说明 |
|------|----------|------|--------|------|
| `mika_memory_enabled` | `MIKA_MEMORY_ENABLED` | `boolean` | `false` | [advanced] 启用长期记忆（高级）<br/>自动从对话中抽取事实并存储，后续对话中召回相关记忆。 |
| `mika_memory_search_top_k` | `MIKA_MEMORY_SEARCH_TOP_K` | `integer` | `5` | [advanced] 召回 Top-K（高级）<br/>每次对话最多召回的记忆条数。 |
| `mika_memory_min_similarity` | `MIKA_MEMORY_MIN_SIMILARITY` | `number` | `0.5` | [advanced] 最低相似度（高级）<br/>低于此相似度的记忆不会被召回，范围 0.0 ~ 1.0。 |
| `mika_memory_max_age_days` | `MIKA_MEMORY_MAX_AGE_DAYS` | `integer` | `90` | [advanced] 记忆保留天数（高级）<br/>超过此天数且召回次数少于 3 次的记忆会被自动清理。 |
| `mika_memory_extract_interval` | `MIKA_MEMORY_EXTRACT_INTERVAL` | `integer` | `3` | [advanced] 抽取间隔（消息数）（高级）<br/>每隔多少条消息触发一次记忆抽取。 |
| `mika_memory_retrieval_enabled` | `MIKA_MEMORY_RETRIEVAL_ENABLED` | `boolean` | `false` | [advanced] 启用 ReAct 记忆检索（高级）<br/>回复前执行多源检索（话题摘要/档案/长期记忆/知识库）。 |
| `mika_memory_retrieval_max_iterations` | `MIKA_MEMORY_RETRIEVAL_MAX_ITERATIONS` | `integer` | `3` | [advanced] ReAct 最大轮次（高级）<br/>记忆检索 Agent 的最大迭代次数。 |
| `mika_memory_retrieval_timeout` | `MIKA_MEMORY_RETRIEVAL_TIMEOUT` | `number` | `15.0` | [advanced] ReAct 超时（秒）（高级）<br/>记忆检索 Agent 总超时，超时后使用当前观察结果。 |

## 知识库 RAG

| 字段 | 环境变量 | 类型 | 默认值 | 说明 |
|------|----------|------|--------|------|
| `mika_knowledge_enabled` | `MIKA_KNOWLEDGE_ENABLED` | `boolean` | `false` | [advanced] 启用知识库（高级）<br/>开启 RAG 知识库功能，支持文档上传和向量检索。 |
| `mika_knowledge_default_corpus` | `MIKA_KNOWLEDGE_DEFAULT_CORPUS` | `string` | `default` | [advanced] 默认语料库 ID（高级）<br/>默认使用的知识库语料库标识。 |
| `mika_knowledge_auto_inject` | `MIKA_KNOWLEDGE_AUTO_INJECT` | `boolean` | `false` | [advanced] 自动注入知识（高级）<br/>每次对话自动检索并注入相关知识片段到上下文。 |
| `mika_knowledge_search_top_k` | `MIKA_KNOWLEDGE_SEARCH_TOP_K` | `integer` | `5` | [advanced] 检索 Top-K（高级）<br/>知识库检索返回的最大结果数。 |
| `mika_knowledge_min_similarity` | `MIKA_KNOWLEDGE_MIN_SIMILARITY` | `number` | `0.5` | [advanced] 最低相似度（高级）<br/>低于此值的知识片段不会被返回，范围 0.0 ~ 1.0。 |

## 工具与 ReAct

| 字段 | 环境变量 | 类型 | 默认值 | 说明 |
|------|----------|------|--------|------|
| `mika_tool_allowlist` | `MIKA_TOOL_ALLOWLIST` | `array` | `["web_search", "search_group_history", "fetch_history_images", "search_knowledge"]` | [advanced] 工具白名单（高级）<br/>允许 Bot 调用的工具名称列表，为空则允许所有已注册工具。 |
| `mika_tool_max_rounds` | `MIKA_TOOL_MAX_ROUNDS` | `integer` | `5` | [advanced] 工具调用轮数上限（高级）<br/>单次请求中最大工具调用轮次。 |
| `mika_react_enabled` | `MIKA_REACT_ENABLED` | `boolean` | `false` | [advanced] 启用 ReAct 推理（高级）<br/>让 Bot 使用思考-行动-观察循环来处理复杂问题。 |
| `mika_react_max_rounds` | `MIKA_REACT_MAX_ROUNDS` | `integer` | `8` | [advanced] ReAct 最大轮数（高级）<br/>ReAct 推理循环的最大迭代次数。 |

## 消息发送

| 字段 | 环境变量 | 类型 | 默认值 | 说明 |
|------|----------|------|--------|------|
| `mika_forward_threshold` | `MIKA_FORWARD_THRESHOLD` | `integer` | `300` | 长消息阈值<br/>达到该长度时优先使用长消息策略（转发/图片兜底）。 |
| `mika_message_split_enabled` | `MIKA_MESSAGE_SPLIT_ENABLED` | `boolean` | `false` | 启用消息分段<br/>长回复拆分为多条发送，提升 IM 阅读体验。 |
| `mika_message_split_threshold` | `MIKA_MESSAGE_SPLIT_THRESHOLD` | `integer` | `300` | 分段阈值<br/>达到该长度后执行分段发送。 |
| `mika_message_split_max_chunks` | `MIKA_MESSAGE_SPLIT_MAX_CHUNKS` | `integer` | `6` | 最多分段条数<br/>最多拆分为多少条消息；超出的内容会并入最后一条。 |
| `mika_reply_stream_enabled` | `MIKA_REPLY_STREAM_ENABLED` | `boolean` | `false` | [advanced] 启用流式发送（高级）<br/>逐段发送模型输出；平台不支持时自动回退。 |
| `mika_reply_stream_mode` | `MIKA_REPLY_STREAM_MODE` | `string` | `chunked` | [advanced] 流式模式（高级）<br/>chunked: 分段发送；final_only: 仅发送最终文本。 |
| `mika_reply_stream_min_chars` | `MIKA_REPLY_STREAM_MIN_CHARS` | `integer` | `120` | [advanced] 流式最小长度（高级）<br/>回复长度达到该值才启用流式发送。 |
| `mika_reply_stream_chunk_chars` | `MIKA_REPLY_STREAM_CHUNK_CHARS` | `integer` | `80` | [advanced] 流式分段长度（高级）<br/>每段发送的目标字符数。 |
| `mika_reply_stream_delay_ms` | `MIKA_REPLY_STREAM_DELAY_MS` | `integer` | `0` | [advanced] 流式段间延迟毫秒（高级）<br/>每段发送间隔延迟，0 表示无延迟。 |
| `mika_long_reply_image_fallback_enabled` | `MIKA_LONG_REPLY_IMAGE_FALLBACK_ENABLED` | `boolean` | `true` | 启用图片兜底<br/>长消息发送失败时渲染为图片发送。 |

## 主动发言

| 字段 | 环境变量 | 类型 | 默认值 | 说明 |
|------|----------|------|--------|------|
| `mika_proactive_keywords` | `MIKA_PROACTIVE_KEYWORDS` | `array` | `["Mika", "未花"]` | [advanced] 触发关键词（高级）<br/>包含这些关键词时触发主动发言，逗号分隔或 JSON 数组。 |
| `mika_proactive_topics` | `MIKA_PROACTIVE_TOPICS` | `array` | `["玩游戏或讨论游戏相关话题", "抽卡或氪金相关的话题", "关于甜点、蛋糕、零食的话题", "想吃东西或讨论美食", "作业、学习或课程相关", "考试成绩或挂科相关", "Blue Archive 蔚蓝档案游戏", "科技数码或电子产品", "听歌或音乐相关话题"]` | [advanced] 话题关键词（高级）<br/>当群聊讨论这些话题时触发主动发言。 |
| `mika_proactive_rate` | `MIKA_PROACTIVE_RATE` | `number` | `0.2` | [advanced] 随机触发概率（高级）<br/>每条群消息的随机触发概率，范围 0.0 ~ 1.0。 |
| `mika_proactive_cooldown` | `MIKA_PROACTIVE_COOLDOWN` | `integer` | `30` | [advanced] 冷却时间（秒）（高级）<br/>同一群内两次主动发言的最短间隔。 |
| `mika_relevance_filter_enabled` | `MIKA_RELEVANCE_FILTER_ENABLED` | `boolean` | `false` | [advanced] 启用相关性过滤（高级）<br/>群聊回复前先判断是否值得回复，降低无意义输出。 |
| `mika_relevance_filter_model` | `MIKA_RELEVANCE_FILTER_MODEL` | `string` | `` | [advanced] 相关性过滤模型（高级）<br/>过滤器专用模型，留空回退到任务模型配置。 |

## 搜索

| 字段 | 环境变量 | 类型 | 默认值 | 说明 |
|------|----------|------|--------|------|
| `search_provider` | `SEARCH_PROVIDER` | `string` | `serper` | 搜索引擎<br/>网络搜索使用的服务提供商。 |
| `search_api_key` | `SEARCH_API_KEY` | `string` | `` | [secret] 搜索 API Key<br/>搜索引擎服务的认证密钥。 |
| `mika_search_llm_gate_enabled` | `MIKA_SEARCH_LLM_GATE_ENABLED` | `boolean` | `false` | [advanced] LLM 搜索守门（高级）<br/>由 LLM 判断是否需要搜索，而非每次都搜索。 |

## WebUI

| 字段 | 环境变量 | 类型 | 默认值 | 说明 |
|------|----------|------|--------|------|
| `mika_webui_enabled` | `MIKA_WEBUI_ENABLED` | `boolean` | `false` | 启用 WebUI<br/>开启后可通过浏览器访问管理界面。 |
| `mika_webui_token` | `MIKA_WEBUI_TOKEN` | `string` | `` | [secret] 访问令牌<br/>WebUI 认证令牌，为空时仅允许本机 (127.0.0.1) 访问。 |
| `mika_webui_base_path` | `MIKA_WEBUI_BASE_PATH` | `string` | `/webui` | [advanced] URL 路径前缀（高级）<br/>WebUI 的 URL 路径前缀，如 /webui。 |

## 其他

| 字段 | 环境变量 | 类型 | 默认值 | 说明 |
|------|----------|------|--------|------|
| `mika_dream_enabled` | `MIKA_DREAM_ENABLED` | `boolean` | `false` | [advanced] 启用 Dream 整理（高级）<br/>会话空闲达到阈值后，后台自动整理/合并话题摘要。 |
| `mika_dream_idle_minutes` | `MIKA_DREAM_IDLE_MINUTES` | `integer` | `30` | [advanced] Dream 空闲阈值（分钟）（高级）<br/>会话空闲超过该值时触发一次 Dream 整理。 |
| `mika_dream_max_iterations` | `MIKA_DREAM_MAX_ITERATIONS` | `integer` | `5` | [advanced] Dream 最大迭代次数（高级）<br/>单次 Dream 运行最多执行的整理步骤数。 |
