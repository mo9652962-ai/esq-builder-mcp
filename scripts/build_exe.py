"""构建 Windows 单文件 exe（PyInstaller onefile）。

用法: uv run python scripts/build_exe.py
产物: dist/esq-builder-mcp.exe（stdio MCP server，PyInstaller 冷启动较慢属正常）
先装打包依赖: uv sync --all-extras（pyinstaller 在 dev extras 里）
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "scripts" / "exe_entry.py"


def main() -> int:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--onefile",
            "--clean",
            "--noconfirm",
            "--name",
            "esq-builder-mcp",
            "--copy-metadata",
            "fastmcp",
            "--copy-metadata",
            "mcp",
            "--copy-metadata",
            "pydantic",
            "--hidden-import",
            "mcp.server.fastmcp",
            str(ENTRY),
        ],
        cwd=str(ROOT),
        shell=False,
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
