"""ESQ 1.0 题库包构造器：结构校验 + 打包 ZIP。

入参结构（对 LLM 友好的最小面）:
  manifest: {packageId, contentVersion, title, subject, publisher, license: {notice}, source: {description}}
  papers:   [{paperKey, year, units: [{unitKey, type, title, sequence, passage?, candidates?, questions: [...]}]}]
  answers:  {<paperKey>: {<questionKey>: {"correctOption": "B", "score": 2}}}

manifest.papers[].path / answerPath 由本模块自动生成（papers/<paperKey>.json），
调用方不填路径, 少一个出错面。
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from .rules import (
    BLOCK_TYPES,
    MANIFEST_REQUIRED_TEXT_FIELDS,
    MAX_PACKAGE_BYTES,
    SEMVER_RE,
    UNIT_TYPES,
    check_key,
    check_option_key,
    check_passage_blanks,
)


def validate_inputs(manifest: dict[str, Any], papers: list[dict[str, Any]], answers: dict[str, Any]) -> list[dict[str, str]]:
    """构造前置校验。返回结构化错误列表（空列表 = 通过）。"""
    errors: list[dict[str, str]] = []

    if not isinstance(manifest, dict):
        return [{"path": "manifest", "reason": "必须是对象"}]
    if not isinstance(papers, list) or not papers:
        return [{"path": "papers", "reason": "至少包含一套试卷"}]
    if not isinstance(answers, dict):
        return [{"path": "answers", "reason": "必须是对象 {paperKey: {questionKey: {correctOption, score}}"}]

    # --- manifest ---
    if manifest.get("format", "esq") != "esq":
        errors.append({"path": "manifest.format", "reason": "必须为 esq（不填则自动补）"})
    if manifest.get("schemaVersion", "1.0") not in ("1.0", "1.1"):
        errors.append({"path": "manifest.schemaVersion", "reason": "仅支持 ESQ 1.0 / 1.1"})
    check_key(manifest.get("packageId"), "manifest.packageId", errors)
    content_version = manifest.get("contentVersion")
    if not isinstance(content_version, str) or not SEMVER_RE.fullmatch(content_version):
        errors.append({"path": "manifest.contentVersion", "reason": f"必须是语义化版本号（如 1.0.0），当前值: {content_version!r}"})
    for field in MANIFEST_REQUIRED_TEXT_FIELDS:
        value = manifest.get(field, "")
        if not isinstance(value, str) or not value.strip():
            errors.append({"path": f"manifest.{field}", "reason": "必填且不能为空白"})
    license_data = manifest.get("license")
    if not isinstance(license_data, dict) or not str(license_data.get("notice", "")).strip():
        errors.append({"path": "manifest.license.notice", "reason": "必填使用声明（license.notice）"})
    source = manifest.get("source")
    if not isinstance(source, dict) or not str(source.get("description", "")).strip():
        errors.append({"path": "manifest.source.description", "reason": "必填来源说明（source.description）"})

    # --- papers / units / questions / answers 交叉 ---
    seen_paper_keys: set[str] = set()
    for paper_index, paper in enumerate(papers):
        if not isinstance(paper, dict):
            errors.append({"path": f"papers[{paper_index}]", "reason": "必须是对象"})
            continue
        paper_key = paper.get("paperKey", "?")
        check_key(paper.get("paperKey"), f"papers[{paper_index}].paperKey", errors)
        if paper_key in seen_paper_keys:
            errors.append({"path": f"papers[{paper_index}].paperKey", "reason": f"试卷 ID 重复: {paper_key}"})
        seen_paper_keys.add(paper_key)
        if not isinstance(paper.get("year"), int):
            errors.append({"path": f"papers.{paper_key}.year", "reason": "必须是整数年份"})

        paper_answers = answers.get(paper_key, {})
        seen_question_keys: set[str] = set()
        for unit_index, unit in enumerate(paper.get("units", [])):
            unit_key = unit.get("unitKey", "?")
            unit_label = f"papers.{paper_key}.units[{unit_index}]"
            check_key(unit.get("unitKey"), f"{unit_label}.unitKey", errors)
            if unit.get("type") not in UNIT_TYPES:
                errors.append({"path": f"{unit_label}.type", "reason": f"必须是 {sorted(UNIT_TYPES)} 之一，当前值: {unit.get('type')!r}"})
            if not isinstance(unit.get("sequence"), int):
                errors.append({"path": f"{unit_label}.sequence", "reason": "必须是整数"})

            for block_index, block in enumerate(unit.get("passage", {}).get("blocks", []) if isinstance(unit.get("passage"), dict) else []):
                if isinstance(block, dict) and block.get("type", "paragraph") not in BLOCK_TYPES:
                    errors.append(
                        {
                            "path": f"{unit_label}.passage.blocks[{block_index}].type",
                            "reason": f"必须是 {sorted(BLOCK_TYPES)} 之一",
                        }
                    )

            # 词库题 candidates: key 单大写字母
            candidate_keys: set[str] = set()
            for candidate in unit.get("candidates", []) or []:
                if isinstance(candidate, dict) and check_option_key(candidate.get("key"), f"{unit_label}.candidates.key", errors):
                    candidate_keys.add(candidate["key"])

            questions = unit.get("questions", [])
            for question_index, question in enumerate(questions):
                question_key = question.get("questionKey", "?")
                question_label = f"{unit_label}.questions[{question_index}]"
                check_key(question.get("questionKey"), f"{question_label}.questionKey", errors)
                if question_key in seen_question_keys:
                    errors.append({"path": f"{question_label}.questionKey", "reason": f"题目 ID 重复: {question_key}"})
                seen_question_keys.add(question_key)
                if not isinstance(question.get("stem"), str) or not question["stem"].strip():
                    errors.append({"path": f"{question_label}.stem", "reason": "题干必填"})

                option_keys = set()
                options = question.get("options")
                if options:
                    for option in options:
                        if isinstance(option, dict) and check_option_key(option.get("key"), f"{question_label}.options.key", errors):
                            option_keys.add(option["key"])

                # 答案: 每空必填, correctOption 必须存在于该题选项
                answer = paper_answers.get(question_key)
                if not isinstance(answer, dict) or not answer.get("correctOption"):
                    errors.append(
                        {
                            "path": f"answers.{paper_key}.{question_key}.correctOption",
                            "reason": "每空必填 correctOption（ESQ 铁律: answers 与题目一一对应）",
                        }
                    )
                    continue
                valid_targets = option_keys or candidate_keys  # 词库题用 candidates
                if valid_targets and answer["correctOption"] not in valid_targets:
                    errors.append(
                        {
                            "path": f"answers.{paper_key}.{question_key}.correctOption",
                            "reason": f"答案 {answer['correctOption']!r} 不在该题选项 {sorted(valid_targets)} 中",
                        }
                    )

            # cloze: 空位数应等于题数
            if unit.get("type") == "cloze":
                blanks = check_passage_blanks(str(paper_key), unit, errors)
                if blanks and blanks != len(questions):
                    errors.append(
                        {
                            "path": f"{unit_label}.passage",
                            "reason": f"cloze 空位数({blanks})与题数({len(questions)})不一致",
                        }
                    )

    # answers 里出现未知 questionKey → 提示（可能是笔误）
    for paper_key, paper_answers in answers.items():
        if paper_key not in seen_paper_keys:
            errors.append({"path": f"answers.{paper_key}", "reason": "answers 引用了不存在的 paperKey"})

    return errors


def _build_paper_file(paper: dict[str, Any]) -> dict[str, Any]:
    # 官方校验器要求每个 block 有 blockKey（3-200 位安全标识）——缺省自动补 p{index}
    import copy as _copy

    paper = _copy.deepcopy(paper)
    for unit in paper["units"]:
        passage = unit.get("passage") or {}
        for index, block in enumerate(passage.get("blocks", [])):
            if isinstance(block, dict) and not block.get("blockKey"):
                block["blockKey"] = f"block-{index}"  # 官方规则 3-200 位, p0 这种 2 位会挂
    paper_file = {"paperKey": paper["paperKey"], "year": paper["year"], "units": paper["units"]}
    if paper.get("title"):
        paper_file["title"] = paper["title"]
    return paper_file


def _build_answer_file(paper_key: str, answers: dict[str, Any]) -> dict[str, Any]:
    return {"paperKey": paper_key, "answers": answers}


def build_esq_package(
    manifest: dict[str, Any],
    papers: list[dict[str, Any]],
    answers: dict[str, Any],
    output_path: str,
) -> dict[str, Any]:
    """校验并打包 ESQ 1.0 ZIP。返回 {ok, zip_path, totals, errors}。"""
    errors = validate_inputs(manifest, papers, answers)
    if errors:
        return {"ok": False, "errors": errors}

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    full_manifest = {
        "format": "esq",
        "schemaVersion": manifest.get("schemaVersion", "1.0"),
        **manifest,
        "papers": [
            {
                "paperKey": paper["paperKey"],
                "year": paper["year"],
                "path": f"papers/{paper['paperKey']}.json",
                "answerPath": f"answers/{paper['paperKey']}.json",
            }
            for paper in papers
        ],
    }

    totals = {"papers": len(papers), "units": 0, "questions": 0}
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(full_manifest, ensure_ascii=False, indent=2))
        for paper in papers:
            totals["units"] += len(paper["units"])
            totals["questions"] += sum(len(unit.get("questions", [])) for unit in paper["units"])
            zf.writestr(
                f"papers/{paper['paperKey']}.json",
                json.dumps(_build_paper_file(paper), ensure_ascii=False, indent=2),
            )
            zf.writestr(
                f"answers/{paper['paperKey']}.json",
                json.dumps(_build_answer_file(paper["paperKey"], answers.get(paper["paperKey"], {})), ensure_ascii=False, indent=2),
            )

    size = out.stat().st_size
    return {
        "ok": True,
        "zip_path": str(out),
        "size_bytes": size,
        "size_ok": size <= MAX_PACKAGE_BYTES,
        "totals": totals,
        "errors": [],
    }
