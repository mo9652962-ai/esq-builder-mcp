# esq-builder-mcp

ESQ 1.0 题库包 MCP 工具链：把 [esq-question-bank-import] 技能的确定性环节（构建/校验/上传/词表分析）固化为 MCP 工具，供任意 MCP 客户端（ZCode / Claude Desktop / Codex 等）调用。

## 为什么

技能（SKILL.md）传的是流程知识，LLM 每次执行都可能踩坑（ASCII key、双花括号、上传路径 405……）。本 server 把这些坑固化进工具代码——调用方不会再遇到它们。

| 工具 | 作用 | 固化的坑 |
|:---|:---|:---|
| `esq_build_package` | 校验 + 打包 ESQ ZIP（可选 `auto_fix`） | externalKey 纯 ASCII 3-200 位；`{{blank:N}}` 双花括号；option/candidates key 单大写字母；correctOption 必须存在于选项；cloze 空位数=题数；manifest 必填字段 + semver |
| `esq_validate_package` | 校验 ESQ 包（默认内置校验器，可选官方 CLI 对账） | 双轨校验（见下） |
| `esq_upload_and_publish` | 上传 + 发布到刷题机后端 | 路径写死 `/api/question-banks/imports`（`/upload` 会 405）；503 重试 3 次间隔 10s；publish 失败时提示用 job_id 单独重试 |
| `esq_parse_wordlist` | kajweb/dict JSONL 高频词解析（.jsonl 或 book zip） | 逐行 json.loads（整文件 load 报 Extra data）；wordRank 排序 |
| `esq_hot_words` | 真题 passage 热点词统计 | 近两年过滤；去停用词；`[a-zA-Z][a-zA-Z'-]{3,}` |

### auto_fix：机械性坑自动修复

`esq_build_package(auto_fix=true)` 在校验前自动修复「纯机械」的坑，修复明细记录在返回值 `fixes` 数组（审计）：

- 含中文/非法字符的 packageId/paperKey/unitKey/questionKey → `cn.xxx.y2021.u1` 风格重建，**answers 两级键自动同步改名**
- 单花括号 `{blank:N}` → 双花括号 `{{blank:N}}`
- 缺失的 `unit.sequence` 补 index+1；不达标 blockKey（如 2 位的 `p1`）归一为 `block-{index}`

判断性问题（空位数≠题数、答案不在选项中）**不会**被静默修复，仍走「拒绝 + 可行动错误」。默认 `false` 保持严格行为。

### 双轨校验

`esq_validate_package` 有两条通道，返回值 `validator` 字段标明所用通道：

- **默认：内置校验器**（`esq_validator.py`，vendor 自 backend/app/services/esq.py 校验子集，import 调用）——零外部依赖，PyPI/uvx/PyInstaller 分发可用；
- **对账：官方 CLI**——显式传 `validator_path` 或设 `ESQ_VALIDATOR_PATH` 时走 subprocess 调官方校验器。

两条通道的一致性由 `tests/test_validator_conformance.py` 守护（本机有刷题机仓库时自动执行；后端校验逻辑变更后先跑它再同步 vendored 副本）。

## 安装与运行

```bash
cd D:/esq-builder-mcp
uv venv && uv pip install -e ".[dev]"
uv run esq-builder-mcp          # stdio 模式
```

## 注册到 MCP 客户端

ZCode（`~/.zcode/cli/config.json` → mcpServers）或其他客户端：

```json
{
  "mcpServers": {
    "esq-builder": {
      "command": "uv",
      "args": ["--directory", "D:/esq-builder-mcp", "run", "esq-builder-mcp"]
    }
  }
}
```

> Windows 下 MCP 命令参数一律用正斜杠路径（Codex config.toml 转义坑的同款规避）。

## 环境变量

| 变量 | 默认 | 说明 |
|:---|:---|:---|
| `ESQ_VALIDATOR_PATH` | （未设） | 设定后 `esq_validate_package` 改走官方校验器 CLI（对账/仲裁通道）；默认内置校验器，不需要此变量 |

## 测试

```bash
uv run pytest -v          # 35 项；含 vendored vs 官方 CLI 一致性对账（无刷题机环境自动 skip）
```

## 后续演进

- ~~**schema 包抽取**~~：已用 vendored 校验器（`esq_validator.py`）实现同目标——本包自包含、可独立分发；一致性测试代替单副本保证零漂移。若后续把 backend 的 esq.py 抽成独立 `esq-schema` PyPI 包，可直接替换 vendored 副本。
- **ESQ 1.1 examType**：manifest.papers[].examType 已在官方校验器支持，构造器暂未暴露。
- **发布到 PyPI**：vendored 校验器落地后已无外部路径依赖，`uvx esq-builder-mcp` 一行接入可期；Windows 单文件 exe 走 PyInstaller。

## 与技能的关系

- 上游技能：`~/.agents/skills/esq-question-bank-import/SKILL.md`（流程与数据源）
- 本 server 是其「确定性环节」的工具化；AI 标注答案（基元律动）等 LLM 判断环节仍在技能侧。

## 演进记录

- 2026-09-28：校验改双轨（vendored 默认 + 官方 CLI 对账），解除对刷题机仓库路径的运行时依赖，PyPI 分发解锁；`esq_build_package` 增加 `auto_fix` 通道；`esq_parse_wordlist` 支持 book zip 输入。
