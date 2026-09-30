# Changelog

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本遵循[语义化版本](https://semver.org/lang/zh-CN/)。

## [0.1.2] - 2026-09-29

### Added

- CI：Actions SHA 全固定、覆盖率棘轮 65、pip-audit 依赖扫描、CycloneDX SBOM + PEP 740 provenance
- 治理：CHANGELOG / CONTRIBUTING / issue-PR 模板 / CODEOWNERS

## [Unreleased]

## [0.1.4] - 2026-09-30

### Added

- MCP Registry 元数据：server.json（io.github 命名 + pypi 包引用 + stdio transport）与
  `registry-publish.yml`（GitHub OIDC 免 token，等 PyPI 上线后自动登记）
- README 加 `mcp-name` 所有权标记（registry 校验读 PyPI 描述）

## [0.1.3] - 2026-09-30

### Added

- CI：ruff + bandit lint job（dev extras + [tool.ruff] 配置，uv.lock 锁定 lint 工具版本）
- 测试：35 → 111 例，覆盖率 69% → 99%（esq_validator 分支变异电池 / builder 校验与 autofix 缺口 / server 工具体 / client MockTransport 往返），覆盖率棘轮 65 → 97

### Fixed

- 清理误跟踪的 .coverage 产物（进 .gitignore）

## [0.1.1] - 2026-09-28

### Changed

- 补全 classifiers/keywords 提升发现性
- publish 工作流加测试门禁 + CI 矩阵（ubuntu/windows）

## [0.1.0] - 2026-09-28

### Added

- FastMCP server：build(auto_fix) → validate(双轨) → upload/publish 工具链
- kajweb 词表解析（wordRank 排序）与热点词频统计
- PyInstaller onefile 打包（Windows exe，随 GitHub release 分发）
- PyPI 发布（Trusted Publishing/OIDC）+ MIT LICENSE + 仓库元数据
- CI：ubuntu/windows 矩阵 + 覆盖率度量 + pip-audit 依赖扫描（本次补齐）
