# esq-builder-mcp

ESQ 1.0 题库包 MCP 工具链：把 [esq-question-bank-import] 技能的确定性环节（构建/校验/上传/词表分析）固化为 MCP 工具，供任意 MCP 客户端（ZCode / Claude Desktop / Codex 等）调用。

## 为什么

技能（SKILL.md）传的是流程知识，LLM 每次执行都可能踩坑（ASCII key、双花括号、上传路径 405……）。本 server 把这些坑固化进工具代码——调用方不会再遇到它们。

| 工具 | 作用 | 固化的坑 |
|:---|:---|:---|
| `esq_build_package` | 校验 + 打包 ESQ ZIP | externalKey 纯 ASCII 3-200 位；`{{blank:N}}` 双花括号；option/candidates key 单大写字母；correctOption 必须存在于选项；cloze 空位数=题数；manifest 必填字段 + semver |
| `esq_validate_package` | 调刷题机官方校验器（backend/app/services/esq.py） | 不复制校验逻辑，subprocess 复用，零漂移 |
| `esq_upload_and_publish` | 上传 + 发布到刷题机后端 | 路径写死 `/api/question-banks/imports`（`/upload` 会 405）；503 重试 3 次间隔 10s；publish 失败时提示用 job_id 单独重试 |
| `esq_parse_wordlist` | kajweb/dict JSONL 高频词解析 | 逐行 json.loads（整文件 load 报 Extra data）；wordRank 排序 |
| `esq_hot_words` | 真题 passage 热点词统计 | 近两年过滤；去停用词；`[a-zA-Z][a-zA-Z'-]{3,}` |

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
| `ESQ_VALIDATOR_PATH` | `D:/english-multiple-choice-practice-machine/tools/validate_question_bank.py` | 官方校验器 CLI 位置 |

## 测试

```bash
uv run pytest -v          # 含真校验器联动测试（无刷题机环境自动 skip）
```

## 后续演进

- **schema 包抽取**：把 backend/app/services/esq.py 抽成独立 `esq-schema` PyPI 包，刷题机与本 server 共同依赖，彻底消除 subprocess。
- **ESQ 1.1 examType**：manifest.papers[].examType 已在官方校验器支持，构造器暂未暴露。
- **发布到 PyPI**：`uvx esq-builder-mcp` 一行接入；Windows 单文件 exe 走 PyInstaller。

## 与技能的关系

- 上游技能：`~/.agents/skills/esq-question-bank-import/SKILL.md`（流程与数据源）
- 本 server 是其「确定性环节」的工具化；AI 标注答案（基元律动）等 LLM 判断环节仍在技能侧。
