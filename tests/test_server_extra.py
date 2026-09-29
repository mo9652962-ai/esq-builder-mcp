"""server 工具体剩余分支（upload/parse/hot_words）与 main 入口。"""

from __future__ import annotations

import json
import runpy
import zipfile

from fastmcp import FastMCP

from esq_builder_mcp import server as server_mod
from esq_builder_mcp.server import mcp

try:
    from fastmcp import Client
except ImportError:  # pragma: no cover
    import pytest

    pytest.skip("fastmcp 未安装", allow_module_level=True)


async def test_upload_tool_delegates(monkeypatch):
    captured = {}

    def fake_upload(zip_path, **kwargs):
        captured.update(kwargs, zip_path=zip_path)
        return {"ok": True, "job_id": "j1", "uploaded": True, "published": True}

    monkeypatch.setattr(server_mod, "upload_and_publish", fake_upload)
    async with Client(mcp) as client:
        result = await client.call_tool(
            "esq_upload_and_publish",
            {"zip_path": "x.esq", "base_url": "http://127.0.0.1:1", "profile_id": 3, "publish": False},
        )
    assert result.data["ok"] is True
    assert captured["zip_path"] == "x.esq"
    assert captured["profile_id"] == 3
    assert captured["publish"] is False


async def test_parse_wordlist_tool(tmp_path):
    jsonl = tmp_path / "words.jsonl"
    entry = {
        "wordRank": 1,
        "headWord": "apple",
        "content": {"word": {"content": {
            "usphone": "ˈæpl",
            "trans": [{"pos": "n", "tranCn": "苹果"}],
            "syno": [{"pos": "n", "words": [{"w": "fruit"}]}],
        }}},
    }
    jsonl.write_text("\n\n" + json.dumps(entry) + "\nnot-json\n", encoding="utf-8")
    async with Client(mcp) as client:
        result = await client.call_tool(
            "esq_parse_wordlist", {"jsonl_path": str(jsonl), "top_n": 10, "level": "测试级"},
        )
    data = result.data
    assert data["ok"] is True
    assert data["count"] == 1 and data["bad_lines"] == 1
    assert data["words"][0]["word"] == "apple"
    assert data["words"][0]["translations"][0]["tran"] == "苹果"


async def test_hot_words_tool_filters_by_year():
    texts = [
        {"year": 2024, "text": "The quick brown fox jumps over lazy dogs quickly."},
        {"year": 2020, "text": "ancient words should be ignored entirely here."},
    ]
    async with Client(mcp) as client:
        result = await client.call_tool(
            "esq_hot_words",
            {"texts": texts, "since_year": 2023, "top_n": 5, "extra_stopwords": ["quick"]},
        )
    data = result.data
    assert data["ok"] is True
    assert data["texts_scanned"] == 1  # 2020 年的文本被过滤
    terms = {w["term"] for w in data["hot_words"]}
    assert "quick" not in terms  # 额外停用词
    assert {"brown", "jumps", "dogs"} & terms


def test_main_entry_runs_without_serving(monkeypatch):
    """runpy 以 __main__ 重执行 server 模块；FastMCP.run 打桩防阻塞，覆盖 main() 全分支。"""
    monkeypatch.setattr(FastMCP, "run", lambda self: None, raising=True)
    runpy.run_module("esq_builder_mcp.server", run_name="__main__")


def test_wordlist_zip_input(tmp_path):
    """parse_wordlist 的 zip 通道（kajweb book/*.zip，逐行 JSON 对象）。"""
    zpath = tmp_path / "book.zip"
    line = json.dumps({
        "wordRank": 2, "headWord": "banana",
        "content": {"word": {"content": {"usphone": "b", "trans": [], "syno": []}}},
    })
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("book/level1.jsonl", line + "\n")
        zf.writestr("book/cover.png", b"\x89PNG")  # 非词表成员应被忽略
    from esq_builder_mcp.wordlist import parse_wordlist

    result = parse_wordlist(str(zpath))
    assert result["ok"] is True and result["count"] == 1
    assert result["words"][0]["word"] == "banana"
