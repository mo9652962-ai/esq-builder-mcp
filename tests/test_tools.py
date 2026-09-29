"""MCP 工具层集成测试: fastmcp 内存 Client 全链路（build → validate）。"""

from __future__ import annotations

import pytest

from esq_builder_mcp.server import mcp

try:
    from fastmcp import Client
except ImportError:  # pragma: no cover
    pytest.skip("fastmcp 未安装", allow_module_level=True)

from pathlib import Path

from esq_builder_mcp.validator import DEFAULT_VALIDATOR


async def test_list_tools():
    async with Client(mcp) as client:
        tools = await client.list_tools()
        names = {t.name for t in tools}
        assert names == {
            "esq_build_package",
            "esq_validate_package",
            "esq_upload_and_publish",
            "esq_parse_wordlist",
            "esq_hot_words",
        }


async def test_build_tool_end_to_end(tmp_path, manifest, papers, answers):
    async with Client(mcp) as client:
        result = await client.call_tool(
            "esq_build_package",
            {
                "manifest": manifest,
                "papers": papers,
                "answers": answers,
                "output_path": str(tmp_path / "demo.esq"),
            },
        )
        data = result.data
        assert data["ok"] is True, data["errors"]
        assert (tmp_path / "demo.esq").exists()


async def test_build_tool_reports_friendly_errors(tmp_path, manifest, papers):
    async with Client(mcp) as client:
        result = await client.call_tool(
            "esq_build_package",
            {
                "manifest": manifest,
                "papers": papers,
                "answers": {},
                "output_path": str(tmp_path / "bad.esq"),
            },
        )
        data = result.data
        assert data["ok"] is False
        assert any("每空必填" in e["reason"] for e in data["errors"])


@pytest.mark.skipif(not Path(DEFAULT_VALIDATOR).exists(), reason="本机无刷题机校验器")
async def test_validate_tool_against_real_validator(tmp_path, manifest, papers, answers):
    """真校验器联动: build 出的包必须过官方 esq.py 校验（双保险一致性）。"""
    from esq_builder_mcp.builder import build_esq_package

    zip_path = str(tmp_path / "real.esq")
    built = build_esq_package(manifest, papers, answers, zip_path)
    assert built["ok"], built["errors"]

    async with Client(mcp) as client:
        result = await client.call_tool("esq_validate_package", {"zip_path": zip_path})
        data = result.data
        assert data["ok"] is True, data
        assert data["valid"] is True, data.get("errors")
