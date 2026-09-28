"""ESQ 1.0 规则常量与基础校验。

规则来源：backend/app/services/esq.py（墨题刷题机）+ esq-question-bank-import 技能实测坑。
固化成代码后，这些坑对调用方（LLM/人）不再存在。
"""

from __future__ import annotations

import re
from typing import Any

# externalKey（packageId/paperKey/unitKey/questionKey）: 纯 ASCII, 3-200 位
KEY_RE = re.compile(r"[A-Za-z0-9._:\-]{3,200}")

# 选项/词库 key: 单个大写字母（esq.py 用 re.fullmatch(r"[A-Z]", key)）
OPTION_KEY_RE = re.compile(r"[A-Z]")

# manifest.contentVersion: 语义化版本
SEMVER_RE = re.compile(r"\d+\.\d+\.\d+")

# 段落块类型白名单（esq.py allowed 集合）
BLOCK_TYPES = {"paragraph", "quote", "image", "table", "audio", "separator"}

# 题型白名单（ESQ 1.0 导入管道实际支持的 unit type）
UNIT_TYPES = {"cloze", "reading", "part_b"}

# 上传端点硬限制
MAX_PACKAGE_BYTES = 100 * 1024 * 1024  # 100 MiB

BLANK_TOKEN_RE = re.compile(r"\{\{blank:(\d+)\}\}")
# 单花括号是库里存储格式, 包文件里必须双花括号（高频坑）
SINGLE_BLANK_RE = re.compile(r"(?<!\{)\{blank:\d+\}(?!\})")

MANIFEST_REQUIRED_TEXT_FIELDS = ("title", "subject", "publisher")


def check_key(value: Any, label: str, errors: list[dict[str, str]]) -> bool:
    """externalKey 规则: 纯 ASCII [A-Za-z0-9._:-], 3-200 位。含中文直接报错并给出正确风格示例。"""
    if not isinstance(value, str) or not KEY_RE.fullmatch(value):
        errors.append(
            {
                "path": label,
                "reason": f"必须是纯 ASCII 3-200 位 [A-Za-z0-9._:-]，当前值: {value!r}。"
                "含中文会校验失败，请用 cn.gaokao.cloze.y2021.u1 风格",
            }
        )
        return False
    return True


def check_option_key(value: Any, label: str, errors: list[dict[str, str]]) -> bool:
    if not isinstance(value, str) or not OPTION_KEY_RE.fullmatch(value):
        errors.append(
            {
                "path": label,
                "reason": f"必须是单个大写字母 A-Z，当前值: {value!r}",
            }
        )
        return False
    return True


def check_passage_blanks(paper_key: str, unit: dict[str, Any], errors: list[dict[str, str]]) -> int:
    """校验 cloze 段落空位标记, 返回空位数。

    - 单花括号 {blank:N} → 直接报错（ESQ 包必须双花括号, 库内存储才是单括号）
    - {{blank:N}} 序号必须从 1 连续递增
    """
    unit_label = f"papers.{paper_key}.units.{unit.get('unitKey', '?')}"
    passage = unit.get("passage") or {}
    blocks = passage.get("blocks") or []
    blanks = 0
    for index, block in enumerate(blocks):
        text = block.get("text", "") if isinstance(block, dict) else ""
        if SINGLE_BLANK_RE.search(text):
            errors.append(
                {
                    "path": f"{unit_label}.passage.blocks[{index}]",
                    "reason": "检测到单花括号 {blank:N} —— ESQ 包文件必须用双花括号 {{blank:N}}（库内存储才是单括号）",
                }
            )
        for match in BLANK_TOKEN_RE.finditer(text):
            blanks = max(blanks, int(match.group(1)))
    if blanks:
        expected = set(range(1, blanks + 1))
        found = {
            int(m.group(1))
            for block in blocks
            for m in BLANK_TOKEN_RE.finditer(block.get("text", "") if isinstance(block, dict) else "")
        }
        missing = expected - found
        if missing:
            errors.append(
                {
                    "path": f"{unit_label}.passage",
                    "reason": f"空位序号不连续, 缺少 {{blank:{',blank:'.join(map(str, sorted(missing)))}}}",
                }
            )
    return blanks
