"""client 测试: MockTransport 模拟后端（上传/发布/503 重试）。"""

from __future__ import annotations

import httpx
import pytest

from esq_builder_mcp.client import upload_and_publish


@pytest.fixture
def esq_zip(tmp_path):
    path = tmp_path / "demo.esq"
    path.write_bytes(b"PK\x03\x04fake")
    return str(path)


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def test_upload_and_publish_success(esq_zip):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path.endswith("/imports"):
            return httpx.Response(200, json={"id": 42, "filename": "demo.esq", "format": "esq-1.0"})
        return httpx.Response(200, json={"published_paper_ids": [1, 2]})

    result = upload_and_publish(esq_zip, transport=_transport(handler), retry_interval=0)
    assert result["ok"]
    assert result["job_id"] == 42
    assert result["published"]["published_paper_ids"] == [1, 2]
    # 坑固化: 上传路径必须是 /api/question-banks/imports, 发布必须带 /publish 后缀
    assert calls[0].endswith("/api/question-banks/imports")
    assert calls[1].endswith("/api/question-banks/imports/42/publish")


def test_upload_503_retry_then_success(esq_zip):
    upload_attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/imports"):
            upload_attempts["n"] += 1
            if upload_attempts["n"] < 3:
                return httpx.Response(503, text="service unavailable")
            return httpx.Response(200, json={"id": 7})
        return httpx.Response(200, json={"ok": True})  # publish

    result = upload_and_publish(esq_zip, transport=_transport(handler), retry_interval=0)
    assert result["ok"]
    assert upload_attempts["n"] == 3  # 503 抖动重试 3 次内恢复


def test_upload_503_exhausted(esq_zip):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    result = upload_and_publish(esq_zip, transport=_transport(handler), retry_interval=0)
    assert not result["ok"]
    assert result["stage"] == "upload"


def test_upload_405_wrong_path_not_retried(esq_zip):
    """405（如误用 /upload）不该重试, 直接报错。"""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(405, json={"detail": {"code": "METHOD_NOT_ALLOWED", "message": "Method Not Allowed"}})

    result = upload_and_publish(esq_zip, transport=_transport(handler), retry_interval=0)
    assert not result["ok"]
    assert attempts["n"] == 1


def test_publish_failure_after_upload(esq_zip):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/imports"):
            return httpx.Response(200, json={"id": 9})
        return httpx.Response(400, json={"detail": {"code": "PUBLISH_BLOCKED", "message": "存在警告未确认"}})

    result = upload_and_publish(esq_zip, transport=_transport(handler), retry_interval=0)
    assert not result["ok"]
    assert result["stage"] == "publish"
    assert result["hint"]  # 上传已成功, 提示可用 job_id 单独重试
    assert result["job_id"] == 9


def test_missing_file():
    assert not upload_and_publish("Z:/no/such.esq")["ok"]
