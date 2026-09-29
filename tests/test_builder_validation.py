"""builder 的 validate_inputs / apply_autofix 缺口分支与 _build_paper_file 细节。"""

from __future__ import annotations

import copy
import json
import zipfile

from esq_builder_mcp.builder import apply_autofix, build_esq_package, validate_inputs


def _one(errors: list[dict], needle: str) -> dict | None:
    return next((e for e in errors if needle in e["path"] or needle in e["reason"]), None)


# --- validate_inputs 顶层与 manifest 分支 ---

def test_top_level_type_guards(manifest, papers, answers):
    assert _one(validate_inputs("x", papers, answers), "manifest")
    assert _one(validate_inputs(manifest, [], answers), "papers")
    assert _one(validate_inputs(manifest, papers, "x"), "answers")


def test_manifest_field_errors(manifest, papers, answers):
    def m(**overrides) -> list[dict]:
        bad = dict(manifest)
        bad.update(overrides)
        return validate_inputs(bad, papers, answers)

    assert _one(m(format="esq2"), "manifest.format")
    assert _one(m(schemaVersion="2.0"), "manifest.schemaVersion")
    assert _one(m(contentVersion="1.0"), "contentVersion")
    assert _one(m(title=" "), "manifest.title")
    assert _one(m(source={"description": " "}), "source.description")


# --- papers / units / questions 交叉分支 ---

def test_paper_level_errors(manifest, papers, answers):
    dup = copy.deepcopy(papers)
    dup.append(dict(dup[0]))
    assert _one(validate_inputs(manifest, dup, answers), "试卷 ID 重复")

    bad_year = copy.deepcopy(papers)
    bad_year[0]["year"] = "2024"
    assert _one(validate_inputs(manifest, bad_year, answers), "必须是整数年份")

    junk = copy.deepcopy(papers)
    junk.append("not-a-dict")
    assert _one(validate_inputs(manifest, junk, answers), "必须是对象")


def test_unit_level_errors(manifest, papers, answers):
    cases = [
        ({"type": "clozeX"}, "必须是"),
        ({"sequence": "1"}, "sequence"),
        ({"passage": {"blocks": [{"type": "hologram", "text": "x"}]}}, "passage.blocks"),
    ]
    for overrides, needle in cases:
        mutated = copy.deepcopy(papers)
        mutated[0]["units"][0].update(overrides)
        assert _one(validate_inputs(manifest, mutated, answers), needle), overrides


def test_question_level_errors(manifest, papers, answers):
    dup = copy.deepcopy(papers)
    u = dup[0]["units"][0]
    u["questions"].append(dict(u["questions"][0]))
    assert _one(validate_inputs(manifest, dup, answers), "题目 ID 重复")

    empty_stem = copy.deepcopy(papers)
    empty_stem[0]["units"][0]["questions"][0]["stem"] = "  "
    assert _one(validate_inputs(manifest, empty_stem, answers), "题干必填")


def test_answer_errors_and_unknown_paper(manifest, papers, answers):
    missing_flag = copy.deepcopy(answers)
    missing_flag["cn.test.reading.y2024"]["cn.test.reading.y2024.u1.q1"] = {}
    assert _one(validate_inputs(manifest, papers, missing_flag), "每空必填")

    wrong_target = copy.deepcopy(answers)
    wrong_target["cn.test.reading.y2024"]["cn.test.reading.y2024.u1.q1"] = {"correctOption": "Z"}
    errors = validate_inputs(manifest, papers, wrong_target)
    assert _one(errors, "不在该题选项")

    ghost = dict(answers)
    ghost["cn.ghost.y1"] = {"cn.ghost.q1": {"correctOption": "A"}}
    assert _one(validate_inputs(manifest, papers, ghost), "不存在的 paperKey")


def test_cloze_blank_sequence_gap(manifest, papers, answers):
    mutated = copy.deepcopy(papers)
    mutated[1]["units"][0]["passage"]["blocks"][0]["text"] = (
        "I {{blank:1}} a cat. It {{blank:3}} cute."
    )
    errors = validate_inputs(manifest, mutated, answers)
    hit = _one(errors, "空位序号不连续")
    assert hit and "blank:2" in hit["reason"]


# --- apply_autofix 缺口分支 ---

def _fix(fixes: list[dict], needle: str) -> dict | None:
    return next((f for f in fixes if needle in f["field"]), None)


def test_autofix_rebuilds_package_id():
    manifest = {"packageId": "非法*id", "subject": "english"}
    fixes, _warnings = apply_autofix(manifest, [], {})
    assert _fix(fixes, "manifest.packageId")
    assert manifest["packageId"].startswith("cn.english.pkg")


def test_autofix_skips_junk_entries():
    manifest = {"packageId": "cn.ok.pkg", "subject": "english"}
    papers: list = ["junk"]
    fixes, _warnings = apply_autofix(manifest, papers, {})
    assert papers == ["junk"]
    assert fixes == []


def test_autofix_fills_missing_sequence_and_skips_bad_block():
    manifest = {"packageId": "cn.ok.pkg", "subject": "english"}
    papers = [{
        "paperKey": "cn.ok.y2024", "year": 2024,
        "units": [{
            "unitKey": "cn.ok.y2024.u1", "type": "cloze",
            "passage": {"blocks": ["junk", {"type": "paragraph", "text": "hi"}]},
            "questions": ["junk"],
        }],
    }]
    fixes, _warnings = apply_autofix(manifest, papers, {})
    assert papers[0]["units"][0]["sequence"] == 1
    assert _fix(fixes, "sequence")
    assert papers[0]["units"][0]["passage"]["blocks"][0] == "junk"
    assert papers[0]["units"][0]["questions"][0] == "junk"


def test_autofix_remaps_answer_keys():
    manifest = {"packageId": "cn.ok.pkg", "subject": "english"}
    papers = [{
        "paperKey": "坏-键", "year": 2024,
        "units": [{
            "unitKey": "u#1", "type": "cloze", "sequence": 1,
            "passage": {"blocks": [{"type": "paragraph", "text": "I {{blank:1}}."}]},
            "questions": [{
                "questionKey": "q#1", "number": 1, "type": "single_choice",
                "stem": "1", "options": [{"key": "A", "content": "x"}], "score": 1,
            }],
        }],
    }]
    answers = {"坏-键": {"q#1": {"correctOption": "A", "score": 1}}}
    fixes, _warnings = apply_autofix(manifest, papers, answers)
    new_paper_key = papers[0]["paperKey"]
    assert new_paper_key != "坏-键"
    assert list(answers) == [new_paper_key]
    new_q = next(iter(answers[new_paper_key]))
    assert new_q == papers[0]["units"][0]["questions"][0]["questionKey"]
    assert _fix(fixes, "answers")


def test_autofix_answers_absent_creates_empty_entry():
    manifest = {"packageId": "cn.ok.pkg", "subject": "english"}
    papers = [{"paperKey": "cn.ok.y2024", "year": 2024, "units": []}]
    fixes, _warnings = apply_autofix(manifest, papers, {})
    assert fixes == []
    # 无答案条目时不抛错：paper_answers None → 取新键 → 空对象兜底
    assert papers[0]["paperKey"] == "cn.ok.y2024"


# --- _build_paper_file / build_esq_package ---

def test_build_includes_paper_title_and_block_keys(tmp_path, manifest, papers, answers):
    built_papers = copy.deepcopy(papers)
    built_papers[0]["title"] = "阅读卷"
    for unit in built_papers[0]["units"]:
        for index, block in enumerate(unit["passage"]["blocks"]):
            block.pop("blockKey", None)
    out = tmp_path / "t.esq"
    result = build_esq_package(manifest, built_papers, answers, str(out))
    assert result["ok"], result["errors"]
    with zipfile.ZipFile(out) as zf:
        paper_file = json.loads(zf.read("papers/cn.test.reading.y2024.json").decode("utf-8"))
    assert paper_file["title"] == "阅读卷"
    assert paper_file["units"][0]["passage"]["blocks"][0]["blockKey"] == "block-0"


def test_build_auto_fix_end_to_end(tmp_path, manifest, papers, answers):
    dirty_manifest = dict(manifest)
    dirty_manifest["packageId"] = "gaokao-2024-新课标"
    dirty_papers = copy.deepcopy(papers)
    dirty_papers[0]["paperKey"] = "gaokao-2024-新课标Ⅰ"
    dirty_papers[0]["units"][0]["passage"]["blocks"][0]["text"] = (
        "Hello world. {blank:1} test."
    )
    # 答案键跟随脏 paperKey，autofix 应同步改名
    dirty_answers = {
        "gaokao-2024-新课标Ⅰ": {"cn.test.reading.y2024.u1.q1": {"correctOption": "A", "score": 2}},
        "cn.test.cloze.y2024": answers["cn.test.cloze.y2024"],
    }
    result = build_esq_package(
        dirty_manifest, dirty_papers, dirty_answers, str(tmp_path / "fixed.esq"), auto_fix=True,
    )
    assert result["ok"], result["errors"]
    assert result["fixes"], "auto_fix 必须留下修复痕迹"
