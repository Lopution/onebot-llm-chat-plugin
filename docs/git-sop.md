# Git SOP（版本与分支管理）

本文件是项目维护的日常操作标准（SOP），目标：

- `main` 始终可运行、可发布
- 每次改动可追溯、可回滚
- 与 CI/分支保护规则一致，减少“本地通过、线上失败”

---

## 1. 仓库角色与红线

### 仓库角色

- 开发主仓：`/root/onebot-llm-chat-plugin`
- 本地部署仓：`/root/bot`（私有运行环境）

### 红线

- 不把以下内容提交或同步到开发主仓：
  - `.env.prod`
  - `data/`
  - `models/`
  - `logs/`

双仓同步细节见：`docs/deploy/repo-sync.md`

---

## 2. 分支模型（Trunk-Based，轻量）

- 长期分支只保留：`main`
- 所有开发都走短分支 + PR 合并到 `main`
- 短分支尽量小步快跑（建议 1~3 天内完成）

### 分支命名

- `feat/<topic>` 新功能
- `fix/<topic>` 缺陷修复
- `refactor/<topic>` 重构
- `docs/<topic>` 文档
- `chore/<topic>` 工程杂项
- `hotfix/<topic>` 紧急修复

---

## 3. 提交流程（命令模板）

### 3.1 起分支

```bash
git checkout main
git pull --ff-only origin main
git checkout -b feat/<topic>
```

### 3.2 开发与提交

```bash
git add -A
git commit -m "feat(scope): short summary"
```

提交信息建议使用 Conventional Commits：

- `feat(scope): ...`
- `fix(scope): ...`
- `docs(scope): ...`
- `refactor(scope): ...`
- `test(scope): ...`
- `chore(scope): ...`

### 3.3 推送与 PR

```bash
git push -u origin <branch>
```

在 GitHub 发起 PR（`<branch> -> main`），等待检查通过后合并。

---

## 4. PR 与合并规范

### PR 描述最小要求

1. 改动目的（为什么改）
2. 主要改动点（改了什么）
3. 验证方式（跑了哪些测试）
4. 风险与回滚方式（失败如何撤回）

### 合并策略

- 推荐仅启用 `Squash merge`
- 每个 PR 在 `main` 只留下 1 个提交，便于追踪和回滚

---

## 5. 分支保护（GitHub Ruleset）

建议对 `main` 启用：

- `Require a pull request before merging`
- `Require status checks to pass`
- `Block force pushes`
- `Restrict deletions`
- `Require linear history`（建议）

当前测试门禁建议至少包含：

- `pytest (3.10)`
- `pytest (3.11)`
- `pytest (3.12)`

---

## 6. 发布与回滚

### 发布

1. `main` 同步并确认测试通过
2. 打 tag（语义化版本）：

```bash
git checkout main
git pull --ff-only origin main
git tag -a vX.Y.Z -m "vX.Y.Z"
git push origin vX.Y.Z
```

3. 在 GitHub Release 填写发布说明

### 回滚

优先用 `revert`，不要改公共历史：

```bash
git revert <commit_sha>
git push origin main
```

---

## 7. 双仓同步（开发仓 -> 部署仓）

1. 开发仓先通过测试（`pytest -q`）
2. 仅按白名单同步代码与文档
3. 部署仓做最小验证（启动、`/health`、OneBot 连接）

请勿把部署仓私有数据反向带回开发仓。

---

## 8. 常见错误与避免方式

- 直接推 `main`：用分支保护 + PR 强制约束
- 大分支长期不合并：拆小 PR，减少冲突
- CI 红了还合并：必需检查设为 required
- 修复线上问题直接改历史：统一走 `revert` + PR
- 开发仓与部署仓混用：严格按仓库角色操作

