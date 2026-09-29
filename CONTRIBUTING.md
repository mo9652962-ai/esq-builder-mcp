# 贡献指南

## 开发环境

```bash
git clone https://github.com/mo9652962-ai/esq-builder-mcp.git && cd esq-builder-mcp
uv sync --extra dev
uv run pytest -q --cov=esq_builder_mcp --cov-report=term-missing
```

## 约定

- **Actions SHA 固定**：`.github/workflows/` 内所有 `uses:` 必须钉全量 commit SHA。
- **覆盖率只升不降**：CI 输出覆盖率（当前度量阶段，门槛待基线稳定后棘轮）。
- **双轨校验**：validate 工具与官方 esq.py 校验器保持一致，改动须同步测试。
- **发布**：bump `pyproject` version → 打 `v*` tag → trusted publishing 自动发 PyPI。

## 提交

PR 前跑 `uv run pytest -q`；commit message 用祈使句。
