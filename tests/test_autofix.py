"""auto_fix 通道: 机械性坑自动修复 + 审计, 判断性问题仍拒绝。"""

from __future__ import annotations

import copy

from esq_builder_mcp.builder import build_esq_package
from esq_builder_mcp.esq_validator import load_esq_package

from conftest import MANIFEST, CLOZE_UNIT, READING_UNIT


def _dirty_papers() -> list[dict]:
    """含三个坑: 中文 paperKey/unitKey、中文 questionKey、单花括号空位。"""
    unit = copy.deepcopy(CLOZE_UNIT)
    unit["unitKey"] = "gaokao-cloze-2021-完形"
    unit["passage"]["blocks"][0]["text"] = "I {blank:1} a cat. It {blank:2} cute."
    unit["questions"][0]["questionKey"] = "第1题"
    return [{"paperKey": "gaokao-cloze-2021-新课标Ⅰ", "year": 2021, "units": [unit]}]


def test_auto_fix_false_keeps_reject(tmp_path):
    """默认行为不变: 脏输入直接拒绝。"""
    result = build_esq_package(MANIFEST, _dirty_papers(), {}, str(tmp_path / "x.esq"))
    assert not result["ok"]
    assert result["fixes"] == []
    assert any("paperKey" in e["path"] for e in result["errors"])


def test_auto_fix_rebuilds_keys_and_remaps_answers(tmp_path):
    papers = _dirty_papers()
    q2_key = papers[0]["units"][0]["questions"][1]["questionKey"]
    answers = {
        "gaokao-cloze-2021-新课标Ⅰ": {
            "第1题": {"correctOption": "A", "score": 1},
            q2_key: {"correctOption": "B", "score": 1},
        }
    }
    result = build_esq_package(MANIFEST, papers, answers, str(tmp_path / "fixed.esq"), auto_fix=True)
    assert result["ok"], result["errors"]

    fields = {f["field"].split(".")[-1] for f in result["fixes"]}
    assert {"paperKey", "unitKey", "questionKey"} <= fields
    assert any("花括号" in f["old"] for f in result["fixes"])  # 单→双花括号

    # 产物必须过 vendored 校验器, 且答案键已同步到新键
    package = load_esq_package(result["zip_path"])
    unit = package["papers"][0]["units"][0]
    new_unit_key = unit["unitKey"]
    assert new_unit_key.endswith(".u1")
    answer_map = package["papers"][0]["answers"]
    assert answer_map[f"{new_unit_key}.q1"]["correctOption"] == "A"
    # q2 原键本身合法, 不改名, 答案键保持原样
    assert answer_map[q2_key]["correctOption"] == "B"


def test_auto_fix_short_blockkey_normalized(tmp_path):
    """2 位的 blockKey（如 p1）官方校验必挂, 打包时应归一为 block-{index}。"""
    papers = [{"paperKey": "cn.test.blockkey.y2024", "year": 2024, "units": [copy.deepcopy(READING_UNIT)]}]
    papers[0]["units"][0]["passage"]["blocks"][0]["blockKey"] = "p1"
    answers = {"cn.test.blockkey.y2024": {"cn.test.reading.y2024.u1.q1": {"correctOption": "A", "score": 2}}}
    result = build_esq_package(MANIFEST, papers, answers, str(tmp_path / "bk.esq"))
    assert result["ok"], result["errors"]
    package = load_esq_package(result["zip_path"])
    assert package["papers"][0]["units"][0]["passage"]["blocks"][0]["blockKey"] == "block-0"
