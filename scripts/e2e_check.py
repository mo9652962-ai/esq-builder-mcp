"""真实链路自检: build → 官方校验 → 上传(不发布) → 清理。

用法: uv run python scripts/e2e_check.py [--base-url http://127.0.0.1:8765]
不发布(publish 不调用), 上传的 import job 用 DELETE 清理, 不污染题库。
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import httpx

from esq_builder_mcp.builder import build_esq_package
from esq_builder_mcp.client import UPLOAD_PATH
from esq_builder_mcp.validator import validate_package

MANIFEST = {
    "packageId": "cn.e2e.check.y2024",
    "contentVersion": "1.0.0",
    "title": "E2E 自检包",
    "subject": "英语",
    "publisher": "esq-builder-mcp",
    "license": {"notice": "自检数据, 用后即删"},
    "source": {"description": "esq-builder-mcp e2e_check 生成"},
}

PAPERS = [
    {
        "paperKey": "cn.e2e.check.reading.y2024",
        "year": 2024,
        "units": [
            {
                "unitKey": "cn.e2e.check.reading.y2024.u1",
                "type": "reading",
                "title": "Reading Comprehension",
                "sequence": 1,
                "passage": {"blocks": [{"type": "paragraph", "text": "The morning light moved slowly across the quiet valley."}]},
                "questions": [
                    {
                        "questionKey": "cn.e2e.check.reading.y2024.u1.q1",
                        "number": 1,
                        "type": "single_choice",
                        "stem": "What moved across the valley?",
                        "options": [{"key": "A", "content": "light"}, {"key": "B", "content": "wind"}],
                        "score": 2,
                    }
                ],
            }
        ],
    },
    {
        "paperKey": "cn.e2e.check.cloze.y2024",
        "year": 2024,
        "units": [
            {
                "unitKey": "cn.e2e.check.cloze.y2024.u1",
                "type": "cloze",
                "title": "Cloze",
                "sequence": 1,
                "passage": {"blocks": [{"type": "paragraph", "text": "She {{blank:1}} the door quietly and {{blank:2}} away."}]},
                "questions": [
                    {"questionKey": "cn.e2e.check.cloze.y2024.u1.q1", "number": 1, "type": "single_choice", "stem": "1", "options": [{"key": "A", "content": "closed"}, {"key": "B", "content": "opens"}], "score": 1},
                    {"questionKey": "cn.e2e.check.cloze.y2024.u1.q2", "number": 2, "type": "single_choice", "stem": "2", "options": [{"key": "A", "content": "walked"}, {"key": "B", "content": "runs"}], "score": 1},
                ],
            }
        ],
    },
]

ANSWERS = {
    "cn.e2e.check.reading.y2024": {"cn.e2e.check.reading.y2024.u1.q1": {"correctOption": "A", "score": 2}},
    "cn.e2e.check.cloze.y2024": {
        "cn.e2e.check.cloze.y2024.u1.q1": {"correctOption": "A", "score": 1},
        "cn.e2e.check.cloze.y2024.u1.q2": {"correctOption": "A", "score": 1},
    },
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = str(Path(tmp) / "e2e.esq")

        # 1. build
        built = build_esq_package(MANIFEST, PAPERS, ANSWERS, zip_path)
        assert built["ok"], f"build 失败: {json.dumps(built['errors'], ensure_ascii=False)}"
        print(f"[1/4] build ok: {built['totals']}, {built['size_bytes']} bytes")

        # 2. 官方校验
        validated = validate_package(zip_path)
        assert validated["valid"], f"官方校验失败: {json.dumps(validated.get('errors'), ensure_ascii=False)}"
        print(f"[2/4] 官方校验 ok: {validated['totals']}")

        # 3. 上传(不发布)
        with httpx.Client(base_url=args.base_url, timeout=60) as client:
            response = client.post(
                UPLOAD_PATH,
                files={"file": ("e2e.esq", Path(zip_path).read_bytes(), "application/zip")},
            )
            assert response.status_code < 400, f"上传失败 {response.status_code}: {response.text[:300]}"
            job_id = response.json()["id"]
            print(f"[3/4] 上传 ok: job_id={job_id}, profile_id={response.json().get('profile_id')}")

            # 4. 清理
            del_response = client.delete(f"{UPLOAD_PATH}/{job_id}")
            print(f"[4/4] 清理 ok: DELETE {del_response.status_code}")
            assert del_response.status_code < 400

    print("E2E PASS: build → validate → upload → cleanup 全链路真实通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
