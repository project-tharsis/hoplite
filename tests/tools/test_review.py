"""Tests for review_evaluation tool."""
import json
import tempfile
import os
from unittest import mock

from src.tools.review import review_evaluation


def _make_kb_entries(entries: list[dict]) -> str:
    """Write entries to a temp JSON file and return the path."""
    f = tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False)
    json.dump(entries, f, ensure_ascii=False)
    f.flush()
    f.close()
    return f.name


def _base_entry(match_id: str = "123", **overrides) -> dict:
    entry = {
        "match_id": match_id,
        "timestamp": "2024-01-01T00:00:00",
        "opponent": "Liverpool",
        "score": "3-1",
        "result": "W",
        "competition": "Premier League",
        "pre_match_context": {"opponent_quality": "top6", "venue": "home"},
        "predicted_plan": {},
        "features": {"missing_data": ["xG"]},
        "weak_labels": {
            "model_signals": {"1": "🟡"},
            "dimension_signals": {"execution": "🟡"},
            "overall_signal": "🟡",
        },
        "evaluation": {
            "source": "llm",
            "model_signals": {"1": "🟡", "2": "🟢"},
            "dimension_signals": {"execution": "🟡", "adjustment": "🟢"},
            "overall_signal": "🟡",
            "narrative": "Test narrative",
        },
        "human_override": None,
    }
    entry.update(overrides)
    return entry


def _review_input(match_id: str = "123") -> dict:
    return {
        "match_id": match_id,
        "reviewer": "shuo",
        "review_status": "corrected",
        "corrected_overall_signal": "🟡",
        "corrected_model_signals": {"1": "🟢", "2": "🟡"},
        "corrected_dimension_signals": {"execution": "🟡", "adjustment": "🟡"},
        "comments": "Win was useful but control was mixed.",
    }


def test_successful_review():
    """review_evaluation writes human_override to matching entry."""
    entry = _base_entry()
    path = _make_kb_entries([entry])

    with mock.patch("src.tools.review.paths") as mock_paths:
        mock_paths.DEFAULT_KB_PATH = type("P", (), {"__str__": lambda s: path})()
        result = review_evaluation(_review_input())

    assert result["ok"] is True
    override = result["entry"]["human_override"]
    assert override["reviewer"] == "shuo"
    assert override["review_status"] == "corrected"
    assert override["corrected_overall_signal"] == "🟡"
    assert override["corrected_model_signals"] == {"1": "🟢", "2": "🟡"}
    assert override["corrected_dimension_signals"] == {"execution": "🟡", "adjustment": "🟡"}
    assert override["comments"] == "Win was useful but control was mixed."
    assert "reviewed_at" in override

    # Verify persisted to disk
    with open(path) as f:
        persisted = json.load(f)
    assert persisted[0]["human_override"]["reviewer"] == "shuo"

    os.unlink(path)


def test_match_id_not_found():
    """Returns error when match_id doesn't exist."""
    entry = _base_entry(match_id="999")
    path = _make_kb_entries([entry])

    with mock.patch("src.tools.review.paths") as mock_paths:
        mock_paths.DEFAULT_KB_PATH = type("P", (), {"__str__": lambda s: path})()
        result = review_evaluation(_review_input(match_id="123"))

    assert result["ok"] is False
    assert result["error"]["code"] == "NOT_FOUND"
    assert "123" in result["error"]["message"]

    os.unlink(path)


def test_original_evaluation_preserved():
    """Original weak_labels and evaluation are NOT overwritten."""
    entry = _base_entry()
    original_weak_labels = json.loads(json.dumps(entry["weak_labels"]))
    original_evaluation = json.loads(json.dumps(entry["evaluation"]))
    path = _make_kb_entries([entry])

    with mock.patch("src.tools.review.paths") as mock_paths:
        mock_paths.DEFAULT_KB_PATH = type("P", (), {"__str__": lambda s: path})()
        result = review_evaluation(_review_input())

    assert result["ok"] is True
    # weak_labels must be unchanged
    assert result["entry"]["weak_labels"] == original_weak_labels
    # evaluation must be unchanged
    assert result["entry"]["evaluation"] == original_evaluation

    os.unlink(path)


def test_human_override_written_correctly():
    """All human_override fields are correctly set."""
    entry = _base_entry()
    path = _make_kb_entries([entry])

    review_data = {
        "match_id": "123",
        "reviewer": "shuo",
        "review_status": "corrected",
        "corrected_overall_signal": "🔴",
        "corrected_model_signals": {"1": "🟢", "3": "🔴"},
        "corrected_dimension_signals": {"execution": "🟢", "satisfaction": "🔴"},
        "comments": "Poor defensive identity.",
    }

    with mock.patch("src.tools.review.paths") as mock_paths:
        mock_paths.DEFAULT_KB_PATH = type("P", (), {"__str__": lambda s: path})()
        result = review_evaluation(review_data)

    override = result["entry"]["human_override"]
    assert override["reviewer"] == "shuo"
    assert override["review_status"] == "corrected"
    assert override["corrected_overall_signal"] == "🔴"
    assert override["corrected_model_signals"]["3"] == "🔴"
    assert override["corrected_dimension_signals"]["satisfaction"] == "🔴"
    assert override["comments"] == "Poor defensive identity."
    # reviewed_at should be an ISO timestamp string
    assert "T" in override["reviewed_at"]

    os.unlink(path)


def test_missing_match_id():
    """Returns error when match_id is missing from input."""
    result = review_evaluation({"reviewer": "shuo"})
    assert result["ok"] is False
    assert result["error"]["code"] == "MISSING_FIELD"
