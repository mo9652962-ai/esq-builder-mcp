# Security

## Mimosa deep scan（2026-09-28）

| 项 | 值 |
|:---|:---|
| scanId | `scan-2026-09-28T05-05-47.121Z-bf431a8d379c` |
| seal | `sha256:59a2dddcee69835dc765dd962134b975d6a0144f1fbfb2e2e910476bce4a03bb` |
| depth | deep |
| findings | **0**（high 0 / medium 0 / low 0 / info 0 / businessLogic 0） |
| run status | **inconclusive** |
| verdict effect | none |

### 覆盖说明（如实）

- 结论为 inconclusive 而非 clean：调用图部分不完整（动态派发/超出分析规模），跨文件可达性可能不完整；威胁模型阶段 partial（MCP 工具经 `@mcp.tool` 装饰器动态注册，静态分析未识别为 entry points）。
- 即：已审查范围内零发现，但不是全量安全认证。
- 复核：扫描工件（含封印）在 `~/.mimosa/security-scans/project-82273bf59b5299a4d1ccbe2f/scan-2026-09-28T05-05-47.121Z-bf431a8d379c/`。

### 安全边界备注

- `esq_upload_and_publish` 仅向参数指定的 base_url（默认本机 8765）发数据；无遥测、无外部上传。
- `esq_validate_package` 以 subprocess 调用本地校验器，路径默认刷题机仓库、可用 `ESQ_VALIDATOR_PATH` 覆盖——部署者应确保该变量指向可信路径。
- 词表工具只读本地文件；`build_esq_package` 写文件到调用方指定的 output_path。
