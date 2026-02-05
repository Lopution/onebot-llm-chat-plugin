# Contributing Guide

## Prerequisites

- Python 3.10+
- 建议使用虚拟环境

## Local Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Development Rules

- 尽量保持向后兼容，不随意修改已有 env 键名与 OneBot 路径。
- 缺失适配器能力时优先降级处理，不要让主流程崩溃。
- 新功能必须补充最小可回归测试。
- 文档与默认配置值必须同步更新。

## Test

```bash
pytest -q
```

## Pull Request Checklist

- [ ] 本地 `pytest -q` 通过
- [ ] 变更点已更新 README 或 docs（如需要）
- [ ] 不包含私密配置、运行态数据或模型文件
- [ ] 变更说明聚焦行为差异与兼容性影响
