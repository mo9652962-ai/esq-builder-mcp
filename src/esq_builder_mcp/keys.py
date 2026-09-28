"""ESQ 外部标识（externalKey）安全键的生成与修复。

固化技能 Pitfall：externalKey 必须纯 ASCII 3-200 位 [A-Za-z0-9._:-]，
含中文（如 unitKey="gaokao-cloze-2021-新课标Ⅰ"）校验直接失败。
推荐风格：cn.gaokao.cloze.y2021.u1
"""

from __future__ import annotations

import re
from typing import Any

EXTERNAL_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,199}$")

# 单个键段：保留 ASCII 字母数字与连字符、点号（点号是 externalKey 合法分隔符），
# 其余字符（含中文/全角/空格）折叠成 -
_SEGMENT_RE = re.compile(r"[^A-Za-z0-9.-]+")


def is_safe_external_key(value: Any) -> bool:
    return isinstance(value, str) and bool(EXTERNAL_KEY_RE.fullmatch(value))


def sanitize_segment(value: Any) -> str:
    """把任意文本（含中文/全角/空格）压成安全键段（小写归一）；无有效字符时返回空串。"""
    text = str(value or "")
    text = text.encode("ascii", "ignore").decode("ascii")
    return _SEGMENT_RE.sub("-", text).strip("-.").lower()


def build_key(*parts: Any) -> str:
    """用 '.' 连接各段；空段跳过。段内非法字符折叠为 '-'。"""
    segments = [sanitize_segment(part) for part in parts]
    return ".".join(seg for seg in segments if seg)


def ensure_external_key(value: Any, fallback_parts: tuple[Any, ...]) -> tuple[str, bool]:
    """返回 (key, rewritten)：value 合法则原样返回；否则用 fallback_parts 重建。"""
    if is_safe_external_key(value):
        return str(value), False
    rebuilt = build_key(*fallback_parts)
    if not EXTERNAL_KEY_RE.fullmatch(rebuilt):
        rebuilt = f"esq.{abs(hash(rebuilt)) % 10_000_000:07d}"
    return rebuilt, True
