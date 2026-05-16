import json
import pytest
from datetime import datetime

from src.evaluation.knowledge import KnowledgeBase


@pytest.fixture
def kb(tmp_path):
    path = tmp_path / "test_knowledge.json"
    return KnowledgeBase(str(path))


def make_entry(
    match_id="fixture_001",
    opponent="PSV",
    score="7-1",
    result="W",
    competition="Champions League",
    venue="away",
    opponent_quality="mid_table",
    timestamp=None,
):
    return {
        "match_id": match_id,
        "timestamp": timestamp or datetime.now().isoformat(),
        "opponent": opponent,
        "score": score,
        "result": result,
        "competition": competition,
        "pre_match_context": {
            "opponent_quality": opponent_quality,
            "venue": venue,
            "competition_stage": "knockout",
            "injury_situation": "full_strength",
        },
        "predicted_plan": {
            "focus_areas": ["控制中场"],
            "likely_approach": "高位防线 + 快速转换",
            "key_battles": ["中场 — Rice vs DM"],
            "expected_subs": "60' Trossard",
        },
        "evaluation": {
            "execution_signal": "🟢",
            "adjustment_signal": "🟢",
            "satisfaction_signal": "🟢",
            "model_signals": {
                "1": "🟢",
                "2": "🟢",
                "3": "🟢",
                "4": "🟢",
                "5": "🟡",
                "6": "🟢",
            },
        },
    }


def test_save_entry_adds_to_json(kb):
    entry = make_entry()
    kb.save_entry(entry)
    data = kb.get_all()
    assert len(data) == 1
    assert data[0]["match_id"] == "fixture_001"


def test_query_filters_opponent(kb):
    kb.save_entry(make_entry(match_id="m1", opponent="PSV"))
    kb.save_entry(make_entry(match_id="m2", opponent="Real Madrid"))
    kb.save_entry(make_entry(match_id="m3", opponent="PSV"))

    results = kb.query(opponent="PSV")
    assert len(results) == 2
    assert {r["match_id"] for r in results} == {"m1", "m3"}


def test_query_filters_result(kb):
    kb.save_entry(make_entry(match_id="m1", result="W"))
    kb.save_entry(make_entry(match_id="m2", result="L"))
    kb.save_entry(make_entry(match_id="m3", result="W"))

    results = kb.query(result="W")
    assert len(results) == 2
    assert {r["match_id"] for r in results} == {"m1", "m3"}


def test_query_filters_venue(kb):
    kb.save_entry(make_entry(match_id="m1", venue="home"))
    kb.save_entry(make_entry(match_id="m2", venue="away"))
    kb.save_entry(make_entry(match_id="m3", venue="home"))

    results = kb.query(venue="home")
    assert len(results) == 2
    assert {r["match_id"] for r in results} == {"m1", "m3"}


def test_query_returns_most_recent_first(kb):
    kb.save_entry(make_entry(match_id="m1", timestamp="2025-03-01T12:00:00"))
    kb.save_entry(make_entry(match_id="m2", timestamp="2025-03-03T12:00:00"))
    kb.save_entry(make_entry(match_id="m3", timestamp="2025-03-02T12:00:00"))

    results = kb.query(limit=10)
    assert results[0]["match_id"] == "m2"
    assert results[1]["match_id"] == "m3"
    assert results[2]["match_id"] == "m1"


def test_query_respects_limit(kb):
    for i in range(5):
        kb.save_entry(make_entry(match_id=f"m{i}"))
    assert len(kb.query(limit=3)) == 3


def test_find_similar_context(kb):
    kb.save_entry(make_entry(match_id="m1", opponent_quality="mid_table", venue="away"))
    kb.save_entry(make_entry(match_id="m2", opponent_quality="top", venue="away"))
    kb.save_entry(make_entry(match_id="m3", opponent_quality="mid_table", venue="away"))
    kb.save_entry(make_entry(match_id="m4", opponent_quality="mid_table", venue="home"))

    results = kb.find_similar_context("mid_table", "away")
    assert len(results) == 2
    assert {r["match_id"] for r in results} == {"m1", "m3"}


def test_find_similar_context_limit(kb):
    for i in range(5):
        kb.save_entry(make_entry(match_id=f"m{i}", opponent_quality="mid_table", venue="away"))
    assert len(kb.find_similar_context("mid_table", "away", limit=2)) == 2


def test_get_patterns(kb):
    e1 = make_entry(match_id="m1")
    e1["evaluation"]["model_signals"]["1"] = "🟢"
    kb.save_entry(e1)

    e2 = make_entry(match_id="m2")
    e2["evaluation"]["model_signals"]["1"] = "🟡"
    kb.save_entry(e2)

    e3 = make_entry(match_id="m3")
    e3["evaluation"]["model_signals"]["1"] = "🔴"
    kb.save_entry(e3)

    e4 = make_entry(match_id="m4")
    e4["evaluation"]["model_signals"]["1"] = "🟢"
    kb.save_entry(e4)

    patterns = kb.get_patterns("1")
    assert patterns == {"🟢": 2, "🟡": 1, "🔴": 1}


def test_get_patterns_empty_kb(kb):
    patterns = kb.get_patterns("1")
    assert patterns == {"🟢": 0, "🟡": 0, "🔴": 0}


def test_empty_kb_get_all(kb):
    assert kb.get_all() == []


def test_empty_kb_query(kb):
    assert kb.query() == []


def test_empty_kb_find_similar_context(kb):
    assert kb.find_similar_context("mid_table", "away") == []


def test_save_entry_auto_timestamp(kb):
    entry = make_entry()
    del entry["timestamp"]
    kb.save_entry(entry)
    data = kb.get_all()
    assert "timestamp" in data[0]
