"""vendored 校验器与官方 CLI 的一致性对账。

vendored 副本（esq_validator.py）必须与 backend/app/services/esq.py 同判：
同一批包, valid 结论必须一致。本机有刷题机仓库时执行, 否则跳过。
后端校验逻辑变更后跑本文件——不一致就同步 esq_validator.py。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from esq_builder_mcp.builder import build_esq_package
from esq_builder_mcp.validator import DEFAULT_VALIDATOR, VENDORED_LABEL, validate_package


@pytest.mark.skipif(not Path(DEFAULT_VALIDATOR).exists(), reason="本机无刷题机官方校验器")
def test_vendored_matches_official_verdict(tmp_path, manifest, papers, answers):
    zip_path = str(tmp_path / "conformance.esq")
    built = build_esq_package(manifest, papers, answers, zip_path)
    assert built["ok"], built["errors"]

    vendored = validate_package(zip_path)
    assert vendored["validator"] == VENDORED_LABEL
    assert vendored["valid"] is True, vendored["errors"]

    official = validate_package(zip_path, validator_path=DEFAULT_VALIDATOR)
    assert official["ok"] is True, official
    assert official["valid"] == vendored["valid"]
    assert official.get("totals", {}).get("questions") == vendored["totals"]["questions"]


@pytest.mark.skipif(not Path(DEFAULT_VALIDATOR).exists(), reason="本机无刷题机官方校验器")
def test_vendored_rejects_same_as_official(tmp_path):
    """坏包双通道都必须拒绝: 不是有效 ZIP。"""
    bad = tmp_path / "bad.esq"
    bad.write_bytes(b"not a zip")
    vendored = validate_package(str(bad))
    official = validate_package(str(bad), validator_path=DEFAULT_VALIDATOR)
    assert vendored["valid"] is False
    assert official["valid"] is False
