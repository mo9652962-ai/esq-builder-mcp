"""ESQ 1.0 包校验器（vendor 自墨题刷题机 backend/app/services/esq.py 校验子集）。

与后端导入器保持同一套规则；后端校验逻辑变更时应同步本文件（跑
tests/test_validator_conformance.py 与官方 CLI 对账）。
此文件刻意自包含（无项目内依赖），保证 MCP 包可独立分发（PyPI/uvx/PyInstaller）。
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

MAX_PACKAGE_BYTES = 100 * 1024 * 1024
MAX_UNPACKED_BYTES = 300 * 1024 * 1024
MAX_FILES = 1000
MAX_JSON_BYTES = 20 * 1024 * 1024
MAX_TEXT_LENGTH = 100_000
EXTERNAL_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,199}$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
ALLOWED_ROOTS = {"manifest.json", "papers", "answers", "labels", "assets", "LICENSE.txt", "README.md"}
ALLOWED_ASSET_TYPES = {
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
    "audio/mpeg",
    "audio/mp4",
    "audio/wav",
    "audio/ogg",
}
ALLOWED_ASSET_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".mp3",
    ".m4a",
    ".wav",
    ".ogg",
}

# 与后端 exam_templates.EXAM_TEMPLATES 的注册键保持一致（仅校验用键列表）
SUPPORTED_EXAM_TYPES = ("cet4", "cet6", "gaokao", "tem4", "tem8")

UNIT_TYPES = {"cloze", "reading", "part_b", "listening", "word_bank", "paragraph_matching"}

EMBEDDED_OPTION_MARK_RE = re.compile(
    r"(?:^|[\t\r\n])\s*([A-Da-d])\s*(?:[.]|[．]|[、]|[)])\s*"
)


def split_embedded_option_content(key: str, content: str) -> list[tuple[str, str]]:
    """Return labelled pieces when *content* embeds another A-D option."""
    text = str(content or "").strip()
    source_key = str(key or "").strip().upper()
    matches = list(EMBEDDED_OPTION_MARK_RE.finditer(text))
    if not matches:
        return [(source_key, text)]

    pieces: list[tuple[str, str]] = []
    first = matches[0]
    if first.start() > 0:
        prefix = text[: first.start()].strip()
        if prefix:
            pieces.append((source_key, prefix))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        piece = text[match.end() : end].strip()
        if piece:
            pieces.append((match.group(1).upper(), piece))

    # A single leading marker is not a multi-option split. Keep it verbatim so
    # a legitimate option whose content starts with ``A.`` is not changed.
    if len(pieces) == 1 and first.start() == 0:
        return [(source_key, text)]
    return pieces or [(source_key, text)]


def normalize_option_rows(options: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Expand embedded options while preserving all other option metadata."""
    normalized: list[dict[str, Any]] = []
    for option in options:
        if not isinstance(option, dict):
            normalized.append(option)
            continue
        pieces = split_embedded_option_content(
            str(option.get("key", "")),
            str(option.get("content", "")),
        )
        for piece_key, piece_content in pieces:
            item = dict(option)
            item["key"] = piece_key
            item["content"] = piece_content
            normalized.append(item)
    return normalized


class EsqValidationError(ValueError):
    def __init__(self, details: list[dict[str, str]]) -> None:
        self.details = details
        super().__init__("ESQ 题库包校验失败")


def _error(details: list[dict[str, str]], path: str, reason: str) -> None:
    details.append({"path": path, "reason": reason})


def _key(value: Any, path: str, details: list[dict[str, str]]) -> str:
    if not isinstance(value, str) or not EXTERNAL_KEY_RE.fullmatch(value):
        _error(details, path, "必须是 3-200 位安全外部标识")
        return ""
    return value


def _text(value: Any, path: str, details: list[dict[str, str]], *, required: bool = True) -> str:
    if not isinstance(value, str):
        _error(details, path, "必须是字符串")
        return ""
    if required and not value.strip():
        _error(details, path, "不能为空")
    if len(value) > MAX_TEXT_LENGTH:
        _error(details, path, f"长度不能超过 {MAX_TEXT_LENGTH}")
    return value


def _safe_member(name: str) -> str:
    # Windows 打包工具常写入反斜杠条目名；先归一化再校验（..\ 仍会被拒绝）
    path = PurePosixPath(name.replace("\\", "/"))
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"非法压缩包路径：{name}")
    normalized = str(path)
    root = normalized.split("/", 1)[0]
    if root not in ALLOWED_ROOTS:
        raise ValueError(f"压缩包包含不允许的顶层目录：{root}")
    if normalized.lower().endswith((".exe", ".dll", ".bat", ".cmd", ".ps1", ".js", ".vbs", ".html", ".htm")):
        raise ValueError(f"压缩包包含不允许的文件：{name}")
    return normalized


def _read_member(archive: zipfile.ZipFile, name: str, *, limit: int = MAX_JSON_BYTES) -> bytes:
    info = archive.getinfo(name)
    if info.file_size > limit:
        raise ValueError(f"文件过大：{name}")
    with archive.open(info, "r") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"文件过大：{name}")
    return data


def _validate_asset_signature(media_type: str, data: bytes) -> bool:
    if media_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if media_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if media_type == "image/webp":
        return data.startswith(b"RIFF") and data[8:12] == b"WEBP"
    if media_type == "image/gif":
        return data.startswith((b"GIF87a", b"GIF89a"))
    if media_type == "audio/mpeg":
        return data.startswith(b"ID3") or (
            len(data) >= 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0
        )
    if media_type == "audio/mp4":
        return len(data) >= 12 and data[4:8] == b"ftyp"
    if media_type == "audio/wav":
        return data.startswith(b"RIFF") and data[8:12] == b"WAVE"
    if media_type == "audio/ogg":
        return data.startswith(b"OggS")
    return False


def _read_json(archive: zipfile.ZipFile, name: str) -> dict[str, Any]:
    try:
        payload = json.loads(_read_member(archive, name).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"JSON 文件无效：{name}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"JSON 根节点必须是对象：{name}")
    return payload


def _normalize_blocks(raw: Any, path: str, details: list[dict[str, str]]) -> list[dict[str, Any]]:
    if isinstance(raw, dict) and isinstance(raw.get("paragraphs"), list):
        raw = [
            {
                "blockKey": item.get("paragraphKey", f"p{index}"),
                "type": "paragraph",
                "text": item.get("text", ""),
            }
            for index, item in enumerate(raw["paragraphs"], 1)
            if isinstance(item, dict)
        ]
    if not isinstance(raw, list):
        _error(details, path, "必须是 blocks 数组")
        return []
    blocks: list[dict[str, Any]] = []
    allowed = {"paragraph", "quote", "image", "table", "audio", "separator"}
    for index, item in enumerate(raw):
        current_path = f"{path}[{index}]"
        if not isinstance(item, dict):
            _error(details, current_path, "内容块必须是对象")
            continue
        block_type = item.get("type")
        if block_type not in allowed:
            _error(details, f"{current_path}.type", "不支持的内容块类型")
            continue
        block = dict(item)
        block["blockKey"] = _key(item.get("blockKey"), f"{current_path}.blockKey", details)
        if block_type in {"paragraph", "quote"}:
            block["text"] = _text(item.get("text", ""), f"{current_path}.text", details)
        elif block_type == "image":
            block["assetId"] = _key(item.get("assetId"), f"{current_path}.assetId", details)
            block["alt"] = _text(item.get("alt", ""), f"{current_path}.alt", details)
        elif block_type == "audio":
            block["assetId"] = _key(item.get("assetId"), f"{current_path}.assetId", details)
            if "transcript" in item:
                block["transcript"] = _text(item.get("transcript", ""), f"{current_path}.transcript", details, required=False)
        elif block_type == "table":
            rows = item.get("rows")
            if not isinstance(rows, list) or not rows:
                _error(details, f"{current_path}.rows", "表格至少需要一行")
            else:
                normalized_rows: list[list[str]] = []
                for row_index, row in enumerate(rows):
                    if not isinstance(row, list) or not row:
                        _error(details, f"{current_path}.rows[{row_index}]", "表格行必须是非空数组")
                        continue
                    normalized_rows.append(
                        [
                            _text(cell, f"{current_path}.rows[{row_index}][{cell_index}]", details)
                            for cell_index, cell in enumerate(row)
                        ]
                    )
                block["rows"] = normalized_rows
        blocks.append(block)
    return blocks


def flatten_blocks(blocks: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for block in blocks:
        block_type = block.get("type")
        if block_type in {"paragraph", "quote"}:
            parts.append(str(block.get("text", "")))
        elif block_type == "table":
            rows = block.get("rows", [])
            parts.append("\n".join("\t".join(str(cell) for cell in row) for row in rows))
        elif block_type == "image":
            parts.append(f"[图片：{block.get('alt', '题库图片')}]")
        elif block_type == "audio":
            transcript = block.get("transcript", "")
            parts.append(f"[音频]{(': ' + transcript) if transcript else ''}")
        elif block_type == "separator":
            parts.append("---")
    return "\n\n".join(part for part in parts if part).strip()


def _db_passage(blocks: list[dict[str, Any]]) -> str:
    text = flatten_blocks(blocks)
    return re.sub(r"\{\{blank:(\d+)\}\}", r"\1 ______", text)


def _question_hash(
    unit: dict[str, Any],
    question: dict[str, Any],
    answer: dict[str, Any],
) -> str:
    canonical = {
        "passage": unit.get("passage", {}),
        "question": {
            key: question.get(key)
            for key in ("questionKey", "number", "type", "stem", "stemBlocks", "options", "score", "metadata")
        },
        "answer": answer,
    }
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_asset_index(
    archive: zipfile.ZipFile,
    raw: dict[str, Any],
    details: list[dict[str, str]],
) -> dict[str, dict[str, Any]]:
    assets = raw.get("assets", [])
    if not isinstance(assets, list):
        _error(details, "assets/index.json.assets", "必须是数组")
        return {}
    result: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(assets):
        path = f"assets/index.json.assets[{index}]"
        if not isinstance(item, dict):
            _error(details, path, "资源记录必须是对象")
            continue
        asset_id = _key(item.get("assetId"), f"{path}.assetId", details)
        asset_path = item.get("path")
        if not isinstance(asset_path, str):
            _error(details, f"{path}.path", "必须是字符串")
            continue
        try:
            asset_path = _safe_member(asset_path)
        except ValueError as error:
            _error(details, f"{path}.path", str(error))
            continue
        if Path(asset_path).suffix.lower() not in ALLOWED_ASSET_EXTENSIONS:
            _error(details, f"{path}.path", "资源扩展名不受支持")
        media_type = item.get("mediaType")
        if media_type not in ALLOWED_ASSET_TYPES:
            _error(details, f"{path}.mediaType", "不支持的媒体类型")
        sha256 = item.get("sha256")
        if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", sha256):
            _error(details, f"{path}.sha256", "必须是 64 位 SHA-256")
        if asset_id in result:
            _error(details, f"{path}.assetId", "资源 ID 重复")
            continue
        try:
            data = _read_member(archive, asset_path, limit=50 * 1024 * 1024)
        except (KeyError, ValueError) as error:
            _error(details, f"{path}.path", str(error))
            continue
        if sha256 and hashlib.sha256(data).hexdigest().lower() != str(sha256).lower():
            _error(details, f"{path}.sha256", "文件校验和不匹配")
        if media_type in ALLOWED_ASSET_TYPES and not _validate_asset_signature(media_type, data):
            _error(details, f"{path}.mediaType", "文件头与声明的媒体类型不匹配")
        result[asset_id] = {
            **item,
            "assetId": asset_id,
            "path": asset_path,
            "mediaType": media_type,
            "bytes": len(data),
        }
    return result


def _validate_paper(
    paper: dict[str, Any],
    reference: dict[str, Any],
    answers: dict[str, Any],
    labels: dict[str, Any] | None,
    assets: dict[str, dict[str, Any]],
    details: list[dict[str, str]],
) -> dict[str, Any]:
    paper_key = _key(paper.get("paperKey"), "paper.paperKey", details)
    if paper_key != reference.get("paperKey"):
        _error(details, "paper.paperKey", "必须与 manifest.papers[].paperKey 一致")
    year = paper.get("year")
    if not isinstance(year, int) or not 1900 <= year <= 2200:
        _error(details, "paper.year", "必须是 1900-2200 的整数")
    units = paper.get("units")
    if not isinstance(units, list) or not units:
        _error(details, "paper.units", "至少需要一个练习单元")
        units = []
    normalized_units: list[dict[str, Any]] = []
    unit_keys: set[str] = set()
    question_keys: set[str] = set()
    answer_map = answers.get("answers", {}) if isinstance(answers, dict) else {}
    if not isinstance(answer_map, dict):
        _error(details, f"answers[{year}].answers", "必须是对象")
        answer_map = {}
    for unit_index, raw_unit in enumerate(units):
        path = f"papers/{year}.units[{unit_index}]"
        if not isinstance(raw_unit, dict):
            _error(details, path, "单元必须是对象")
            continue
        unit = dict(raw_unit)
        unit_key = _key(unit.get("unitKey"), f"{path}.unitKey", details)
        if unit_key in unit_keys:
            _error(details, f"{path}.unitKey", "单元 ID 重复")
        unit_keys.add(unit_key)
        unit_type = unit.get("type")
        if unit_type not in UNIT_TYPES:
            _error(details, f"{path}.type", "不支持该题型")
        passage = unit.get("passage")
        if not isinstance(passage, dict):
            _error(details, f"{path}.passage", "必须是对象")
            passage = {"blocks": []}
        blocks = _normalize_blocks(passage.get("blocks", passage.get("paragraphs")), f"{path}.passage.blocks", details)
        unit["passage"] = {**passage, "blocks": blocks}
        unit["passageText"] = _db_passage(blocks)
        unit["contentBlocks"] = blocks
        for block in blocks:
            if block.get("type") in {"image", "audio"} and block.get("assetId") not in assets:
                _error(details, f"{path}.passage.blocks", f"引用了不存在的资源 {block.get('assetId')}")
        candidates = unit.get("candidates", [])
        if candidates and not isinstance(candidates, list):
            _error(details, f"{path}.candidates", "必须是数组")
            candidates = []
        candidate_keys: set[str] = set()
        normalized_candidates: list[dict[str, Any]] = []
        for candidate_index, candidate in enumerate(candidates):
            if not isinstance(candidate, dict):
                _error(details, f"{path}.candidates[{candidate_index}]", "候选项必须是对象")
                continue
            key = candidate.get("key")
            content = _text(candidate.get("content", ""), f"{path}.candidates[{candidate_index}].content", details)
            if not isinstance(key, str) or not re.fullmatch(r"[A-Z]", key):
                _error(details, f"{path}.candidates[{candidate_index}].key", "必须是单个大写字母")
                continue
            if key in candidate_keys:
                _error(details, f"{path}.candidates[{candidate_index}].key", "候选项键重复")
            candidate_keys.add(key)
            normalized_candidates.append({**candidate, "key": key, "content": content})
        unit["candidates"] = normalized_candidates
        questions = unit.get("questions", [])
        if not isinstance(questions, list) or not questions:
            _error(details, f"{path}.questions", "至少需要一道题")
            questions = []
        normalized_questions: list[dict[str, Any]] = []
        for question_index, raw_question in enumerate(questions):
            question_path = f"{path}.questions[{question_index}]"
            if not isinstance(raw_question, dict):
                _error(details, question_path, "题目必须是对象")
                continue
            question = dict(raw_question)
            question_key = _key(question.get("questionKey"), f"{question_path}.questionKey", details)
            if question_key in question_keys:
                _error(details, f"{question_path}.questionKey", "题目 ID 重复")
            question_keys.add(question_key)
            _text(question.get("stem", ""), f"{question_path}.stem", details, required=False)
            if question.get("stemBlocks") is not None:
                question["stemBlocks"] = _normalize_blocks(
                    question.get("stemBlocks"),
                    f"{question_path}.stemBlocks",
                    details,
                )
                for block in question["stemBlocks"]:
                    if block.get("type") in {"image", "audio"} and block.get("assetId") not in assets:
                        _error(details, f"{question_path}.stemBlocks", f"引用了不存在的资源 {block.get('assetId')}")
            if question.get("type") != "single_choice":
                _error(details, f"{question_path}.type", "v1 仅支持 single_choice")
            score = question.get("score")
            if not isinstance(score, (int, float)) or score < 0:
                _error(details, f"{question_path}.score", "分值必须是非负数字")
            options = question.get("options")
            if not options and normalized_candidates:
                options = normalized_candidates
            if not isinstance(options, list) or not options:
                _error(details, f"{question_path}.options", "必须包含选项或使用单元候选项")
                options = []
            # Accept legacy ESQ/OCR cells that contain e.g. ``foo\tB. bar``
            # by expanding them before validating keys and importing rows.
            options = normalize_option_rows(options)
            option_keys: set[str] = set()
            normalized_options: list[dict[str, Any]] = []
            for option_index, raw_option in enumerate(options):
                option_path = f"{question_path}.options[{option_index}]"
                if not isinstance(raw_option, dict):
                    _error(details, option_path, "选项必须是对象")
                    continue
                option_key = raw_option.get("key")
                if not isinstance(option_key, str) or not re.fullmatch(r"[A-Z]", option_key):
                    _error(details, f"{option_path}.key", "必须是单个大写字母")
                    continue
                if option_key in option_keys:
                    _error(details, f"{option_path}.key", "选项键重复")
                option_keys.add(option_key)
                normalized_options.append(
                    {
                        **raw_option,
                        "key": option_key,
                        "content": _text(raw_option.get("content", ""), f"{option_path}.content", details),
                    }
                )
                if raw_option.get("contentBlocks") is not None:
                    normalized_options[-1]["contentBlocks"] = _normalize_blocks(
                        raw_option.get("contentBlocks"),
                        f"{option_path}.contentBlocks",
                        details,
                    )
                    for block in normalized_options[-1]["contentBlocks"]:
                        if block.get("type") in {"image", "audio"} and block.get("assetId") not in assets:
                            _error(details, f"{option_path}.contentBlocks", f"引用了不存在的资源 {block.get('assetId')}")
            answer = answer_map.get(question_key)
            if not isinstance(answer, dict):
                _error(details, f"answers.{question_key}", "缺少标准答案")
                answer = {}
            correct = answer.get("correctOption")
            if correct not in option_keys:
                _error(details, f"answers.{question_key}.correctOption", "答案必须对应题目选项")
            question["options"] = normalized_options
            question["answerData"] = answer
            question["contentHash"] = _question_hash(unit, question, answer)
            normalized_questions.append(question)
            if labels and isinstance(labels.get("labels"), dict) and question_key in labels["labels"]:
                label = labels["labels"][question_key]
                if isinstance(label, dict):
                    label["questionContentHash"] = label.get("questionContentHash", "")
        unit["questions"] = normalized_questions
        normalized_units.append(unit)
    return {
        **paper,
        "paperKey": paper_key,
        "year": year,
        "units": normalized_units,
        "answers": answer_map,
        "labels": labels or {},
    }


def load_esq_package(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if path.stat().st_size > MAX_PACKAGE_BYTES:
        raise EsqValidationError([{"path": "file", "reason": "ESQ 文件超过 100 MiB"}])
    if not zipfile.is_zipfile(path):
        raise EsqValidationError([{"path": "file", "reason": "不是有效的 ESQ/ZIP 文件"}])
    details: list[dict[str, str]] = []
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_FILES:
                _error(details, "archive", "文件数量超过 1000")
            total_size = 0
            member_names: set[str] = set()
            for info in infos:
                try:
                    name = _safe_member(info.filename)
                except ValueError as error:
                    _error(details, f"archive.{info.filename}", str(error))
                    continue
                if name in member_names:
                    _error(details, f"archive.{name}", "压缩包路径重复")
                member_names.add(name)
                total_size += info.file_size
                if info.flag_bits & 0x1:
                    _error(details, f"archive.{name}", "不允许加密 ZIP")
                if info.compress_size and info.file_size / info.compress_size > 100:
                    _error(details, f"archive.{name}", "压缩比过高")
            if total_size > MAX_UNPACKED_BYTES:
                _error(details, "archive", "解压后总大小超过 300 MiB")
            if "manifest.json" not in member_names:
                _error(details, "manifest.json", "缺少 manifest.json")
            if details:
                raise EsqValidationError(details)
            manifest = _read_json(archive, "manifest.json")
            _validate_manifest(manifest, details)
            assets: dict[str, dict[str, Any]] = {}
            if "assets/index.json" in member_names:
                assets = _validate_asset_index(archive, _read_json(archive, "assets/index.json"), details)
            package_papers: list[dict[str, Any]] = []
            seen_paper_keys: set[str] = set()
            for reference_index, reference in enumerate(manifest.get("papers", [])):
                ref_path = f"manifest.papers[{reference_index}]"
                if not isinstance(reference, dict):
                    _error(details, ref_path, "必须是对象")
                    continue
                paper_key = reference.get("paperKey")
                paper_path = reference.get("path")
                answer_path = reference.get("answerPath")
                if paper_key in seen_paper_keys:
                    _error(details, f"{ref_path}.paperKey", "试卷 ID 重复")
                    continue
                seen_paper_keys.add(paper_key)
                if paper_path not in member_names:
                    _error(details, f"{ref_path}.path", "题目文件不存在")
                    continue
                if answer_path not in member_names:
                    _error(details, f"{ref_path}.answerPath", "答案文件不存在")
                    continue
                paper = _read_json(archive, paper_path)
                answers = _read_json(archive, answer_path)
                labels = _read_json(archive, reference["labelPath"]) if reference.get("labelPath") in member_names else None
                normalized = _validate_paper(paper, reference, answers, labels, assets, details)
                package_papers.append(normalized)
            if details:
                raise EsqValidationError(details)
            return {
                "manifest": manifest,
                "papers": package_papers,
                "assets": assets,
                "source_path": str(path),
            }
    except EsqValidationError:
        raise
    except (OSError, zipfile.BadZipFile, KeyError) as error:
        raise EsqValidationError([{"path": "file", "reason": f"读取 ESQ 失败：{error}"}]) from error


def _validate_manifest(manifest: dict[str, Any], details: list[dict[str, str]]) -> None:
    if manifest.get("format") != "esq":
        _error(details, "manifest.format", "必须为 esq")
    schema_version = manifest.get("schemaVersion", "")
    if schema_version not in ("1.0", "1.1"):
        _error(details, "manifest.schemaVersion", "仅支持 ESQ 1.0 / 1.1")
    _key(manifest.get("packageId"), "manifest.packageId", details)
    if not isinstance(manifest.get("contentVersion"), str) or not SEMVER_RE.fullmatch(manifest["contentVersion"]):
        _error(details, "manifest.contentVersion", "必须是语义化版本号")
    _text(manifest.get("title", ""), "manifest.title", details)
    _text(manifest.get("subject", ""), "manifest.subject", details)
    _text(manifest.get("publisher", ""), "manifest.publisher", details)
    license_data = manifest.get("license")
    if not isinstance(license_data, dict):
        _error(details, "manifest.license", "必须是对象")
    elif not isinstance(license_data.get("notice"), str) or not license_data["notice"].strip():
        _error(details, "manifest.license.notice", "必须填写使用声明")
    source = manifest.get("source")
    if not isinstance(source, dict):
        _error(details, "manifest.source", "必须是对象")
    elif not isinstance(source.get("description"), str) or not source["description"].strip():
        _error(details, "manifest.source.description", "必须填写来源说明")
    papers = manifest.get("papers")
    if not isinstance(papers, list) or not papers:
        _error(details, "manifest.papers", "至少包含一套试卷")
    if schema_version == "1.1":
        for index, paper_entry in enumerate(papers):
            path = f"manifest.papers[{index}]"
            if not isinstance(paper_entry, dict):
                continue
            exam_type = paper_entry.get("examType")
            if isinstance(exam_type, str) and exam_type not in {"", *SUPPORTED_EXAM_TYPES}:
                _error(details, f"{path}.examType", "不支持的考试类型")
            exam_month = paper_entry.get("examMonth")
            if exam_month is not None and not isinstance(exam_month, int):
                _error(details, f"{path}.examMonth", "必须是整数")
            set_number = paper_entry.get("setNumber")
            if set_number is not None and not isinstance(set_number, int):
                _error(details, f"{path}.setNumber", "必须是整数")
            listening_tracks = paper_entry.get("listeningTracks")
            if listening_tracks is not None and not isinstance(listening_tracks, list):
                _error(details, f"{path}.listeningTracks", "必须是数组")
