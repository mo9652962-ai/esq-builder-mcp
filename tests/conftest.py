"""共享 fixture: 最小合法 ESQ 包。"""

from __future__ import annotations

import pytest

MANIFEST = {
    "packageId": "cn.test.demo",
    "contentVersion": "1.0.0",
    "title": "测试包",
    "subject": "英语",
    "publisher": "tester",
    "license": {"notice": "仅供测试"},
    "source": {"description": "测试数据源"},
}

READING_UNIT = {
    "unitKey": "cn.test.reading.y2024.u1",
    "type": "reading",
    "title": "阅读",
    "sequence": 1,
    "passage": {"blocks": [{"type": "paragraph", "text": "Hello world. This is a test passage."}]},
    "questions": [
        {
            "questionKey": "cn.test.reading.y2024.u1.q1",
            "number": 1,
            "type": "single_choice",
            "stem": "What does the passage say?",
            "options": [
                {"key": "A", "content": "Yes"},
                {"key": "B", "content": "No"},
            ],
            "score": 2,
        }
    ],
}

CLOZE_UNIT = {
    "unitKey": "cn.test.cloze.y2024.u1",
    "type": "cloze",
    "title": "完形",
    "sequence": 1,
    "passage": {"blocks": [{"type": "paragraph", "text": "I {{blank:1}} a cat. It {{blank:2}} cute."}]},
    "questions": [
        {
            "questionKey": "cn.test.cloze.y2024.u1.q1",
            "number": 1,
            "type": "single_choice",
            "stem": "1",
            "options": [{"key": "A", "content": "have"}, {"key": "B", "content": "has"}],
            "score": 1,
        },
        {
            "questionKey": "cn.test.cloze.y2024.u1.q2",
            "number": 2,
            "type": "single_choice",
            "stem": "2",
            "options": [{"key": "A", "content": "is"}, {"key": "B", "content": "are"}],
            "score": 1,
        },
    ],
}

CANDIDATES_CLOZE_UNIT = {
    "unitKey": "cn.test.bank.y2024.u1",
    "type": "cloze",
    "title": "选词填空",
    "sequence": 1,
    "passage": {"blocks": [{"type": "paragraph", "text": "She {{blank:1}} to school."}]},
    "candidates": [
        {"key": "A", "content": "goes"},
        {"key": "B", "content": "going"},
    ],
    "questions": [
        {
            "questionKey": "cn.test.bank.y2024.u1.q1",
            "number": 1,
            "type": "single_choice",
            "stem": "1",
            "score": 1,
        }
    ],
}


@pytest.fixture
def manifest() -> dict:
    return dict(MANIFEST)


@pytest.fixture
def papers() -> list[dict]:
    return [
        {"paperKey": "cn.test.reading.y2024", "year": 2024, "units": [READING_UNIT]},
        {"paperKey": "cn.test.cloze.y2024", "year": 2024, "units": [CLOZE_UNIT]},
    ]


@pytest.fixture
def answers() -> dict:
    return {
        "cn.test.reading.y2024": {"cn.test.reading.y2024.u1.q1": {"correctOption": "A", "score": 2}},
        "cn.test.cloze.y2024": {
            "cn.test.cloze.y2024.u1.q1": {"correctOption": "A", "score": 1},
            "cn.test.cloze.y2024.u1.q2": {"correctOption": "A", "score": 1},
        },
    }


@pytest.fixture
def candidates_paper() -> dict:
    return {"paperKey": "cn.test.bank.y2024", "year": 2024, "units": [CANDIDATES_CLOZE_UNIT]}
