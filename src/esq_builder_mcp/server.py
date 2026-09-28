"""ESQ Builder MCP server。

把 esq-question-bank-import 技能的确定性环节工具化:
build → validate → upload/publish + 词表分析。
工具 docstring 即 LLM 使用手册, 技能里的坑已固化进实现。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from .builder import build_esq_package
from .client import upload_and_publish
from .validator import validate_package
from .wordlist import hot_words, parse_wordlist

mcp = FastMCP(
    "esq-builder",
    instructions=(
        "ESQ 1.0 题库包工具链（墨题刷题机）。推荐流程: build_esq_package → validate_package → "
        "upload_and_publish。构造时注意: packageId/paperKey/unitKey/questionKey 必须纯 ASCII "
        "[A-Za-z0-9._:-]（如 cn.gaokao.cloze.y2021.u1）; cloze 空位用双花括号 {{blank:N}}。"
        "若不确定键是否合规, esq_build_package 传 auto_fix=true 可自动重建非法键并同步答案映射。"
        "上传/发布前需先启动刷题机后端。"
    ),
)


@mcp.tool
def esq_build_package(
    manifest: dict[str, Any],
    papers: list[dict[str, Any]],
    answers: dict[str, Any],
    output_path: str,
    auto_fix: bool = False,
) -> dict:
    """校验并构建 ESQ 1.0 题库包 ZIP。

    Args:
        manifest: {packageId, contentVersion, title, subject, publisher, license:{notice}, source:{description}}
        papers: [{paperKey, year, units:[{unitKey, type(cloze|reading|part_b), title, sequence, passage?, candidates?, questions:[...]}]}]
            - cloze: passage.blocks[].text 用 {{blank:N}} 双花括号标记空位（不是单花括号!）; 词库题用 unit.candidates=[{key:"A",content:"..."}], questions 不写 options
            - reading: questions 写 options=[{key:"A",content:"..."}]
            - question: {questionKey, number, type:"single_choice", stem, score}
        answers: {paperKey: {questionKey: {correctOption:"B", score: 2}}} —— 每空必填, correctOption 必须存在于该题选项
        output_path: 输出 ZIP 绝对路径
        auto_fix: true 时先自动修复机械性坑再构建——含中文的 externalKey 重建为
            cn.xxx.y2021.u1 风格（answers 键同步改名）、单花括号 {blank:N} 转双花括号、
            缺失 sequence 补默认值。修复明细在返回值 fixes 数组; 判断性问题（空位数≠题数、
            答案不在选项中）仍会报错。默认 false（拒绝 + 可行动错误）。

    Returns:
        {ok, zip_path, totals, errors, fixes, warnings}。ok=false 时 errors 数组给出每个错误的 path 和修复方法。
    """
    return build_esq_package(manifest, papers, answers, output_path, auto_fix=auto_fix)


@mcp.tool
def esq_validate_package(zip_path: str, validator_path: str | None = None) -> dict:
    """校验 ESQ 包（默认内置校验器, 与刷题机官方 esq.py 同规则）。

    Args:
        zip_path: ESQ 包路径
        validator_path: 可选, 指定后改用官方校验器 CLI（backend/tools/validate_question_bank.py）
            subprocess 对账——默认内置实现已与其保持一致并由一致性测试守护

    Returns:
        {valid, errors|totals, validator}。valid=true + 0 errors 才可上传。validator 字段标明用的哪条通道。
    """
    return validate_package(zip_path, validator_path)


@mcp.tool
def esq_upload_and_publish(
    zip_path: str,
    base_url: str = "http://127.0.0.1:8765",
    profile_id: int | None = None,
    publish: bool = True,
) -> dict:
    """上传 ESQ 包到刷题机后端并（可选）发布。上传前先 esq_validate_package。

    Args:
        zip_path: ESQ 包路径
        base_url: 后端地址（默认 http://127.0.0.1:8765, 需先启动后端）
        profile_id: 题库 profile（不传则用后端当前激活级别）
        publish: 是否发布（默认 true）

    Returns:
        {ok, job_id, uploaded, published}。publish 失败时上传已成功, 用返回的 job_id 提示重试。
    """
    return upload_and_publish(zip_path, base_url=base_url, profile_id=profile_id, publish=publish)


@mcp.tool
def esq_parse_wordlist(jsonl_path: str, top_n: int | None = None, level: str | None = None) -> dict:
    """解析 kajweb/dict 高频词表 JSONL（wordRank=真题词频排序）。

    Args:
        jsonl_path: kajweb book/*.zip 解压后的 JSONL 文件路径
        top_n: 只取前 N 个（如四级核心词取 1162）
        level: 标注级别名（如 "四级·高频"）

    Returns:
        {ok, count, words:[{rank, word, phonetic, translations, synonyms}]}
    """
    return parse_wordlist(jsonl_path, top_n=top_n, level=level)


@mcp.tool
def esq_hot_words(
    texts: list[Any],
    since_year: int = 2023,
    top_n: int = 300,
    extra_stopwords: list[str] | None = None,
) -> dict:
    """真题 passage 文本 → 热点词频统计（去停用词, [a-zA-Z][a-zA-Z'-]{3,}）。

    Args:
        texts: [{year: 2024, text: "passage 正文"}, ...]（或纯字符串列表）
        since_year: 只统计该年份之后的真题（默认 2023, 即"近两年热点"）
        top_n: 取前 N 个（默认 300）
        extra_stopwords: 额外停用词

    Returns:
        {ok, unique_words, hot_words:[{term, count}]}
    """
    return hot_words(texts, since_year=since_year, top_n=top_n, extra_stopwords=extra_stopwords)


def main() -> None:
    """stdio 入口（uvx esq-builder-mcp / pip 脚本）。"""
    if sys.platform == "win32":
        # Windows stdio MCP: 强制 UTF-8, 防 GBK 编码坑
        for stream_name in ("stdout", "stderr"):
            stream = getattr(sys, stream_name)
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8")
    mcp.run()


if __name__ == "__main__":
    main()
