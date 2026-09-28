"""调用刷题机官方校验器（backend/app/services/esq.py 的 CLI 包装）。

设计决策：不复制 1402 行校验逻辑（避免双份漂移）, subprocess 调用
tools/validate_question_bank.py —— 校验器自身会 sys.path 插入仓库根。
校验器路径可用环境变量 ESQ_VALIDATOR_PATH 覆盖。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_VALIDATOR = "D:/english-multiple-choice-practice-machine/tools/validate_question_bank.py"


def validate_package(zip_path: str, validator_path: str | None = None, python_path: str | None = None) -> dict:
    """运行官方校验器, 返回 {ok, valid, errors|totals, validator, stderr}。"""
    validator = Path(validator_path or os.environ.get("ESQ_VALIDATOR_PATH", DEFAULT_VALIDATOR))
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

    proc = subprocess.run(
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
