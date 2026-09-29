"""零散缺口：validator 双轨分支、client 错误解析、keys 兜底、wordlist 行处理。"""

from __future__ import annotations

import zipfile

import httpx

from esq_builder_mcp.builder import build_esq_package
from esq_builder_mcp.client import _extract_error, upload_and_publish
from esq_builder_mcp.keys import ensure_external_key
from esq_builder_mcp.validator import validate_package

# --- validate_package：vendored 双轨 ---

def test_validate_vendored_ok(tmp_path, manifest, papers, answers):
    out = tmp_path / "ok.esq"
    assert build_esq_package(manifest, papers, answers, str(out))["ok"]
    result = validate_package(str(out))
    assert result["ok"] is True and result["valid"] is True
    assert result["totals"]["papers"] == 2
    assert "vendored" in result["validator"]


def test_validate_vendored_invalid_package(tmp_path):
    out = tmp_path / "empty.esq"
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr("papers/x.json", "{}")
    result = validate_package(str(out))
    assert result["ok"] is True
    assert result["valid"] is False
    assert any("manifest" in e["path"] for e in result["errors"])


def test_validate_file_missing(tmp_path):
    result = validate_package(str(tmp_path / "nope.esq"))
    assert result["ok"] is False
    assert result["errors"][0]["path"] == "file"


def test_validate_subprocess_validator_missing(tmp_path):
    result = validate_package(str(tmp_path / "x.esq"), validator_path=str(tmp_path / "ghost.py"))
    assert result["ok"] is False
    assert "不存在" in result["errors"][0]["reason"]


def test_validate_subprocess_non_json_output(tmp_path, manifest, papers, answers):
    out = tmp_path / "ok.esq"
    assert build_esq_package(manifest, papers, answers, str(out))["ok"]
    fake_validator = tmp_path / "fake_validator.py"
    fake_validator.write_text("print('not json')\n", encoding="utf-8")
    result = validate_package(str(out), validator_path=str(fake_validator))
    assert result["ok"] is False
    assert "不是 JSON" in result["errors"][0]["reason"]


def test_validate_subprocess_json_output(tmp_path, manifest, papers, answers):
    out = tmp_path / "ok.esq"
    assert build_esq_package(manifest, papers, answers, str(out))["ok"]
    fake_validator = tmp_path / "fake_validator.py"
    fake_validator.write_text(
        "import json, sys; print(json.dumps({'valid': True, 'via': 'cli'}))\n", encoding="utf-8",
    )
    result = validate_package(str(out), validator_path=str(fake_validator))
    assert result["ok"] is True
    assert result["valid"] is True and result["via"] == "cli"


# --- client 错误解析与上传分支 ---

def test_extract_error_variants():
    assert _extract_error(httpx.Response(400, json={"detail": "简单错误"})) == "简单错误"
    assert _extract_error(httpx.Response(400, json={"detail": {"message": "模型 503"}})) == "模型 503"
    detail_dict = _extract_error(httpx.Response(400, json={"detail": {"other": 1}}))
    assert "other" in detail_dict
    assert _extract_error(httpx.Response(400, content=b"<html>boom</html>"))


def test_upload_file_missing(tmp_path):
    result = upload_and_publish(str(tmp_path / "nope.esq"))
    assert result == {"ok": False, "error": f"文件不存在: {tmp_path / 'nope.esq'}"}


def test_upload_mock_transport_reject(tmp_path, manifest, papers, answers):
    out = tmp_path / "u.esq"
    assert build_esq_package(manifest, papers, answers, str(out))["ok"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"detail": {"message": "包体不合法"}})

    result = upload_and_publish(
        str(out), base_url="http://test", transport=httpx.MockTransport(handler), retry_interval=0.0,
    )
    assert result["ok"] is False and result["stage"] == "upload"
    assert result["error"] == "包体不合法"


def test_upload_then_publish_failure_hint(tmp_path, manifest, papers, answers):
    out = tmp_path / "u2.esq"
    assert build_esq_package(manifest, papers, answers, str(out))["ok"]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/publish"):
            return httpx.Response(500, json={"detail": "模型服务抖动"})
        return httpx.Response(200, json={"id": "job-1"})

    result = upload_and_publish(
        str(out), base_url="http://test", transport=httpx.MockTransport(handler), retry_interval=0.0,
    )
    assert result["ok"] is False and result["stage"] == "publish"
    assert result["job_id"] == "job-1"
    assert "重试" in result["hint"]


def test_upload_publish_success_roundtrip(tmp_path, manifest, papers, answers):
    out = tmp_path / "u3.esq"
    assert build_esq_package(manifest, papers, answers, str(out))["ok"]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/publish"):
            return httpx.Response(200, json={"published": True})
        assert request.headers["content-type"].startswith("multipart/form-data")
        return httpx.Response(200, json={"id": "job-9"})

    result = upload_and_publish(
        str(out), base_url="http://test", transport=httpx.MockTransport(handler), retry_interval=0.0,
    )
    assert result["ok"] is True
    assert result["published"] == {"published": True}


# --- keys 兜底 ---

def test_ensure_external_key_fallback_hash():
    rebuilt, changed = ensure_external_key(None, ("cn", "-_-"))
    assert changed is True
    import re

    assert re.fullmatch(r"esq\.\d{7}", rebuilt)


def test_ensure_external_key_passthrough():
    assert ensure_external_key("cn.good.key", ("x",)) == ("cn.good.key", False)


# --- wordlist 行处理 ---

def test_parse_wordlist_missing_file(tmp_path):
    from esq_builder_mcp.wordlist import parse_wordlist

    result = parse_wordlist(str(tmp_path / "nope.jsonl"))
    assert result["ok"] is False and "不存在" in result["error"]
