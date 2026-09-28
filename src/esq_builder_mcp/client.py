"""刷题机后端导入/发布 API 客户端。

端点与坑全部固化（来源: esq-question-bank-import 技能）:
- 上传是 POST /api/question-banks/imports (multipart: file + profile_id), 不是 /upload（405）
- 发布是 POST /api/question-banks/imports/{job_id}/publish, body {}
- 模型服务 503 抖动: 重试 3 次间隔 10s（瞬时恢复, 不是配置问题）
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:8765"  # 刷题机 README 实测端口（uvicorn 8765, 非 8000）
UPLOAD_PATH = "/api/question-banks/imports"  # 写死正确路径, 防止 /upload 405 坑
RETRY_STATUSES = {503}
DEFAULT_RETRIES = 3
DEFAULT_RETRY_INTERVAL = 10.0


def _post_with_retry(client: httpx.Client, url: str, retry_interval: float = DEFAULT_RETRY_INTERVAL, **kwargs) -> httpx.Response:
    last_response: httpx.Response | None = None
    for attempt in range(DEFAULT_RETRIES):
        response = client.post(url, **kwargs)
        if response.status_code not in RETRY_STATUSES:
            return response
        last_response = response
        if attempt < DEFAULT_RETRIES - 1:
            time.sleep(retry_interval)
    assert last_response is not None
    return last_response


def upload_and_publish(
    zip_path: str,
    base_url: str = DEFAULT_BASE_URL,
    profile_id: int | None = None,
    publish: bool = True,
    timeout: float = 300.0,
    transport: httpx.BaseTransport | None = None,
    retry_interval: float = DEFAULT_RETRY_INTERVAL,
) -> dict:
    """上传 ESQ 包（可选发布）。返回 {ok, uploaded, published, ...}。

    transport 仅测试用（httpx.MockTransport）; retry_interval 仅测试用（默认 10s）。
    """
    path = Path(zip_path)
    if not path.exists():
        return {"ok": False, "error": f"文件不存在: {path}"}

    with httpx.Client(base_url=base_url, timeout=timeout, transport=transport) as client:
        files = {"file": (path.name, path.read_bytes(), "application/zip")}
        data = {"profile_id": str(profile_id)} if profile_id is not None else {}
        response = _post_with_retry(client, UPLOAD_PATH, retry_interval=retry_interval, files=files, data=data)
        if response.status_code >= 400:
            return {
                "ok": False,
                "stage": "upload",
                "status": response.status_code,
                "error": _extract_error(response),
            }
        uploaded = response.json()
        result: dict = {"ok": True, "uploaded": uploaded, "job_id": uploaded.get("id")}

        if publish and result.get("job_id") is not None:
            publish_url = f"{UPLOAD_PATH}/{result['job_id']}/publish"
            publish_response = _post_with_retry(client, publish_url, retry_interval=retry_interval, json={})
            if publish_response.status_code >= 400:
                result.update(
                    {
                        "ok": False,
                        "stage": "publish",
                        "status": publish_response.status_code,
                        "error": _extract_error(publish_response),
                        "hint": "上传已成功, 可用 job_id 单独重试发布",
                    }
                )
            else:
                result["published"] = publish_response.json()
        return result


def _extract_error(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail", response.text)
        if isinstance(detail, dict):
            return str(detail.get("message") or detail)
        return str(detail)
    except Exception:
        return response.text[:500]
