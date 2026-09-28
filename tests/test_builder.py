"""builder 校验规则测试: 技能里踩过的坑逐条固化。"""

from __future__ import annotations

import copy

from esq_builder_mcp.builder import build_esq_package, validate_inputs


def _one_error(errors: list[dict], needle: str) -> dict | None:
    return next((e for e in errors if needle in e["path"] or needle in e["reason"]), None)


def test_valid_package_builds(tmp_path, manifest, papers, answers):
    result = build_esq_package(manifest, papers, answers, str(tmp_path / "out.esq"))
    assert result["ok"], result["errors"]
    assert result["totals"] == {"papers": 2, "units": 2, "questions": 3}
    assert result["size_ok"]


def test_chinese_key_rejected(tmp_path, manifest, papers, answers):
    papers = copy.deepcopy(papers)
    papers[0]["paperKey"] = "gaokao-cloze-2021-新课标Ⅰ"  # 技能实测坑: 含中文直接失败
    errors = validate_inputs(manifest, papers, answers)
    assert _one_error(errors, "paperKey"), errors
    result = build_esq_package(manifest, papers, answers, str(tmp_path / "x.esq"))
    assert not result["ok"]


def test_single_brace_blank_rejected(manifest, papers, answers):
    papers = copy.deepcopy(papers)
    papers[1]["units"][0]["passage"]["blocks"][0]["text"] = "I {blank:1} a cat."  # 库内格式, 包里必须双括号
    errors = validate_inputs(manifest, papers, answers)
    assert _one_error(errors, "双花括号")


def test_blank_count_mismatch(manifest, papers, answers):
    papers = copy.deepcopy(papers)
    papers[1]["units"][0]["passage"]["blocks"][0]["text"] = "I {{blank:1}} a cat."  # 1 空 2 题
    errors = validate_inputs(manifest, papers, answers)
    assert _one_error(errors, "不一致")


def test_answer_option_mismatch(manifest, papers, answers):
    answers = copy.deepcopy(answers)
    answers["cn.test.reading.y2024"]["cn.test.reading.y2024.u1.q1"]["correctOption"] = "Z"
    errors = validate_inputs(manifest, papers, answers)
    assert _one_error(errors, "correctOption")


def test_missing_answer(manifest, papers):
    errors = validate_inputs(manifest, papers, {})
    assert _one_error(errors, "每空必填")


def test_lowercase_option_key(manifest, papers, answers):
    papers = copy.deepcopy(papers)
    papers[0]["units"][0]["questions"][0]["options"][0]["key"] = "a"
    errors = validate_inputs(manifest, papers, answers)
    assert _one_error(errors, "大写字母")


def test_candidates_used_when_no_options(manifest, candidates_paper):
    """词库题: questions 不写 options, correctOption 校验走 unit.candidates。"""
    papers = [candidates_paper]
    answers = {"cn.test.bank.y2024": {"cn.test.bank.y2024.u1.q1": {"correctOption": "A", "score": 1}}}
    assert validate_inputs(manifest, papers, answers) == []
    answers["cn.test.bank.y2024"]["cn.test.bank.y2024.u1.q1"]["correctOption"] = "C"
    assert _one_error(validate_inputs(manifest, papers, answers), "correctOption")


def test_manifest_required_fields(manifest, papers, answers):
    manifest = dict(manifest)
    del manifest["license"]
    errors = validate_inputs(manifest, papers, answers)
    assert _one_error(errors, "license")
