"""ESQ 1.0 题库包构造器：结构校验 + 打包 ZIP。

入参结构（对 LLM 友好的最小面）:
  manifest: {packageId, contentVersion, title, subject, publisher, license: {notice}, source: {description}}
  papers:   [{paperKey, year, units: [{unitKey, type, title, sequence, passage?, candidates?, questions: [...]}]}]
  answers:  {<paperKey>: {<questionKey>: {"correctOption": "B", "score": 2}}}

manifest.papers[].path / answerPath 由本模块自动生成（papers/<paperKey>.json），
调用方不填路径, 少一个出错面。
"""

from __future__ import annotations

import copy
import json
import re
import zipfile
from pathlib import Path
from typing import Any

from .keys import ensure_external_key
from .rules import (
    BLOCK_TYPES,
    KEY_RE,
    MANIFEST_REQUIRED_TEXT_FIELDS,
    MAX_PACKAGE_BYTES,
    SEMVER_RE,
    UNIT_TYPES,
    check_key,
    check_option_key,
    check_passage_blanks,
)

# 包文件必须双花括号；单花括号是库内存储格式（高频坑）。两侧非花括号才补，避免重复修复
SINGLE_BLANK_FIX_RE = re.compile(r"(?<!\{)\{blank:(\d+)\}(?!\})")


def apply_autofix(
    manifest: dict[str, Any],
    papers: list[dict[str, Any]],
    answers: dict[str, Any],
) -> tuple[list[dict[str, str]], list[str]]:
    """就地修复机械性坑（判断性问题留给 validate_inputs）。返回 (fixes, warnings)。

    修复项（全部在 fixes 留痕）:
    - 含中文/非法字符的 packageId/paperKey/unitKey/questionKey → cn.xxx.y2021.u1 风格重建
      （questionKey 重建后 answers 的键自动同步改名）
    - 单花括号 {blank:N} → 双花括号 {{blank:N}}
    - 缺失的 unit.sequence 补 index+1
    """
    fixes: list[dict[str, str]] = []
    warnings: list[str] = []
    subject_hint = manifest.get("subject") or "english"

    original_package_id = str(manifest.get("packageId") or "")
    new_package_id, changed = ensure_external_key(manifest.get("packageId"), ("cn", subject_hint, "pkg"))
    if changed:
        fixes.append({"field": "manifest.packageId", "old": original_package_id, "new": new_package_id})
        manifest["packageId"] = new_package_id

    for paper_index, paper in enumerate(papers):
        if not isinstance(paper, dict):
            continue
        original_paper_key = str(paper.get("paperKey") or "")
        new_paper_key, changed = ensure_external_key(
            paper.get("paperKey"), ("cn", subject_hint, f"y{paper.get('year')}", f"p{paper_index + 1}")
        )
        if changed:
            fixes.append({"field": f"papers[{paper_index}].paperKey", "old": original_paper_key, "new": new_paper_key})
        paper["paperKey"] = new_paper_key

        question_renames: dict[str, str] = {}
        for unit_index, unit in enumerate(paper.get("units") or []):
            if not isinstance(unit, dict):
                continue
            original_unit_key = str(unit.get("unitKey") or "")
            new_unit_key, changed = ensure_external_key(unit.get("unitKey"), (new_paper_key, f"u{unit_index + 1}"))
            if changed:
                fixes.append({"field": f"papers[{paper_index}].units[{unit_index}].unitKey", "old": original_unit_key, "new": new_unit_key})
            unit["unitKey"] = new_unit_key

            if not isinstance(unit.get("sequence"), int):
                fixes.append(
                    {"field": f"papers[{paper_index}].units[{unit_index}].sequence", "old": str(unit.get("sequence")), "new": str(unit_index + 1)}
                )
                unit["sequence"] = unit_index + 1

            for block_index, block in enumerate((unit.get("passage") or {}).get("blocks") or []):
                if not isinstance(block, dict):
                    continue
                if isinstance(block.get("text"), str):
                    fixed_text, count = SINGLE_BLANK_FIX_RE.subn(r"{{blank:\1}}", block["text"])
                    if count:
                        fixes.append(
                            {
                                "field": f"papers[{paper_index}].units[{unit_index}].passage.blocks[{block_index}].text",
                                "old": "单花括号 {blank:N}",
                                "new": f"双花括号 {{{{blank:N}}}} × {count}",
                            }
                        )
                        block["text"] = fixed_text

            for question_index, question in enumerate(unit.get("questions") or []):
                if not isinstance(question, dict):
                    continue
                original_question_key = str(question.get("questionKey") or "")
                new_question_key, changed = ensure_external_key(
                    question.get("questionKey"), (new_unit_key, f"q{question.get('number', question_index + 1)}")
                )
                if changed:
                    fixes.append(
                        {"field": f"papers[{paper_index}].units[{unit_index}].questions[{question_index}].questionKey", "old": original_question_key, "new": new_question_key}
                    )
                    question_renames[original_question_key] = new_question_key
                question["questionKey"] = new_question_key

        # answers 键同步: paperKey 与 questionKey 两级
        paper_answers = answers.pop(original_paper_key, None)
        if paper_answers is None:
            paper_answers = answers.get(new_paper_key) or {}
        elif original_paper_key != new_paper_key:
            answers.pop(new_paper_key, None)  # 防御: 两键并存时以原始键内容为准
        remapped: dict[str, Any] = {}
        for question_key, answer in (paper_answers or {}).items():
            new_key = question_renames.get(question_key, question_key)
            if new_key != question_key:
                fixes.append({"field": f"answers[{new_paper_key}].{question_key}", "old": question_key, "new": new_key})
            remapped[new_key] = answer
        answers[new_paper_key] = remapped

    return fixes, warnings


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
    # 官方校验器要求每个 blockKey 是 3-200 位安全标识——缺失或不达标（如 2 位的 p0）都重建
    import copy as _copy

    paper = _copy.deepcopy(paper)
    for unit in paper["units"]:
        passage = unit.get("passage") or {}
        for index, block in enumerate(passage.get("blocks", [])):
            if isinstance(block, dict) and not KEY_RE.fullmatch(str(block.get("blockKey") or "")):
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
    auto_fix: bool = False,
) -> dict[str, Any]:
    """校验并打包 ESQ 1.0 ZIP。返回 {ok, zip_path, totals, errors, fixes, warnings}。

    auto_fix=True 时先就地修复机械性坑（非法 externalKey、单花括号空位、缺失 sequence，
    答案键同步改名），修复记录在 fixes；判断性问题（空位数≠题数、答案不在选项中）
    仍交给 validate_inputs 报错。默认 False 保持「拒绝 + 可行动错误」行为。
    """
    fixes: list[dict[str, str]] = []
    warnings: list[str] = []
    if auto_fix:
        manifest = copy.deepcopy(manifest)
        papers = copy.deepcopy(papers)
        answers = copy.deepcopy(answers)
        fixes, warnings = apply_autofix(manifest, papers, answers)

    errors = validate_inputs(manifest, papers, answers)
    if errors:
        return {"ok": False, "errors": errors, "fixes": fixes, "warnings": warnings}

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
        "fixes": fixes,
        "warnings": warnings,
    }
