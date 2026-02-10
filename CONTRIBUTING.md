# Contributing Guide（开发与维护约定）

## Prerequisites

- Python 3.10+
- 建议使用虚拟环境

## Local Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Git Workflow（分支 / 提交 / 合并）

### Branch Model（推荐）

- `main`: 永远保持可运行、可发布
  - 不建议直接 push 到 `main`，统一走 PR
- `feature/<topic>`: 新功能分支（合并后删除）
- `fix/<bug>`: Bug 修复分支（合并后删除）
- `release/<version>`: 需要“冻结 + 只修 bug”时才创建（可选）

建议：一个 PR 对应一个明确目的，避免“功能 + 重构 + 修 bug”混在一起。

### Commit Messages（推荐 Conventional Commits）

使用约定式提交让历史可读、可自动生成 Release Notes：

- `feat: ...` 新功能
- `fix: ...` 修 bug
- `refactor: ...` 重构（不改行为）
- `docs: ...` 文档
- `test: ...` 测试
- `chore: ...` 杂项（CI、脚本等）

破坏性变更：使用 `feat!: ...` 或在提交信息中包含 `BREAKING CHANGE: ...`。

### PR Merge Strategy

- 推荐使用 **Squash merge**：保持主分支线性历史，回滚更简单
- PR 需要：
  - 说明行为变化与兼容性影响
  - 本地与 CI 测试通过（至少 `pytest -q`）

## Development Rules（项目约束）

- 尽量保持向后兼容，不随意修改已有 env 键名与 OneBot 路径。
- 缺失适配器能力时优先降级处理，不要让主流程崩溃。
- 新功能必须补充最小可回归测试。
- 文档与默认配置值必须同步更新。

## Test

```bash
pytest -q
```

## Release

发布流程见：`docs/release-process.md`。

## Pull Request Checklist

- [ ] 本地 `pytest -q` 通过
- [ ] 变更点已更新 README 或 docs（如需要）
- [ ] 不包含私密配置、运行态数据或模型文件
- [ ] 变更说明聚焦行为差异与兼容性影响
