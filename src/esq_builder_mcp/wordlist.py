"""词表工具：kajweb 高频词解析 + 真题热点词统计。

规则来源（esq-question-bank-import 技能 v2.15）:
- kajweb/dict JSONL 每行一个对象, 必须逐行 json.loads（整文件 load 报 Extra data）
- wordRank = 真题词频排序 → 天然高频序
- 热点词: 近两年真题 passage 词频, 去停用词, [a-zA-Z][a-zA-Z'-]{3,}
"""

from __future__ import annotations

import json
import re
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z'\-]{3,}")

STOPWORDS = frozenset(
    ["the", "and", "for", "are", "but", "not", "you", "all", "any", "can", "had", "her", "was", "one", "our", "out", "day", "get", "has", "him", "his", "how", "man", "new", "now", "old", "see", "two", "way", "who", "boy", "did", "its", "let", "put", "say", "she", "too", "use", "that", "with", "have", "this", "will", "your", "from", "they", "know", "want", "been", "good", "much", "some", "time", "very", "when", "come", "here", "just", "like", "long", "make", "many", "more", "only", "over", "such", "take", "than", "them", "well", "were", "what", "which", "there", "would", "about", "their", "other", "into", "could", "these", "first", "then", "look", "only", "come", "over", "think", "also", "back", "after", "work", "give", "most"]
)


def _jsonl_texts(path: Path) -> list[str]:
    """统一取文本：.jsonl/.json 直接读；kajweb book/*.zip 取其中全部 .json/.jsonl 成员。"""
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            members = [
                info for info in zf.infolist()
                if info.filename.lower().endswith((".json", ".jsonl")) and not info.is_dir()
            ]
            if not members:
                raise ValueError(f"ZIP 内没有 .json/.jsonl 词表成员: {path.name}")
            return [zf.read(info).decode("utf-8", errors="replace") for info in members]
    return [path.read_text(encoding="utf-8")]


def parse_wordlist(jsonl_path: str, top_n: int | None = None, level: str | None = None) -> dict:
    """解析 kajweb/dict 高频词表（.jsonl 或 book zip）。返回 {ok, count, words: [{rank, word, phonetic, translations, synonyms}]}。"""
    path = Path(jsonl_path)
    if not path.exists():
        return {"ok": False, "error": f"文件不存在: {path}"}

    try:
        texts = _jsonl_texts(path)
    except (ValueError, zipfile.BadZipFile) as error:
        return {"ok": False, "error": str(error)}

    words: list[dict[str, Any]] = []
    bad_lines = 0
    for text in texts:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                bad_lines += 1
                continue
            content = entry.get("content", {})
            word_content = content.get("word", {}).get("content", {})
            words.append(
                {
                    "rank": entry.get("wordRank"),
                    "word": entry.get("headWord"),
                    "phonetic": word_content.get("usphone", ""),
                    "translations": [
                        {"pos": t.get("pos", ""), "tran": t.get("tranCn", "")}
                        for t in word_content.get("trans", [])
                    ],
                    "synonyms": [
                        {"pos": s.get("pos", ""), "words": [w.get("w", "") for w in s.get("words", [])]}
                        for s in word_content.get("syno", [])
                    ],
                }
            )

    words = [w for w in words if w["word"]]
    words.sort(key=lambda w: (w["rank"] is None, w["rank"] if w["rank"] is not None else 0))
    if top_n:
        words = words[:top_n]
    return {"ok": True, "level": level, "count": len(words), "bad_lines": bad_lines, "words": words}


def hot_words(
    texts: list[str],
    since_year: int = 2023,
    top_n: int = 300,
    extra_stopwords: list[str] | None = None,
) -> dict:
    """真题 passage 文本 → 热点词频统计。

    texts: [{year: int, text: str}] 或纯文本列表。
    规则: 近两年(year >= since_year), 正则 [a-zA-Z][a-zA-Z'-]{3,}, 小写, 去停用词。
    """
    counter: Counter[str] = Counter()
    stop = STOPWORDS | {w.lower() for w in (extra_stopwords or [])}
    scanned = 0
    for item in texts:
        if isinstance(item, dict):
            year = item.get("year")
            text = item.get("text", "")
            if year is not None and year < since_year:
                continue
        else:
            text = str(item)
        scanned += 1
        for match in WORD_RE.findall(text):
            word = match.lower().strip("'-")
            if len(word) >= 4 and word not in stop:
                counter[word] += 1

    top = [{"term": word, "count": count} for word, count in counter.most_common(top_n)]
    return {"ok": True, "texts_scanned": scanned, "unique_words": len(counter), "hot_words": top}
