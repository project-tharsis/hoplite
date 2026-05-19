"""Tests for CalibrationComputer."""
import json
import tempfile
from src.evaluation.calibration import CalibrationComputer


def _write_kb(entries: list[dict]) -> str:
    """Write entries to a temp KB file and return the path."""
    f = tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False)
    json.dump(entries, f, ensure_ascii=False)
    f.flush()
    f.close()
    return f.name


def _make_entry(
    match_id: str = "1",
    result: str = "W",
    score: str = "3-1",
    opponent_quality: str = "mid_table",
    venue: str = "home",
    competition_stage: str = "league_early",
    features: dict | None = None,
    human_override: dict | None = None,
    evaluation: dict | None = None,
) -> dict:
    return {
        "match_id": match_id,
        "timestamp": "2024-01-01T00:00:00",
        "opponent": "TestFC",
        "score": score,
        "result": result,
        "competition": "Premier League",
        "pre_match_context": {
            "opponent_quality": opponent_quality,
            "venue": venue,
            "competition_stage": competition_stage,
        },
        "predicted_plan": {},
        "features": features or {},
        "weak_labels": {},
        "evaluation": evaluation or {
            "model_signals": {},
            "dimension_signals": {},
        },
        "human_override": human_override,
    }


CONTEXT = {
    "opponent_quality": "mid_table",
    "venue": "home",
    "competition_stage": "league_early",
}


def test_empty_kb():
    """Empty KB returns low confidence and zero counts."""
    path = _write_kb([])
    cc = CalibrationComputer(path)
    hints = cc.build_hints(CONTEXT)

    assert hints["count"] == 0
    assert hints["confidence"] == "low"
    assert hints["sample_quality"]["with_features"] == 0
    assert hints["sample_quality"]["with_human_review"] == 0
    assert hints["sample_quality"]["legacy_only"] == 0
    assert hints["record"]["wins"] == 0
    assert hints["guardrails"]  # non-empty


def test_low_confidence_lt3():
    """Fewer than 3 matches → confidence=low."""
    entries = [
        _make_entry(match_id=str(i), features={"missing_data": ["xG"]})
        for i in range(2)
    ]
    path = _write_kb(entries)
    cc = CalibrationComputer(path)
    hints = cc.build_hints(CONTEXT)

    assert hints["count"] == 2
    assert hints["confidence"] == "low"
    assert hints["sample_quality"]["with_features"] == 2


def test_medium_confidence_3_to_4():
    """3-4 matches → confidence=medium."""
    entries = [
        _make_entry(match_id=str(i), features={"missing_data": ["xG"]})
        for i in range(4)
    ]
    path = _write_kb(entries)
    cc = CalibrationComputer(path)
    hints = cc.build_hints(CONTEXT)

    assert hints["count"] == 4
    assert hints["confidence"] == "medium"


def test_high_confidence_5_with_features():
    """5+ matches, most with features → confidence=high."""
    entries = [
        _make_entry(
            match_id=str(i),
            features={"missing_data": []},
            evaluation={
                "model_signals": {"1": "🟢"},
                "dimension_signals": {"execution": "🟢"},
            },
        )
        for i in range(5)
    ]
    path = _write_kb(entries)
    cc = CalibrationComputer(path)
    hints = cc.build_hints(CONTEXT)

    assert hints["count"] == 5
    assert hints["confidence"] == "high"
    assert hints["sample_quality"]["with_features"] == 5
    assert hints["sample_quality"]["legacy_only"] == 0


def test_legacy_only_cap_at_medium():
    """5+ matches but mostly legacy-only → confidence capped at medium."""
    # 4 legacy-only (no features) + 1 with features
    entries = [_make_entry(match_id=str(i)) for i in range(4)]
    entries.append(
        _make_entry(match_id="5", features={"missing_data": ["xG"]})
    )
    path = _write_kb(entries)
    cc = CalibrationComputer(path)
    hints = cc.build_hints(CONTEXT)

    assert hints["count"] == 5
    assert hints["confidence"] == "medium"  # capped
    assert hints["sample_quality"]["legacy_only"] == 4
    assert hints["sample_quality"]["with_features"] == 1


def test_human_review_counting():
    """Entries with human_override counted in with_human_review."""
    entries = [
        _make_entry(
            match_id="1",
            features={"missing_data": []},
            human_override={"reviewer": "shuo", "review_status": "corrected"},
        ),
        _make_entry(match_id="2", features={"missing_data": []}),
        _make_entry(match_id="3", features={"missing_data": []}),
    ]
    path = _write_kb(entries)
    cc = CalibrationComputer(path)
    hints = cc.build_hints(CONTEXT)

    assert hints["count"] == 3
    assert hints["sample_quality"]["with_human_review"] == 1


def test_common_missing_data():
    """Common missing data fields are reported."""
    entries = [
        _make_entry(
            match_id=str(i),
            features={"missing_data": ["xG", "pressing", "transition"]},
        )
        for i in range(3)
    ]
    path = _write_kb(entries)
    cc = CalibrationComputer(path)
    hints = cc.build_hints(CONTEXT)

    assert "xG" in hints["common_missing_data"]
    assert "pressing" in hints["common_missing_data"]


def test_record_aggregation():
    """Wins/draws/losses and score averages are computed."""
    entries = [
        _make_entry(match_id="1", result="W", score="3-1"),
        _make_entry(match_id="2", result="D", score="1-1"),
        _make_entry(match_id="3", result="L", score="0-2"),
    ]
    path = _write_kb(entries)
    cc = CalibrationComputer(path)
    hints = cc.build_hints(CONTEXT)

    assert hints["record"]["wins"] == 1
    assert hints["record"]["draws"] == 1
    assert hints["record"]["losses"] == 1
    assert hints["record"]["avg_arsenal_score"] == round((3 + 1 + 0) / 3, 2)
    assert hints["record"]["avg_opponent_score"] == round((1 + 1 + 2) / 3, 2)


def test_build_hints_includes_known_blind_spots(tmp_path):
    """build_hints() must include known_blind_spots field."""
    import json
    from src.evaluation.calibration import CalibrationComputer
    kb_path = tmp_path / "kb.json"
    entries = [{
        "match_id": "1",
        "features": {"result": "L", "opponent_quality": "lower", "missing_data": []},
        "pre_match_context": {"opponent_quality": "lower", "venue": "away", "competition_stage": "regular"},
        "evaluation": {"model_signals": {}, "dimension_signals": {}, "overall_signal": "🔴"},
    }]
    with open(kb_path, "w") as f:
        json.dump(entries, f)
    cc = CalibrationComputer(str(kb_path))
    hints = cc.build_hints({"opponent_quality": "lower", "venue": "away"})
    assert "known_blind_spots" in hints
    spots = hints["known_blind_spots"]
    assert len(spots) >= 1
    assert spots[0]["id"] == "dominant_stats_loss"


def test_empty_hints_includes_known_blind_spots():
    """_empty_hints() must include known_blind_spots (at least one)."""
    from src.evaluation.calibration import CalibrationComputer
    empty = CalibrationComputer._empty_hints()
    assert "known_blind_spots" in empty
    spots = empty["known_blind_spots"]
    assert len(spots) >= 1
    assert spots[0]["id"] == "dominant_stats_loss"
