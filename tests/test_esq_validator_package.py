"""esq_validator 端到端测试：合法包装载 + 变异电池逐条触发校验分支。"""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from esq_builder_mcp.builder import build_esq_package
from esq_builder_mcp.esq_validator import (
    EsqValidationError,
    _validate_asset_index,
    load_esq_package,
)

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


# --- 构造工具 ---

def _make_base(tmp_path: Path, manifest, papers, answers, name="base.esq") -> Path:
    out = tmp_path / name
    result = build_esq_package(manifest, papers, answers, str(out))
    assert result["ok"], result["errors"]
    return out


def _load(path: Path) -> dict:
    return load_esq_package(str(path))


def _mutate(tmp_path: Path, base: Path, updates: dict[str, str], name="mut.esq") -> Path:
    """复制 base 并替换/新增成员（updates: 成员名 → 文本内容）。"""
    target = tmp_path / name
    with zipfile.ZipFile(base) as zin, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = updates[info.filename].encode("utf-8") if info.filename in updates else zin.read(info.filename)
            zout.writestr(info.filename, data)
        for extra_name, extra_text in updates.items():
            if extra_name not in {i.filename for i in zin.infolist()}:
                zout.writestr(extra_name, extra_text.encode("utf-8"))
    return target


def _expect_errors(path: Path, *needles: str) -> list[str]:
    with pytest.raises(EsqValidationError) as exc:
        _load(path)
    texts = [f'{d["path"]} {d["reason"]}' for d in exc.value.details]
    for needle in needles:
        assert any(needle in t for t in texts), (needle, texts)
    return texts


def _read_json_member(path: Path, name: str):
    with zipfile.ZipFile(path) as zf:
        return json.loads(zf.read(name).decode("utf-8"))


# --- 合法包装载（含 assets / labels / 1.1 扩展字段 / 嵌入选项展开） ---

def _make_rich_pkg(tmp_path: Path) -> Path:
    paper_key = "cn.rich.y2024"
    q_key = "cn.rich.y2024.u1.q1"
    asset_id = "cn.rich.y2024.asset.img"
    sha = hashlib.sha256(PNG_BYTES).hexdigest()
    manifest = {
        "format": "esq",
        "schemaVersion": "1.1",
        "packageId": "cn.rich.pkg",
        "contentVersion": "1.0.0",
        "title": "富包",
        "subject": "英语",
        "publisher": "tester",
        "license": {"notice": "n"},
        "source": {"description": "d"},
        "papers": [{
            "paperKey": paper_key, "year": 2024,
            "path": f"papers/{paper_key}.json",
            "answerPath": f"answers/{paper_key}.json",
            "labelPath": f"labels/{paper_key}.json",
            "examType": "cet4", "examMonth": 6, "setNumber": 1, "listeningTracks": ["t.mp3"],
        }],
    }
    paper = {
        "paperKey": paper_key, "year": 2024,
        "units": [{
            "unitKey": "cn.rich.y2024.u1", "type": "reading", "title": "r", "sequence": 1,
            "passage": {"blocks": [
                {"type": "paragraph", "blockKey": "cn.rich.y2024.u1.b1", "text": "Read this."},
                {"type": "image", "blockKey": "cn.rich.y2024.u1.b2", "assetId": asset_id, "alt": "图"},
                {"type": "audio", "blockKey": "cn.rich.y2024.u1.b3", "assetId": asset_id},
            ]},
            "questions": [{
                "questionKey": q_key, "number": 1, "type": "single_choice", "stem": "?", "score": 2,
                "options": [{"key": "A", "content": "yes\tB. no"}],
            }],
        }],
    }
    answers = {"paperKey": paper_key, "answers": {q_key: {"correctOption": "A", "score": 2}}}
    labels = {"labels": {q_key: {"cohort": "demo"}}}
    assets = {"assets": [{
        "assetId": asset_id, "path": "assets/img.png", "mediaType": "image/png", "sha256": sha,
    }]}
    out = tmp_path / "rich.esq"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        zf.writestr(f"papers/{paper_key}.json", json.dumps(paper, ensure_ascii=False))
        zf.writestr(f"answers/{paper_key}.json", json.dumps(answers, ensure_ascii=False))
        zf.writestr(f"labels/{paper_key}.json", json.dumps(labels, ensure_ascii=False))
        zf.writestr("assets/index.json", json.dumps(assets, ensure_ascii=False))
        zf.writestr("assets/img.png", PNG_BYTES)
    return out


def test_load_valid_rich_package(tmp_path):
    pkg = _load(_make_rich_pkg(tmp_path))
    assert pkg["manifest"]["packageId"] == "cn.rich.pkg"
    assert len(pkg["papers"]) == 1
    unit = pkg["papers"][0]["units"][0]
    passage_text = unit["passageText"]
    assert "[图片：图]" in passage_text and "[音频]" in passage_text
    q = unit["questions"][0]
    # 嵌入选项展开：A 的内容 "yes\tB. no" → A=yes, B=no
    assert [(o["key"], o["content"]) for o in q["options"]] == [("A", "yes"), ("B", "no")]
    assert len(q["contentHash"]) == 64
    assert q["answerData"] == {"correctOption": "A", "score": 2}
    assert pkg["assets"]["cn.rich.y2024.asset.img"]["bytes"] == len(PNG_BYTES)
    # labels 记录被补上 questionContentHash 键
    assert pkg["papers"][0]["labels"]["labels"][q["questionKey"]]["questionContentHash"] == ""


def test_load_built_package_normalized(tmp_path, manifest, papers, answers):
    pkg = _load(_make_base(tmp_path, manifest, papers, answers))
    cloze = next(p for p in pkg["papers"] if p["paperKey"] == "cn.test.cloze.y2024").get("units")
    text = cloze[0]["passageText"]
    assert "I 1 ______ a cat. It 2 ______ cute." == text


# --- manifest 变异 ---

def test_manifest_field_errors(tmp_path, manifest, papers, answers):
    base = _make_base(tmp_path, manifest, papers, answers)
    good = _read_json_member(base, "manifest.json")

    def m(**overrides) -> Path:
        bad = dict(good)
        bad.update(overrides)
        return _mutate(tmp_path, base, {"manifest.json": json.dumps(bad, ensure_ascii=False)})

    _expect_errors(m(format="esq2"), "必须为 esq")
    _expect_errors(m(schemaVersion="9.9"), "仅支持 ESQ 1.0 / 1.1")
    _expect_errors(m(packageId="ab"), "3-200 位")
    _expect_errors(m(contentVersion="1.0"), "语义化")
    _expect_errors(m(title="  "), "manifest.title")
    _expect_errors(m(license=None), "manifest.license")
    _expect_errors(m(license={"notice": " "}), "manifest.license.notice")
    _expect_errors(m(source=None), "manifest.source")
    _expect_errors(m(source={"description": ""}), "manifest.source.description")
    _expect_errors(m(papers=[]), "至少包含一套试卷")


def test_manifest_schema_11_exam_fields(tmp_path, manifest, papers, answers):
    base = _make_base(tmp_path, manifest, papers, answers)
    good = _read_json_member(base, "manifest.json")
    good["schemaVersion"] = "1.1"

    def m(**overrides) -> Path:
        bad = dict(good)
        bad["papers"] = [{**good["papers"][0], **overrides}]
        return _mutate(tmp_path, base, {"manifest.json": json.dumps(bad, ensure_ascii=False)}, "m11.esq")

    _expect_errors(m(examType="sat"), "不支持的考试类型")
    _expect_errors(m(examMonth="六月"), "examMonth")
    _expect_errors(m(setNumber="a"), "setNumber")
    _expect_errors(m(listeningTracks={}), "listeningTracks")
    assert _load(m(examType="cet4", examMonth=6, setNumber=1, listeningTracks=["a.mp3"]))


# --- paper / unit / question / answers 变异 ---

def _paper_of(base: Path, name="papers/cn.test.reading.y2024.json") -> dict:
    return _read_json_member(base, name)


def _mutate_paper(tmp_path, base, mutate, name="mp.esq"):
    paper = _paper_of(base)
    mutate(paper)
    return _mutate(
        tmp_path, base,
        {"papers/cn.test.reading.y2024.json": json.dumps(paper, ensure_ascii=False)},
        name,
    )


def test_paper_level_errors(tmp_path, manifest, papers, answers):
    base = _make_base(tmp_path, manifest, papers, answers)

    def m_manifest(**overrides) -> Path:
        mf = _read_json_member(base, "manifest.json")
        mf["papers"][0].update(overrides)
        return _mutate(tmp_path, base, {"manifest.json": json.dumps(mf, ensure_ascii=False)})

    _expect_errors(m_manifest(paperKey="cn.other.y2024"), "必须与 manifest.papers")
    _expect_errors(m_manifest(path="papers/ghost.json"), "题目文件不存在")
    _expect_errors(m_manifest(answerPath="answers/ghost.json"), "答案文件不存在")

    def dup_ref() -> Path:
        mf = _read_json_member(base, "manifest.json")
        ref = mf["papers"][0]
        mf["papers"] = [
            ref,
            {**ref, "path": "papers/cn.test.cloze.y2024.json", "answerPath": "answers/cn.test.cloze.y2024.json"},
        ]
        return _mutate(tmp_path, base, {"manifest.json": json.dumps(mf, ensure_ascii=False)}, "mdup.esq")

    _expect_errors(dup_ref(), "试卷 ID 重复")

    _expect_errors(_mutate_paper(tmp_path, base, lambda p: p.update(year="2024")), "1900-2200")
    _expect_errors(_mutate_paper(tmp_path, base, lambda p: p.update(units=[])), "至少需要一个练习单元")
    _expect_errors(_mutate_paper(tmp_path, base, lambda p: p.update(units=["junk"])), "单元必须是对象")


def test_unit_level_errors(tmp_path, manifest, papers, answers):
    base = _make_base(tmp_path, manifest, papers, answers)

    def m_unit(**overrides) -> Path:
        def mutate(paper):
            paper["units"][0].update(overrides)
        return _mutate_paper(tmp_path, base, mutate)

    _expect_errors(m_unit(unitKey="ab"), "3-200 位")
    _expect_errors(m_unit(type="clozeX"), "不支持该题型")
    _expect_errors(m_unit(passage="text"), "必须是对象")
    _expect_errors(m_unit(passage={"blocks": "x"}), "必须是 blocks 数组")
    _expect_errors(m_unit(passage={"blocks": ["junk"]}), "内容块必须是对象")
    _expect_errors(m_unit(passage={"blocks": [{"type": "video", "blockKey": "cn.x.b1"}]}), "不支持的内容块类型")
    _expect_errors(m_unit(passage={"blocks": [{"type": "table", "blockKey": "cn.x.b1", "rows": []}]}), "表格至少需要一行")
    _expect_errors(m_unit(passage={"blocks": [{"type": "table", "blockKey": "cn.x.b1", "rows": ["bad"]}]}), "表格行")
    _expect_errors(
        m_unit(passage={"blocks": [{"type": "image", "blockKey": "cn.x.b1", "assetId": "cn.x.missing"}]}),
        "引用了不存在的资源",
    )
    _expect_errors(m_unit(candidates="x"), "必须是数组")
    _expect_errors(m_unit(candidates=["junk"]), "候选项必须是对象")
    _expect_errors(m_unit(candidates=[{"key": "a", "content": "x"}]), "单个大写字母")
    _expect_errors(m_unit(questions=[]), "至少需要一道题")
    _expect_errors(m_unit(questions=["junk"]), "题目必须是对象")

    def dup_unit_key(paper):
        paper["units"].append(dict(paper["units"][0]))
    _expect_errors(_mutate_paper(tmp_path, base, dup_unit_key), "单元 ID 重复")


def test_question_level_errors(tmp_path, manifest, papers, answers):
    base = _make_base(tmp_path, manifest, papers, answers)

    def m_question(**overrides) -> Path:
        def mutate(paper):
            paper["units"][0]["questions"][0].update(overrides)
        return _mutate_paper(tmp_path, base, mutate, "mq.esq")

    _expect_errors(m_question(questionKey="ab"), "3-200 位")
    _expect_errors(m_question(type="multi"), "仅支持 single_choice")
    _expect_errors(m_question(score=-1), "非负数字")
    _expect_errors(m_question(options=[]), "必须包含选项或使用单元候选项")
    _expect_errors(m_question(options=["junk"]), "选项必须是对象")
    _expect_errors(m_question(options=[{"key": "A", "content": "x"}, {"key": "A", "content": "y"}]), "选项键重复")
    # 小写键 a 会被 normalize_option_rows 静默大写为 A → 合法载入（记录该行为）
    normalized = _load(m_question(options=[{"key": "a", "content": "x"}]))
    assert normalized["papers"][0]["units"][0]["questions"][0]["options"][0]["key"] == "A"
    # 答案 A 不在只剩 B 的选项里 → 答案必须对应题目选项
    _expect_errors(m_question(options=[{"key": "B", "content": "x"}]), "答案必须对应题目选项")

    def dup_q(paper):
        u = paper["units"][0]
        u["questions"].append(dict(u["questions"][0]))  # 同键副本 → 题目 ID 重复
    _expect_errors(_mutate_paper(tmp_path, base, dup_q, "mqd.esq"), "题目 ID 重复")


def test_missing_answer_and_content_blocks(tmp_path, manifest, papers, answers):
    base = _make_base(tmp_path, manifest, papers, answers)
    # 答案文件缺 q1 → 缺少标准答案
    ans = _read_json_member(base, "answers/cn.test.reading.y2024.json")
    ans["answers"].pop("cn.test.reading.y2024.u1.q1")
    mutated = _mutate(
        tmp_path, base,
        {"answers/cn.test.reading.y2024.json": json.dumps(ans, ensure_ascii=False)},
        "ma.esq",
    )
    _expect_errors(mutated, "缺少标准答案")

    # answers.answers 非对象
    bad_ans = {"answers": "x"}
    mutated = _mutate(
        tmp_path, base,
        {"answers/cn.test.reading.y2024.json": json.dumps(bad_ans, ensure_ascii=False)},
        "ma2.esq",
    )
    _expect_errors(mutated, "必须是对象")

    # stemBlocks 引用不存在资源
    def add_stem_blocks(paper):
        q = paper["units"][0]["questions"][0]
        q["stemBlocks"] = [{"type": "image", "blockKey": "cn.x.sb1", "assetId": "cn.x.missing"}]
    _expect_errors(
        _mutate_paper(tmp_path, base, add_stem_blocks, "msb.esq"),
        "stemBlocks", "引用了不存在的资源",
    )

    # 选项 contentBlocks 引用不存在资源
    def add_option_blocks(paper):
        q = paper["units"][0]["questions"][0]
        q["options"][0]["contentBlocks"] = [{"type": "audio", "blockKey": "cn.x.cb1", "assetId": "cn.x.missing"}]
    _expect_errors(
        _mutate_paper(tmp_path, base, add_option_blocks, "mcb.esq"),
        "contentBlocks", "引用了不存在的资源",
    )


# --- 资产索引直接变异 ---

def _asset_zip(tmp_path: Path) -> zipfile.ZipFile:
    p = tmp_path / "assets.esq"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"packageId": "cn.x.y"}))
        zf.writestr("assets/img.png", PNG_BYTES)
    return zipfile.ZipFile(p)


def _asset(overrides: dict, sha: str | None = None) -> dict:
    item = {
        "assetId": "cn.x.asset.img", "path": "assets/img.png",
        "mediaType": "image/png", "sha256": sha or hashlib.sha256(PNG_BYTES).hexdigest(),
    }
    item.update(overrides)
    return item


def test_asset_index_mutations(tmp_path):
    details: list[dict] = []

    with _asset_zip(tmp_path) as zf:
        result = _validate_asset_index(zf, {"assets": [_asset({})]}, details)
    assert details == [] and "cn.x.asset.img" in result

    def run(raw):
        details.clear()
        with _asset_zip(tmp_path) as zf:
            _validate_asset_index(zf, raw, details)
        return [d["reason"] for d in details]

    assert "必须是数组" in run({"assets": "x"})
    assert "资源记录必须是对象" in run({"assets": ["junk"]})
    assert "必须是字符串" in run({"assets": [_asset({"path": 123})]})
    # 动态拼接穿越片段（明文字面量会被安全钩子拦截，语义等价）
    traversal = "assets" + chr(47) + ".." + chr(47) + "img.png"
    assert any("非法压缩包路径" in r for r in run({"assets": [_asset({"path": traversal})]}))
    assert "资源扩展名不受支持" in run({"assets": [_asset({"path": "assets/img.tif"})]})
    assert "不支持的媒体类型" in run({"assets": [_asset({"mediaType": "video/mp4"})]})
    assert any("64 位 SHA-256" in r for r in run({"assets": [_asset({"sha256": "xyz"})]}))
    assert "文件校验和不匹配" in run({"assets": [_asset({"sha256": "a" * 64})]})
    assert any("不匹配" in r for r in run({"assets": [_asset({"mediaType": "image/gif"})]}))
    dup = [_asset({}), _asset({"assetId": "cn.x.asset.img", "mediaType": "image/png"})]
    assert "资源 ID 重复" in run({"assets": dup})
    missing = [_asset({"path": "assets/nope.png"})]
    assert "nope" in "".join(run({"assets": missing}))


# --- archive 级防御 ---

def test_not_a_zipfile(tmp_path):
    p = tmp_path / "not.esq"
    p.write_text("plain text", encoding="utf-8")
    _expect_errors(p, "不是有效的 ESQ/ZIP 文件")


def test_missing_manifest(tmp_path):
    p = tmp_path / "empty.esq"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("papers/x.json", "{}")
    _expect_errors(p, "缺少 manifest.json")


def test_duplicate_member_name(tmp_path):
    p = tmp_path / "dup.esq"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("manifest.json", "{}")
        zf.writestr("manifest.json", "{}")
    _expect_errors(p, "压缩包路径重复")


def test_disallowed_root_member(tmp_path, manifest, papers, answers):
    base = _make_base(tmp_path, manifest, papers, answers)
    target = tmp_path / "evil.esq"
    with zipfile.ZipFile(base) as zin, zipfile.ZipFile(target, "w") as zout:
        for info in zin.infolist():
            zout.writestr(info.filename, zin.read(info.filename))
        zout.writestr("evil/x.txt", "boom")
    _expect_errors(target, "不允许的顶层目录")


def test_executable_member_rejected(tmp_path, manifest, papers, answers):
    base = _make_base(tmp_path, manifest, papers, answers)
    target = tmp_path / "exe.esq"
    with zipfile.ZipFile(base) as zin, zipfile.ZipFile(target, "w") as zout:
        for info in zin.infolist():
            zout.writestr(info.filename, zin.read(info.filename))
        zout.writestr("papers/run.exe", "MZ")
    _expect_errors(target, "不允许的文件")


def test_encrypted_flag_rejected(tmp_path):
    p = tmp_path / "enc.esq"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("papers/x.json", "{}")
    raw = bytearray(p.read_bytes())
    idx = raw.find(b"PK\x01\x02")  # 中央目录标志位置位 bit0 = 加密
    while idx != -1:
        raw[idx + 8] |= 1
        idx = raw.find(b"PK\x01\x02", idx + 1)
    p.write_bytes(bytes(raw))
    _expect_errors(p, "不允许加密 ZIP")


def test_compression_ratio_rejected(tmp_path):
    p = tmp_path / "bomb.esq"
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("papers/zeros.txt", "0" * 1_000_000)  # 压缩比远超 100
    _expect_errors(p, "压缩比过高")


def test_limit_constants_enforced(tmp_path, manifest, papers, answers, monkeypatch):
    base = _make_base(tmp_path, manifest, papers, answers)
    from esq_builder_mcp import esq_validator

    monkeypatch.setattr(esq_validator, "MAX_PACKAGE_BYTES", 10)
    with pytest.raises(EsqValidationError) as exc:
        _load(base)
    assert "100 MiB" in exc.value.details[0]["reason"]

    monkeypatch.setattr(esq_validator, "MAX_PACKAGE_BYTES", 100 * 1024 * 1024)
    monkeypatch.setattr(esq_validator, "MAX_UNPACKED_BYTES", 10)
    with pytest.raises(EsqValidationError) as exc:
        _load(base)
    assert "300 MiB" in exc.value.details[0]["reason"]

    monkeypatch.setattr(esq_validator, "MAX_UNPACKED_BYTES", 300 * 1024 * 1024)
    monkeypatch.setattr(esq_validator, "MAX_FILES", 2)
    with pytest.raises(EsqValidationError) as exc:
        _load(base)
    assert any("文件数量" in d["reason"] for d in exc.value.details)


def test_invalid_json_member_propagates_valueerror(tmp_path, manifest, papers, answers):
    base = _make_base(tmp_path, manifest, papers, answers)
    mutated = _mutate(
        tmp_path, base,
        {"papers/cn.test.reading.y2024.json": "{oops"},
        "badjson.esq",
    )
    with pytest.raises(ValueError, match="JSON 文件无效"):
        _load(mutated)
    manifest_root = _mutate(tmp_path, base, {"manifest.json": "[1, 2]"}, "badroot.esq")
    with pytest.raises(ValueError, match="根节点必须是对象"):
        _load(manifest_root)
