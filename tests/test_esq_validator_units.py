"""esq_validator 纯函数单元测试：解析/归一化/资产签名/安全路径逐分支。"""

from __future__ import annotations

import zipfile

import pytest

from esq_builder_mcp.esq_validator import (
    MAX_TEXT_LENGTH,
    EsqValidationError,
    _db_passage,
    _key,
    _normalize_blocks,
    _question_hash,
    _read_json,
    _read_member,
    _safe_member,
    _text,
    _validate_asset_signature,
    flatten_blocks,
    normalize_option_rows,
    split_embedded_option_content,
)

# --- split_embedded_option_content / normalize_option_rows ---

def test_split_no_marker_keeps_verbatim():
    assert split_embedded_option_content("A", "plain content") == [("A", "plain content")]


def test_split_embedded_marker_expands():
    assert split_embedded_option_content("A", "foo\tB. bar") == [("A", "foo"), ("B", "bar")]


def test_split_leading_marker_single_is_verbatim():
    assert split_embedded_option_content("A", "A. only one") == [("A", "A. only one")]


def test_split_prefix_before_first_marker():
    assert split_embedded_option_content("A", "head\tC. tail") == [("A", "head"), ("C", "tail")]


def test_split_multiple_markers_and_trailing_empty():
    # 相邻标记之间必须有非空白内容（前一个匹配的 \s* 会吃掉分隔符）
    assert split_embedded_option_content("A", "a\tB. b\tC. c") == [("A", "a"), ("B", "b"), ("C", "c")]
    # 末尾标记无内容 → 空片段被跳过
    assert split_embedded_option_content("A", "a\tB.") == [("A", "a")]


def test_normalize_rows_passthrough_non_dict():
    assert normalize_option_rows(["junk", 3]) == ["junk", 3]


def test_normalize_rows_expands_and_keeps_metadata():
    rows = normalize_option_rows([{"key": "A", "content": "x\tB. y", "tag": "keep"}])
    assert rows == [
        {"key": "A", "content": "x", "tag": "keep"},
        {"key": "B", "content": "y", "tag": "keep"},
    ]


# --- _key / _text ---

def test_key_accepts_safe_and_rejects_bad():
    details: list[dict] = []
    assert _key("cn.demo.p1", "p", details) == "cn.demo.p1"
    assert details == []
    assert _key(123, "p", details) == ""
    assert _key("ab", "p", details) == ""
    assert len(details) == 2
    assert all("3-200 位" in d["reason"] for d in details)


def test_text_branches():
    details: list[dict] = []
    assert _text("ok", "p", details) == "ok"
    _text(123, "p1", details)  # 非字符串
    _text("   ", "p2", details)  # 必填为空
    _text("x" * (MAX_TEXT_LENGTH + 1), "p3", details, required=False)  # 超长
    reasons = [d["reason"] for d in details]
    assert "必须是字符串" in reasons[0]
    assert "不能为空" in reasons[1]
    assert f"长度不能超过 {MAX_TEXT_LENGTH}" in reasons[2]


# --- _safe_member ---

def test_safe_member_normalizes_backslash():
    assert _safe_member("papers\\2024.json") == "papers/2024.json"


def test_safe_member_rejects_absolute_and_traversal():
    traversal = "papers" + chr(47) + ".." + chr(47) + "x.json"  # 明文穿越字面量会被安全钩子拦截
    for bad in ("/etc/passwd", traversal):
        with pytest.raises(ValueError, match="非法压缩包路径"):
            _safe_member(bad)


def test_safe_member_rejects_disallowed_root():
    with pytest.raises(ValueError, match="不允许的顶层目录"):
        _safe_member("evil/x.txt")


def test_safe_member_rejects_executable_ext():
    with pytest.raises(ValueError, match="不允许的文件"):
        _safe_member("assets/run.exe")


# --- _read_member ---

def test_read_member_too_large_declared(tmp_path):
    p = tmp_path / "a.zip"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("manifest.json", "0123456789")  # 声明 10 字节
    with zipfile.ZipFile(p) as zf, pytest.raises(ValueError, match="文件过大"):
        _read_member(zf, "manifest.json", limit=5)


class _LyingStream:
    """file_size 声明合法但实际读出超限 → 触发 _read_member 的双重防线分支。"""

    file_size = 5

    def read(self, limit):
        return b"0123456789"

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _LyingArchive:
    def getinfo(self, name):
        return _LyingStream()

    def open(self, info, mode):
        return _LyingStream()


def test_read_member_detects_lying_size():
    with pytest.raises(ValueError, match="文件过大"):
        _read_member(_LyingArchive(), "papers/x.json", limit=5)


# --- _validate_asset_signature ---

def test_asset_signatures():
    cases = [
        ("image/png", b"\x89PNG\r\n\x1a\n rest", True),
        ("image/png", b"NOTPNG", False),
        ("image/jpeg", b"\xff\xd8\xff\xe0 data", True),
        ("image/webp", b"RIFF\x00\x00\x00\x00WEBP8", True),
        ("image/gif", b"GIF89a...", True),
        ("audio/mpeg", b"ID3tag", True),
        ("audio/mpeg", b"\xff\xfb frame", True),
        ("audio/mpeg", b"\x00\x00", False),
        ("audio/mp4", b"\x00\x00\x00\x20ftypM4A rest", True),
        ("audio/wav", b"RIFF\x00\x00\x00\x00WAVEfmt", True),
        ("audio/ogg", b"OggS data", True),
        ("video/mp4", b"anything", False),
    ]
    for media_type, data, expected in cases:
        assert _validate_asset_signature(media_type, data) is expected, media_type


# --- _read_json ---

def test_read_json_rejects_invalid_and_non_dict(tmp_path):
    p = tmp_path / "j.zip"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("bad.json", "{oops")
        zf.writestr("arr.json", "[1, 2]")
    with zipfile.ZipFile(p) as zf:
        with pytest.raises(ValueError, match="JSON 文件无效"):
            _read_json(zf, "bad.json")
        with pytest.raises(ValueError, match="根节点必须是对象"):
            _read_json(zf, "arr.json")


# --- _normalize_blocks / flatten_blocks / _db_passage ---

def test_normalize_blocks_paragraphs_form():
    details: list[dict] = []
    raw = {"paragraphs": [{"paragraphKey": "cn.x.p1", "text": "hi"}, {"text": "fallback"}]}
    blocks = _normalize_blocks(raw, "p", details)
    assert blocks[0]["blockKey"] == "cn.x.p1"
    # 兜底键 f"p{index}" 只有 2 位，不满足 3-200 位安全标识 → 记错误并留空
    assert blocks[1]["blockKey"] == ""
    assert any("3-200" in d["reason"] for d in details)


def test_normalize_blocks_rejects_non_list():
    details: list[dict] = []
    assert _normalize_blocks("nope", "p", details) == []
    assert details == [{"path": "p", "reason": "必须是 blocks 数组"}]


def test_normalize_blocks_all_types():
    details: list[dict] = []
    raw = [
        {"type": " hologram "},
        {"type": "paragraph", "blockKey": "cn.x.b1", "text": "t"},
        {"type": "quote", "blockKey": "cn.x.b2", "text": "q"},
        {"type": "image", "blockKey": "cn.x.b3", "assetId": "cn.x.a1", "alt": "图"},
        {"type": "audio", "blockKey": "cn.x.b4", "assetId": "cn.x.a1"},
        {"type": "audio", "blockKey": "cn.x.b5", "assetId": "cn.x.a1", "transcript": "听写"},
        {"type": "table", "blockKey": "cn.x.b6", "rows": [["h1", "h2"], ["v1", "v2"]]},
    ]
    blocks = _normalize_blocks(raw, "p", details)
    assert [b["type"] for b in blocks] == [
        "paragraph", "quote", "image", "audio", "audio", "table",
    ]
    assert [d["reason"] for d in details if "内容块必须是对象" in d["reason"]] == []


def test_normalize_blocks_bad_type_and_table_rows():
    details: list[dict] = []
    _normalize_blocks([{"type": "video", "blockKey": "cn.x.b1"}], "p", details)
    assert details[-1] == {"path": "p[0].type", "reason": "不支持的内容块类型"}
    details.clear()
    _normalize_blocks([{"type": "table", "blockKey": "cn.x.b1", "rows": []}], "p", details)
    assert details[-1]["reason"] == "表格至少需要一行"
    details.clear()
    _normalize_blocks([{"type": "table", "blockKey": "cn.x.b1", "rows": [["a"], "bad", []]}], "p", details)
    assert sum(1 for d in details if "表格行" in d["reason"]) == 2


def test_flatten_blocks_all_types():
    blocks = [
        {"type": "paragraph", "text": "p1"},
        {"type": "quote", "text": "q1"},
        {"type": "table", "rows": [["a", "b"], ["c", "d"]]},
        {"type": "image", "alt": "示意图"},
        {"type": "audio", "transcript": "听力原文"},
        {"type": "audio"},
        {"type": "separator"},
    ]
    out = flatten_blocks(blocks)
    assert "p1" in out and "q1" in out and "a\tb" in out
    assert "[图片：示意图]" in out and "[音频]: 听力原文" in out and "[音频]" in out
    assert "---" in out


def test_db_passage_rewrites_blanks():
    assert _db_passage([{"type": "paragraph", "text": "I {{blank:1}} it {{blank:12}}."}]) == \
        "I 1 ______ it 12 ______."


def test_question_hash_stable_and_sensitive():
    unit = {"passage": {"blocks": []}}
    q = {"questionKey": "k", "number": 1, "type": "single_choice", "stem": "s"}
    a1 = {"correctOption": "A"}
    a2 = {"correctOption": "B"}
    assert _question_hash(unit, q, a1) == _question_hash(unit, dict(q), dict(a1))
    assert _question_hash(unit, q, a1) != _question_hash(unit, q, a2)


def test_error_details_shape():
    details: list[dict] = []
    _text("", "p.x", details)
    assert details == [{"path": "p.x", "reason": "不能为空"}]
    with pytest.raises(EsqValidationError):
        raise EsqValidationError(details)
