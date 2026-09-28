"""wordlist 测试: kajweb JSONL 逐行解析 + 热点词统计。"""

from __future__ import annotations

import json

from esq_builder_mcp.wordlist import hot_words, parse_wordlist


def _write_jsonl(path, rows):
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")


def test_parse_wordlist(tmp_path):
    """JSONL 每行一个对象; 整文件 json.loads 会报 Extra data（技能实测坑）。"""
    rows = [
        {"wordRank": 2, "headWord": "banana", "content": {"word": {"content": {"usphone": "bəˈnænə", "trans": [{"pos": "n", "tranCn": "香蕉"}], "syno": []}}}},
        {"wordRank": 1, "headWord": "apple", "content": {"word": {"content": {"usphone": "ˈæpl", "trans": [{"pos": "n", "tranCn": "苹果"}], "syno": []}}}},
        "not json",  # 坏行应跳过并计数
    ]
    path = tmp_path / "words.jsonl"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) if isinstance(r, dict) else r for r in rows), encoding="utf-8")

    result = parse_wordlist(str(path), top_n=1, level="四级·高频")
    assert result["ok"]
    assert result["bad_lines"] == 1
    assert result["count"] == 1
    assert result["words"][0]["word"] == "apple"  # wordRank 排序
    assert result["words"][0]["translations"][0]["tran"] == "苹果"


def test_parse_wordlist_missing_file():
    assert not parse_wordlist("Z:/no/such.jsonl")["ok"]


def test_hot_words_year_filter_and_stopwords():
    texts = [
        {"year": 2024, "text": "The technology development improves technology efficiency quickly."},
        {"year": 2018, "text": "ancient text should be excluded by year filter"},  # 早于 since_year
    ]
    result = hot_words(texts, since_year=2023, top_n=10)
    assert result["ok"]
    assert result["texts_scanned"] == 1  # 2018 那条被年份过滤
    terms = [w["term"] for w in result["hot_words"]]
    assert "technology" in terms
    assert "technology" == terms[0]  # 出现两次, 计数最高
    assert "ancient" not in terms  # 年份过滤生效


def test_hot_words_min_length_and_extra_stopwords():
    texts = [{"year": 2024, "text": "cat dog bird apple banana apple"}]  # cat/dog 3 字母被 {3,} 正则排除
    result = hot_words(texts, extra_stopwords=["banana", "bird"])
    terms = [w["term"] for w in result["hot_words"]]
    assert terms == ["apple"]
