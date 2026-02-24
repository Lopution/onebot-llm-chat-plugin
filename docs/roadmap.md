# onebot-llm-chat-plugin 未来发展路线图（兼顾自用 + 开源）

本文是“项目总路线图（Source of Truth）”，用于统一目标、边界、里程碑与验收口径，避免分散到多份计划导致过时与冲突。

说明：
- 纯架构方向仍见 `docs/refactor_direction.md`（它更偏“目标形态/分层/契约”）。
- 本路线图更偏“做什么 + 何时做 + 如何验收 + 如何回滚”。

---

## 简要总结（方向与目标）

- **北极星目标**：同一套核心代码，既能支撑你日常群聊稳定可用，也能对外开源维护与演进。
- **现状痛点**：功能很多但结构像“老房子加盖”，继续堆功能会越来越难维护、难定位问题，也难保证体验一致。
- **总体策略**：沿用你现有“增量绞杀式重构”思路，每批次可独立发布/回滚；并把部署仓的真实验收纳入流程。

---

## 项目治理（不会再反复决策）

- **主仓（Source of Truth）**：`/root/onebot-llm-chat-plugin`
  - 所有核心代码改动先在这里完成并跑通测试，再同步到部署仓。
- **部署仓角色**：`/root/bot`
  - 以“真实运行环境 + 验收”为主，尽量不直接改核心逻辑（仅保留脚本、`.env.prod`、models、logs、NapCat 相关等私有内容）。
- **发布策略**：
  - `MAJOR`：允许破坏性变更（需要写清 BREAKING CHANGE 与迁移说明）。
  - `MINOR/PATCH`：不破坏公共接口，只做新增/修复/性能/可观测性改进。
- **双仓同步方式**：继续“复制同步”，但要脚本化 + 可回滚，避免手工步骤导致分叉。

---

## 关键公共接口（稳定契约）

后续重构必须满足：`MINOR/PATCH` 不破坏以下接口；如必须破坏则走 `MAJOR`：

- **Python 插件入口**：`nonebot_plugin_mika_chat` 的加载与初始化必须可用。
- **运行时配置入口**：以 `LLM_*` 与 `MIKA_*` 环境变量为唯一入口（新增键允许，但旧键不能随意改名/删除）。
- **Core Service HTTP**（若启用远程模式）：至少保证
  - `POST /v1/events`
  - `GET /v1/health`
- **上下文语义稳定**：历史记录默认以“文本转录 + 稳定媒体占位符”为主，避免二进制直接进历史上下文；需要时再按需回取。

---

## 路线图（按阶段/批次）

阶段命名沿用 `docs/refactor_direction.md` 的 Stage A/B/C/D，但把“近期必须做”的体验与稳定性专题单独拉出来做 P0。

### P0（近期最高优先级）：多模态上下文自动关联（对齐 AstrBot）

目标：把“图片/表情包等非文本内容”从现在的“必须引用/必须工具才看得到”升级为 AstrBot 式体验：
- 无论被触发回复还是主动发言，只要当前触发消息需要结合最近非文本上下文理解，系统就自动把相关媒体带给 LLM。
- 当主上游不支持图片输入时，自动走 caption 兜底：先用可看图的 caption provider 把图片转文字，再注入本次请求。

#### 目标与验收标准（必须）

1. **无需引用**：用户先发图/表情包，后一句只说“啥意思/这是什么/解释下/看懂没”，不 reply、不引用，LLM 仍能基于刚刚媒体正确回答。
2. **覆盖主动发言**：开启 `MIKA_PROACTIVE_CHATROOM_ENABLED=true` 时，同样成立。
3. **主上游不支持图片时也尽量像**：主上游禁用图片输入时，系统会自动生成 caption 注入；保证路径存在、失败可观测、可降级。
4. **测试门禁**：`pytest -q` 全绿，并新增测试覆盖“隐式指代 + 自动关联 + caption 兜底”。

#### 对外接口/行为变更（公开面）

1. **行为变更**：`mika_history_image_mode=hybrid` 下，部分原本只给 TWO_STAGE 提示的场景会变成“后端自动回取并附带媒体”。
2. **新增配置项（最小集）**：
   - `MIKA_LLM_SUPPORTS_IMAGES`：`true/false`；缺省不设置表示按 provider 推断。
   - `MIKA_MEDIA_CAPTION_ENABLED`：`true/false`；默认 `false`。
   - `MIKA_MEDIA_CAPTION_PROVIDER`：`openai_compat/google_genai/anthropic/azure_openai`；默认空=复用主 provider。
   - `MIKA_MEDIA_CAPTION_BASE_URL`、`MIKA_MEDIA_CAPTION_API_KEY`、`MIKA_MEDIA_CAPTION_MODEL`：默认空=复用主 LLM 配置。
   - `MIKA_MEDIA_CAPTION_PROMPT`、`MIKA_MEDIA_CAPTION_TIMEOUT_SECONDS`：提供默认值；不启用 caption 时不调用。

#### 实施步骤（代码改动清单）

1. **强化“需要媒体理解”的判定（隐式指代）**
   - 改 `src/mika_chat_core/utils/history_image_policy.py`
     - 修复 bug：`custom_keywords` 合并后未参与判断；改为“追加到 GENERAL 触发词集合”参与判断（不覆盖默认集合）。
     - `_count_image_placeholders_in_context()` 同时识别：
       - `[图片]`、`[图片×N]`、`[图片][picid:...]`
       - `[表情]`、`[表情][emoji:...]`
     - 新增隐式触发规则（Smart Attach，默认启用）：
       - 最近上下文存在媒体占位，且当前消息命中“短问句/求解释”模式（如 `啥意思/这是什么/解释下/看懂没/什么意思/怎么回事/图里写的啥` 等），提升 `confidence` 至至少 `two_stage_threshold`。
   - 测试：扩展 `tests/test_history_image_policy_thresholds.py`：
     - 上下文含 `[表情][emoji:...]` 或 `[图片][picid:...]`，用户发“啥意思”，应触发 `TWO_STAGE`。

2. **TWO_STAGE 变“后端自动带媒体”，工具仅作兜底**
   - 改 `src/mika_chat_core/handlers_history_image.py`
     - `decision.action == TWO_STAGE` 时：
       - 先走“内部回取”把候选 `msg_ids` 换成 `data:` URL（成功则直接返回 `final_image_urls`，并注入更强 mapping：包含 `<msg_id:...>` 与 sender）。
       - 失败再回退到现有 `build_candidate_hint()`（提示模型可用工具）。
     - 私聊也取 `context_messages` 参与策略判定（现在仅群聊取）。
   - 抽取复用逻辑（避免双维护）：
     - 把“按 context_key + msg_id 回取图片并转 data:”的核心逻辑做成可复用函数（工具与 handler 共用）。
   - 测试：
     - 新增 `tests/test_history_image_auto_attach.py`：构造 message_archive 含 msg_id 对应 image_url，断言 TWO_STAGE 会返回 `data:` URL（不是空列表 + hint）。

3. **主上游“禁发图片 + caption 兜底”闭环**
   1. 明确主上游是否能吃图（可配置覆盖）
      - 改 `src/mika_chat_core/config.py`：新增 `mika_llm_supports_images: Optional[bool] = None`（env: `MIKA_LLM_SUPPORTS_IMAGES`）。
      - 改 `src/mika_chat_core/mika_api_layers/builder/flow.py`：
        - 计算 `supports_images` 后，若 `mika_llm_supports_images is not None`，覆盖 capabilities 判定。
   2. 让“本次请求图片”也遵守 supports_images（避免上游空回复/400）
      - 改 `src/mika_chat_core/mika_api_layers/builder/stages.py`：
        - `build_original_and_api_content()` 新增参数 `allow_images_in_api: bool`。
        - `original_content` 保留图片 part（用于 archive/回取/语义稳定）。
        - `api_content` 在 `allow_images_in_api=False` 时只发文本占位符，不发 `image_url`。
      - 改 `src/mika_chat_core/mika_api_layers/builder/flow.py`：
        - 调用 `build_original_and_api_content(allow_images_in_api=supports_images)`。
   3. caption 服务（可配置 provider，带缓存）
      - 新增 `src/mika_chat_core/utils/media_captioner.py`
        - `caption_images(image_parts: list[dict], *, request_id: str, cfg: Config) -> list[str]`
        - key 优先使用 `picid/emoji`（稳定语义 id），否则 url hash；TTL 固定 1 天，max_size 固定 1000。
   4. caption 注入策略（不污染指令优先级）
      - 改 `src/mika_chat_core/mika_api_layers/builder/flow.py`
        - 当 `supports_images=False` 且本次请求存在图片：
          - 若 caption 启用：把 captions 追加到 `system_injection`，固定格式：
            - `[Context Media Captions | Untrusted]`
            - `- Image 1: ...`
          - caption 失败：warning 可观测，继续执行，仅保留占位 token。
   - 测试：
     - 新增 `tests/test_builder_caption_fallback.py`
       - 强制 `MIKA_LLM_SUPPORTS_IMAGES=false`
       - mock captioner 返回固定文本
       - 断言 `request_body.messages` 不出现 `image_url`，但出现 captions 注入文本。

4. **主动发言 transcript 模式下的 msg_id 标记（提高关联稳定性）**
   - 改 `src/mika_chat_core/handlers_proactive.py`
     - transcript 行含媒体占位（`[图片` 或 `[表情`）且 msg 有 `message_id` 时，在行尾追加 ` <msg_id:...>`。
   - 改 `src/mika_chat_core/mika_api_layers/builder/stages.py`
     - 历史消息附加 msg_id 的条件：从只匹配 `"[图片"` 扩展为 `"[图片"` 或 `"[表情"`。
   - 测试：
     - 新增 `tests/test_proactive_transcript_msgid.py`：断言输出包含 `<msg_id:...>`。

#### 发布与回滚策略

1. 先发 `rc`：默认不启用 caption（`MIKA_MEDIA_CAPTION_ENABLED=false`），只上线“隐式指代 + TWO_STAGE 自动带媒体”。
2. 部署仓验证主上游是否支持图片：
   - 支持：`MIKA_LLM_SUPPORTS_IMAGES` 不设置或设 `true`。
   - 不支持：设 `false` 并配置 caption provider。
3. 再发正式版：把 caption 作为“可选但推荐”的能力写清楚（成本/延迟/失败行为）。

---

### Stage A/B/C/D（长期演进）

本段保留 Stage A/B/C/D 作为长期演进方向（详见 `docs/refactor_direction.md`），但“优先级”以 P0 专题与线上问题为准。

