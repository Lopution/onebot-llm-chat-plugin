# Release Process

本文件定义本项目推荐的 Git 分支与发版流程，目标是：

- `main` 始终可运行、可发布
- 任何发布都可追溯（commit + tag）
- 出问题可快速回滚（revert 或 tag 回退）

## Versioning

使用语义化版本：

- `MAJOR.MINOR.PATCH`
- Git tag 格式：`vMAJOR.MINOR.PATCH`

示例：`v0.1.0`

### 如何选择版本号

- `PATCH`：只修 bug、修文档、性能/日志改进等，不改变对外行为
- `MINOR`：新增功能但保持兼容（env 键名、OneBot 路径、默认行为不破坏）
- `MAJOR`：破坏兼容（需要在 Release Notes 明确 BREAKING CHANGE）

## Branch Model（推荐）

- `main`：永远保持可运行、可发布
  - 建议通过 PR 合并进入 `main`（不要直接 push）
- `feature/<topic>`：开发新功能（合并后删除）
- `fix/<bug>`：修复问题（合并后删除）
- `release/<version>`（可选）：需要“冻结 + 只修 bug”时创建

合并策略建议使用 GitHub 的 **Squash merge**，让每个 PR 对应 `main` 上一个提交，便于回滚与追溯。

## Release Steps

推荐按以下步骤发布（适用于 GitHub Actions 自动发布）：

1. 确认 `main` 是干净状态并通过测试：`pytest -q`。
2. 更新 `pyproject.toml` 中 `project.version`（只改版本号，不夹带其它大改动）。
3. （可选）补充发布说明：
   - GitHub Release Notes（自动生成）
   - 或更新 `docs/releases/vX.Y.Z.md`（如果你维护手写发布说明）
4. 提交并推送到 `main`。
5. 创建并推送 tag：

```bash
git tag v0.1.0
git push origin v0.1.0
```

6. GitHub Actions 自动执行 `release.yml`：
   - 校验 tag 与 `project.version` 一致
   - 运行测试
   - 生成源码压缩包
   - 创建 GitHub Release 并上传资产

## Release Artifacts

- `onebot-llm-chat-plugin-vX.Y.Z-source.tar.gz`
- `onebot-llm-chat-plugin-vX.Y.Z-source.zip`

## Hotfix（紧急修复）

当线上出现严重问题且需要快速发布：

1. 从 `main` 切 `fix/<bug>`：
   - 修复问题
   - 补最小回归测试（能覆盖这次 bug 的复现路径）
2. 合并回 `main`
3. 直接发一个 `PATCH` 版本（递增 `X.Y.(Z+1)`）

## Rollback

若发布失败：

1. 修复问题并提交到主分支。
2. 删除错误 tag：

```bash
git tag -d v0.1.0
git push --delete origin v0.1.0
```

3. 重新打新 tag（建议递增 patch 版本）并发布。

如果发布后发现行为回归，优先使用 `git revert <sha>` 回滚变更（不要改写已 push 的公共历史）。
