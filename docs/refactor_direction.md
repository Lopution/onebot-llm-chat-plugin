# 重构方向（草案）：面向“多平台/多协议/多框架”的 Mika 插件化架构

本文件描述 **长期重构方向**，目标是在尽量保持现有部署与行为兼容的前提下，让项目逐步具备：

- 多宿主框架：NoneBot2 之外，未来可接入其它框架（例如 Koishi 等）
- 多平台/多协议：不仅限于 QQ + OneBot
- 多厂商服务：LLM Provider / Search Provider 可替换、可扩展

这是“方向文档”，不是一次性大改的实施清单。实际落地建议按小步提交、每步可回滚。

---

## 当前执行状态（与开发仓对齐）

- Stage A/B/C/D 的功能项已完成，当前进入 **B-D 收尾门禁** 阶段。
- 收尾的唯一执行与证据口径见：
  - `plans/HOST_DECOUPLING_EXEC_PLAN.md`
- 本文档继续承担“长期方向”，不再承载门禁打勾与提交级证据。

---

## 1. 现状与痛点（我们要解决什么）

当前项目已具备“核心 + 适配层”的基本分层，但仍存在典型的宿主耦合风险与扩展摩擦：

1. **宿主框架耦合**
   - 核心逻辑偶尔会通过依赖注入/事件类型/日志等方式间接依赖宿主（例如 NoneBot 的类型、生命周期钩子）。
   - 一旦引入跨语言框架（例如 Koishi/Node），纯 Python “库式复用”本质上行不通，需要“协议化”。

2. **协议语义丢失**
   - 不同平台的“@、引用、图片、转发、附件”语义差异大；如果核心只吃纯文本，很容易造成上下文理解问题。

3. **Provider 扩展复杂**
   - LLM/Search 的“可替换”不能只停留在配置项上，还需要：能力声明、消息清洗、错误映射、可观测性与一致测试。

---

## 2. 北极星架构（目标形态）

核心思想：把项目拆成 4 层，层与层之间只有“明确的接口契约”。

1. **Core（宿主无关）**
   - 负责：上下文建模、Prompt 管理、工具编排、搜索编排、LLM 调用编排、策略（主动发言/降级/重试等）。
   - 不允许：导入任何宿主框架（NoneBot/Koishi/Discord SDK 等）。

2. **Ports（宿主能力接口）**
   - Core 需要做事时，不直接调用宿主 API，而是调用 Ports。
   - Ports 是一组最小接口，例如：
     - `send_message(session_id, parts, reply_to, mentions, ...)`
     - `fetch_message(message_id)` / `fetch_recent_messages(session_id, limit)`
     - `resolve_user(user_id)` / `resolve_group(group_id)`
     - `download_asset(url_or_id)`（图片/语音/文件）

3. **Adapters（宿主/协议适配层）**
   - 实现 Ports，把“宿主事件”转换为 Core 的统一事件结构（Contracts）。
   - 例：`nonebot_plugin_mika_chat` 只做两件事：
     - `event -> contracts.EventEnvelope`
     - `actions -> host api calls`

4. **Providers（外部服务适配层）**
   - LLM Provider：OpenAI compat、Anthropic native、Google GenAI native……
   - Search Provider：Serper、Tavily……
   - Provider 必须显式声明能力：`supports_tools/images/json_mode/streaming/...`
   - Core 根据能力做上下文清洗与降级（能力不足则文本化/禁用工具等）。

---

## 3. 两种运行模式（决定能否跨语言/跨框架）

为了同时满足“现有 Python 部署”与“未来 Koishi 等非 Python 宿主”，建议从一开始就把 Core 设计成可同时支持两种模式：

1. **Embedded 模式（Python 内嵌）**
   - Core 作为 Python 包被导入，Adapter 直接调用 Core。
   - 优点：性能好、调试简单、部署最少组件。
   - 适用：NoneBot2、Hoshino 等 Python 框架。

2. **Core Service 模式（推荐做未来兼容的基础）**
   - Core 作为独立进程提供 HTTP API（或 gRPC），Adapter 以客户端形式调用。
   - 优点：跨语言（Koishi/Node、Go、Rust）都能接入；Core 统一演进；多平台并存更简单。
   - 适用：Koishi、Discord.js、Telegram bot（非 Python）。

建议策略：**先完成 Embedded 的完全解耦**，同时把 Contracts/Ports 设计为“可直接 JSON 序列化”的形态，这样升级到 Core Service 只需要加一层传输，而不是推倒重来。

---

## 4. 统一事件契约（Contracts）：把“语义”保留下来

Core 入口不应该是宿主事件对象，而是统一的结构体：

- `EventEnvelope`
  - `session_id`: `group:{id}` / `dm:{id}` / `channel:{id}`
  - `message_id`, `timestamp`
  - `author`: `{id, nickname, role}`
  - `content_parts`: list of
    - `text`
    - `mention`（@谁）
    - `reply`（回复了哪条）
    - `image`（引用/本条/转发来源，统一成 asset ref）
    - `attachment`（文件/语音/视频等，先占位，按需扩展）
  - `raw`（可选，仅用于诊断，默认不入库）

关键点：

- **历史上下文存储**以“文本转录 + 占位符”为主，避免把大量二进制塞入 LLM 输入。
- **按需取回**：当模型明确需要历史图片/附件时，通过工具或 Ports 再取回。

---

## 5. 统一动作契约（Actions）：Core 的输出怎么落到宿主

Core 不直接调用宿主，而是返回一组动作：

- `SendMessageAction(session_id, parts, reply_to, mentions, ...)`
- `ReactAction(...)`（可选）
- `TypingAction(...)`（可选）
- `NoopAction(reason=...)`

Adapter 决定动作如何具体映射到宿主能力（例如 OneBot v11 的 reply CQ 码、v12 的 message segment）。

---

## 6. Provider/Registry/Capabilities（对齐 AstrBot 思路，但更轻量）

AstrBot 的启发点值得学习，但不必照搬所有“管理器”：

1. **Registry**
   - 用字符串 `provider_id` 选择 Provider 工厂（LLM/Search 分开）。

2. **Capabilities 驱动清洗**
   - 先“写核心逻辑”，再用能力清洗解决兼容问题：
     - 不支持图片：图片转为 `[图片]` 占位
     - 不支持工具：移除 tool messages/tool_calls，必要时改为“提示用户补充信息”

3. **错误映射与可观测性统一**
   - Provider 不直接抛各种 SDK 异常，而是映射为统一异常（auth/ratelimit/timeout/server）。
   - Core 使用统一重试/多 key 轮换/降级逻辑。

---

## 7. 配置策略（“一套配置” + 统一命名）

建议长期维持：

- **对外**：统一使用 `MIKA_*` 环境变量。
- **对内**：归一为单一 `Settings`（例如 `llm_provider/llm_base_url/llm_api_key/search_provider/...`）。
- **迁移方式**：文档和脚本只维护 `MIKA_*`，避免双命名长期并存。

核心原则：**配置是运行时输入，不应该通过 import-time 常量固定**（避免热更新与测试注入困难）。

---

## 8. 分阶段落地路线（建议）

### Stage A：完成“宿主完全解耦”（Embedded）
交付物：
- Core 仅依赖 Ports/Contracts，不导入宿主框架。
- NoneBot 适配层只做事件转换与动作执行。
- 新增 `FakePorts`，让 Core 能在纯单元测试中跑通。

验收：
- 在未安装 NoneBot 的环境中 `import mika_chat_core` 成功。
- 用 `FakePorts` 运行一条事件，能得到可预测动作（无外部网络依赖）。

### Stage B：协议扩展准备（多协议/多平台）
交付物：
- Contracts 覆盖 @、reply、图片占位等关键语义。
- OneBot v11/v12 的差异只存在于 adapter（而不是 core）。

验收：
- 同一语义事件在 v11/v12 下生成一致的 Contracts（差异仅体现在 raw 或 adapter）。

### Stage C：Core Service（跨语言宿主的关键）
交付物：
- HTTP API：`POST /v1/events`（输入 EventEnvelope）返回 Actions。
- Schema 版本化：`schema_version=1`，未来可兼容升级。
- Adapter client（Python/Node）最小实现：把宿主事件发给 Core Service 并执行 Actions。

验收：
- NoneBot adapter 可切换为“远程模式”工作（可选）。
- Node/Koishi 可用相同 Contracts 访问 Core Service（先做 demo 即可）。

### Stage D：Providers 扩展与稳定化
交付物：
- LLM Provider：OpenAI compat + Anthropic native + Google GenAI native 稳定映射。
- Search Provider：Serper/Tavily 可切换。
- capabilities 清洗覆盖：tools/images/json_mode。

验收：
- 在 mock HTTP 下，三类 LLM provider 都能跑通：普通对话 + 工具调用 + JSON 输出。

---

## 9. 风险与边界（避免重构把自己拖死）

- 不做“重构顺便改行为”：每个 Stage 的行为变化必须可解释、可回归、可关闭。
- 不追求一次性支持所有平台：先把接口做对（Contracts/Ports），再加适配器。
- Core Service 是跨语言的唯一正路：如果 Koishi 是硬需求，务必尽早把 Contracts 设计成“可序列化”。

---

## 10. 下一步建议（最小可执行）

1. 把现有消息处理链路收敛为：`adapter -> engine.handle(envelope, ports) -> actions -> adapter`
2. 把 `Ports` 做到“最小闭环”：
   - 发送消息
   - 拉取引用消息（reply）文本
   - 下载图片（如需）
3. 先用 `FakePorts` 把核心单测跑通，再回连 NoneBot 真 Ports。

---

## 11. 可执行拆分（Roadmap）

目标：把上面的 Stage A/B/C/D 进一步拆成 **可以直接开工** 的任务清单，每个任务都有验收与回滚策略。

说明：

- 默认所有重构都遵循“小步提交、每步可回滚、保持入口兼容”的原则。
- “部署仓”只保存文档与最终同步结果；建议实际开发在开发仓完成后再同步到部署仓。

### Stage A（Embedded）：核心完全宿主解耦

**A0. 基线冻结**

- 交付物：
  - 记录当前关键行为与启动日志（用于对比回归）。
  - 增加 guard test：核心包导入不依赖宿主框架（例如禁止 `mika_chat_core` 直接 import `nonebot`）。
- 验收：
  - `pytest -q` 全绿。
  - 在无宿主依赖环境中，至少 `import mika_chat_core` 成功（或明确列出允许的最小依赖集合）。
- 回滚：
  - 单一提交回滚即可，不影响线上运行。

**A1. Contracts 落地（统一事件与内容语义）**

- 交付物：
  - `contracts.EventEnvelope`、`contracts.ContentPart`、`contracts.Author` 等核心数据结构。
  - 覆盖最小语义闭环：`text / mention / reply / image`（attachment 先占位）。
  - 设计原则：Contracts 必须可 JSON 序列化（为 Stage C 铺路）。
- 验收：
  - 单元测试：构造一条包含 `@ + reply + 图片占位` 的 envelope，序列化/反序列化后结构不变。
  - 不改现有业务行为，仅新增结构与测试。
- 回滚：
  - 删除新增 contracts 文件即可，不影响现有流程。

**A2. Ports（宿主能力最小接口）**

- 交付物（建议最小集）：
  - `ports.MessagePort`：
    - `send_message(actions.SendMessageAction)`
    - `fetch_message(message_id)`（用于 reply 引用解析）
  - `ports.AssetPort`：
    - `download(url_or_asset_ref)`（图片/附件下载）
  - `ports.ClockPort`：
    - `now()` / `monotonic()`（把时间基准统一起来，便于测试与稳定性）
  - `FakePorts`（纯内存实现，用于核心单测，不需要宿主与网络）
- 验收：
  - 核心单测可在不启动 NoneBot 的情况下跑通至少 1 条“收到消息 -> 生成回复动作”的闭环。
- 回滚：
  - ports 新增为增量模块，可独立回滚。

**A3. Actions（核心输出契约）**

- 交付物：
  - `actions.SendMessageAction`（文本 + mentions + reply_to + 可选图片占位）
  - `actions.NoopAction`（带 reason，便于诊断）
  - 预留但不实现：`TypingAction/ReactAction`（先定义结构避免未来破坏性变更）
- 验收：
  - 核心在 FakePorts 下返回 Actions（不直接调用宿主 API）。
- 回滚：
  - Actions 仅新增，不影响现有路径。

**A4. Engine 主入口收敛（adapter -> engine -> actions）**

- 交付物：
  - `engine.handle_event(envelope, ports, settings) -> list[Action]`
  - 迁移原则：
    - 不在 engine 中出现宿主类型（NoneBot/OneBot 等）。
    - 现有 `handlers.py`、`mika_api.py` 等可先“委派”进 engine，逐步收敛。
  - 兼容入口保留：
    - 现有 NoneBot 插件入口仍然工作（只是内部改为调用 engine）。
    - `python bot.py` 启动方式不变。
- 验收（必须包含真实适配层）：
  - 启动后 at/reply/图片输入等关键路径行为不退化。
  - `/health`、`/metrics`（如存在）保持可用。
- 回滚：
  - adapter 保持旧调用路径的 fallback（例如保留旧 handler 函数），回滚只需切回旧分支。

**A5. 适配层“变薄”（NoneBot 只做转换）**

- 交付物：
  - `nonebot_plugin_mika_chat` 仅负责：
    - 解析宿主事件 -> EventEnvelope
    - 执行 Action -> 调用宿主 API
    - 注入 Ports 的真实实现（MessagePort/AssetPort/ClockPort）
  - 严禁核心层 import NoneBot；禁止 adapter 把宿主对象传入核心。
- 验收：
  - 新增集成测试（或最小 smoke test）确保插件可 import、DI 可解析、启动不崩。
- 回滚：
  - adapter 改动集中，可单独回滚到旧 handler 链路。

### Stage B（协议/平台）：多协议语义层稳定

目标：在不引入新平台的前提下，把 OneBot v11/v12 的差异压缩到 adapter，把“语义”在 Contracts 层稳定下来。

- B1. OneBot 语义对齐：
  - 统一 `@、reply、image` 的表示（v11 CQ 码 vs v12 segments）。
  - 关键：不要让核心依赖“原始文本里包含 CQ 码”的实现细节。
- B2. 历史上下文语义一致：
  - 历史记录存“转录文本 + 占位符 + message_id 引用”，避免把二进制塞进历史上下文。
  - 当需要“看历史图片/附件”时，通过工具或 Ports 按需取回。
- 验收：
  - 相同对话在 v11/v12 下，核心收到的 envelope 表达一致，输出 action 表达一致。
- 回滚：
  - 仅 adapter 变更时可回滚；Contracts 变更必须版本化（避免破坏 Stage C）。

### Stage C（Core Service）：跨语言宿主基础

如果未来 Koishi（Node）是硬需求，这一阶段基本不可避免。

**C0. API 形态定稿**

- 交付物：
  - HTTP API 草案：
    - `POST /v1/events` 输入 `EventEnvelope`，返回 `Action[]`
    - `schema_version` 与 `capabilities`（便于兼容升级）
  - 安全策略：
    - 本地回环/内网访问优先
    - 简单 token auth（可选，但建议有）
- 验收：
  - 用 curl/pytest 发一个 envelope，能拿到 action。

**C1. 远程模式适配（remote-only）**

- 交付物：
  - NoneBot adapter 仅支持 `remote` 运行模式，统一通过 HTTP 调用 Core Service。
- 验收：
  - 主链路全部经 `POST /v1/events` 进入核心，适配层不再保留 embedded 回退。
- 回滚：
  - 通过回滚版本恢复旧模式，不在当前代码内保留双模式开关。

**C2. Koishi Demo（最小化，不做产品化）**

- 交付物：
  - Node 侧只做：事件转换 -> 调 Core Service -> 执行动作。
- 验收：
  - 一个最小命令可运行，证明 contracts/actions 是跨语言可用的。

### Stage D（Providers）：LLM/Search 多厂商稳定化

目标：在“Contracts/Ports/Engine”稳定后，再扩大 Provider 支持面，避免重构期间引入多维不确定性。

- D1. LLM Provider：
  - OpenAI compat 作为覆盖面最大的一类（含 OpenRouter/NewAPI/多数国内兼容端点）。
  - 三种原生格式：OpenAI / Anthropic / Google GenAI（逐个落地、逐个验收）。
  - Capabilities 驱动清洗与降级，保持稳定行为。
- D2. Search Provider：
  - Provider interface + registry（Serper/Tavily 等）。
  - 搜索编排统一：预搜索优先 + 最多一次补搜 + 去重拦截（避免重复请求）。
- 验收：
  - mock HTTP 下跑通：普通对话 + 工具调用 + JSON 输出 + 搜索切换。
- 回滚：
  - provider 层可独立切换，默认链路保持可用。
