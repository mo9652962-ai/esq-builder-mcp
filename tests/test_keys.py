"""keys 模块: ASCII externalKey 修复逻辑。"""

from esq_builder_mcp.keys import (
    build_key,
    ensure_external_key,
    is_safe_external_key,
    sanitize_segment,
)


def test_safe_keys_pass_through():
    assert is_safe_external_key("cn.gaokao.cloze.y2021.u1")
    assert is_safe_external_key("2021-q2")
    assert not is_safe_external_key("gaokao-cloze-2021-新课标Ⅰ")
    assert not is_safe_external_key("ab")  # 少于 3 位
    assert not is_safe_external_key(None)


def test_sanitize_segment_strips_chinese():
    assert sanitize_segment("新课标Ⅰ") == ""
    assert sanitize_segment("CET-4 听力") == "cet-4"


def test_build_key_keeps_dots_in_parts():
    """点号是 externalKey 合法分隔符, 段内不能被吞掉。"""
    assert build_key("cn.english", "y2021", "p1") == "cn.english.y2021.p1"
    assert build_key("cn", "高考", "y2021", "u1") == "cn.y2021.u1"


def test_ensure_external_key_rewrites_dirty():
    key, changed = ensure_external_key("含-中文名", ("cn.english", "y2021", "p1"))
    assert changed
    assert key == "cn.english.y2021.p1"


def test_ensure_external_key_keeps_clean():
    key, changed = ensure_external_key("cn.gaokao.y2021", ("fallback",))
    assert not changed
    assert key == "cn.gaokao.y2021"
