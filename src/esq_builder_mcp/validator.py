"""ESQ 包校验入口（双轨）。

默认走内置 vendored 校验器（esq_validator.py，与 backend/app/services/esq.py
同规则，import 调用）——零外部依赖，PyPI/uvx/PyInstaller 分发可用。
显式提供 validator_path 或 ESQ_VALIDATOR_PATH 时改走官方 CLI subprocess，
作为 vendored 副本的对账/仲裁通道（一致性由 tests/test_validator_conformance.py 守护）。
"""

from __future__ import annotations

import json
import os
import subprocess  # nosec B404 —— 工具本体需调用官方校验器命令行，全项目唯一系统调用点
import sys
from pathlib import Path
from typing import Any

from .esq_validator import EsqValidationError, load_esq_package

DEFAULT_VALIDATOR = "D:/english-multiple-choice-practice-machine/tools/validate_question_bank.py"
VENDORED_LABEL = "vendored:backend/app/services/esq.py"


def _validate_via_subprocess(zip_path: str, validator: Path, python_path: str | None = None) -> dict[str, Any]:
    if not validator.exists():
        return {
            "ok": False,
            "valid": False,
            "errors": [
                {
                    "path": "validator",
                    "reason": f"官方校验器不存在: {validator}。可用 ESQ_VALIDATOR_PATH 环境变量或 validator_path 参数指定",
                }
            ],
        }
    proc = subprocess.run(  # noqa: PLW1510  # nosec B603 —— 参数全为自构造（解释器、校验器与包路径），输出捕获后由调用方解析为结构化结果
        [python_path or sys.executable, str(validator), str(zip_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {
            "ok": False,
            "valid": False,
            "errors": [{"path": "validator", "reason": "校验器输出不是 JSON"}],
            "stdout": proc.stdout[-2000:],
            "stderr": proc.stderr[-2000:],
        }
    return {"ok": True, "validator": str(validator), **payload, "stderr": proc.stderr[-2000:] if proc.stderr else ""}


def validate_package(zip_path: str, validator_path: str | None = None, python_path: str | None = None) -> dict[str, Any]:
    """校验 ESQ 包。默认 vendored；validator_path/ESQ_VALIDATOR_PATH 给定时走官方 CLI。

    返回 {ok, valid, validator, errors|packageId+contentVersion+totals, stderr}。
    """
    explicit = validator_path or os.environ.get("ESQ_VALIDATOR_PATH")
    if explicit:
        return _validate_via_subprocess(zip_path, Path(explicit), python_path)

    try:
        package = load_esq_package(zip_path)
    except EsqValidationError as error:
        return {"ok": True, "validator": VENDORED_LABEL, "valid": False, "errors": error.details, "stderr": ""}
    except (OSError, ValueError) as error:
        return {
            "ok": False,
            "validator": VENDORED_LABEL,
            "valid": False,
            "errors": [{"path": "file", "reason": str(error)}],
            "stderr": "",
        }
    return {
        "ok": True,
        "validator": VENDORED_LABEL,
        "valid": True,
        "packageId": package["manifest"]["packageId"],
        "contentVersion": package["manifest"]["contentVersion"],
        "totals": {
            "papers": len(package["papers"]),
            "units": sum(len(p["units"]) for p in package["papers"]),
            "questions": sum(len(u["questions"]) for p in package["papers"] for u in p["units"]),
            "assets": len(package.get("assets", {})),
        },
        "errors": [],
        "stderr": "",
    }
