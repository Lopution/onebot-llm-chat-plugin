# Release Process

## Versioning

使用语义化版本：

- `MAJOR.MINOR.PATCH`
- Git tag 格式：`vMAJOR.MINOR.PATCH`

示例：`v0.1.0`

## Release Steps

1. 确认主分支 `pytest -q` 通过。
2. 更新 `pyproject.toml` 中 `project.version`。
3. 提交版本变更并推送。
4. 创建并推送 tag：

```bash
git tag v0.1.0
git push origin v0.1.0
```

5. GitHub Actions 自动执行 `release.yml`：
   - 校验 tag 与 `project.version` 一致
   - 运行测试
   - 生成源码压缩包
   - 创建 GitHub Release 并上传资产

## Release Artifacts

- `mika-chat-core-vX.Y.Z-source.tar.gz`
- `mika-chat-core-vX.Y.Z-source.zip`

## Rollback

若发布失败：

1. 修复问题并提交到主分支。
2. 删除错误 tag：

```bash
git tag -d v0.1.0
git push --delete origin v0.1.0
```

3. 重新打新 tag（建议递增 patch 版本）并发布。
