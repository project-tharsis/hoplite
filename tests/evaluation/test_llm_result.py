"""Test LLM result validation."""
import copy
import pytest
from src.evaluation.llm_result import validate_llm_result


VALID_RESULT = {
    "overall_signal": "🟢",
    "model_signals": {
        "1": "🟢", "2": "🟢", "3": "🟡",
        "4": "🟢", "5": "🟡", "6": "🟢",
    },
    "dimension_signals": {
        "execution": "🟢",
        "adjustment": "🟡",
        "satisfaction": "🟢",
    },
    "narrative": "阿森纳通过控制中场和定位球威胁掌控了比赛节奏。",
    "evidence": {
        "1": ["黄牌1张，犯规10次"],
        "2": ["射门差+4", "xG差+0.7"],
        "3": ["丢1球，对手射正3次"],
        "4": ["定位球进1个"],
        "5": ["胜场，传球85%，控球55%"],
        "6": ["替补上场后进球"],
    },
    "confidence": {
        "1": "high", "2": "high", "3": "medium",
        "4": "high", "5": "medium", "6": "high",
    },
    "missing_or_weak_evidence": [],
    "weak_label_disagreements": [],
}


def _fresh():
    return copy.deepcopy(VALID_RESULT)


def test_valid_result_passes():
    """Fully valid result returns normalized dict."""
    result = validate_llm_result(_fresh())
    assert result["overall_signal"] == "🟢"
    assert result["model_signals"]["1"] == "🟢"


def test_invalid_overall_signal():
    """Bad overall_signal raises ValueError."""
    data = _fresh()
    data["overall_signal"] = "invalid"
    with pytest.raises(ValueError, match="overall_signal"):
        validate_llm_result(data)


def test_missing_model_key():
    """Missing model signal key raises ValueError."""
    data = _fresh()
    del data["model_signals"]["3"]
    with pytest.raises(ValueError, match="model_signals missing keys"):
        validate_llm_result(data)


def test_invalid_model_signal_value():
    """Non-emoji model signal value raises ValueError."""
    data = _fresh()
    data["model_signals"]["1"] = "GOOD"
    with pytest.raises(ValueError, match="not a valid signal"):
        validate_llm_result(data)


def test_missing_dimension_key():
    """Missing dimension key raises."""
    data = _fresh()
    del data["dimension_signals"]["execution"]
    with pytest.raises(ValueError, match="dimension_signals missing keys"):
        validate_llm_result(data)


def test_empty_narrative():
    """Empty narrative raises."""
    data = _fresh()
    data["narrative"] = ""
    with pytest.raises(ValueError, match="narrative"):
        validate_llm_result(data)


def test_save_evaluation_dedup():
    """save_evaluation upserts — same match_id doesn't create duplicates."""
    import tempfile
    from src.tools.save_evaluation import save_evaluation
    from src.evaluation.knowledge import KnowledgeBase

    with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
        f.write("[]")
        f.flush()
        fname = f.name

    report = {
        "match": {
            "fixture_id": 99999,
            "date": "2025-01-01T00:00:00",
            "competition": "Premier League",
            "arsenal_score": 2,
            "opponent_score": 0,
            "result": "W",
        },
        "context": {"opponent": "Test FC", "opponent_quality": "lower", "venue": "home"},
        "predicted_plan": {"focus_areas": ["控制中场"]},
    }

    import src.paths as paths
    orig = paths.DEFAULT_KB_PATH
    paths.DEFAULT_KB_PATH = fname

    try:
        r1 = save_evaluation(report, _fresh())
        assert r1["ok"] is True, f"r1 failed: {r1}"

        r2 = save_evaluation(report, _fresh())
        assert r2["ok"] is True

        kb = KnowledgeBase(fname)
        data = kb.get_all()
        assert len(data) == 1  # upserted, not appended
    finally:
        paths.DEFAULT_KB_PATH = orig
