"""Tests for Phase 1: prepare_evaluation CLI command and extract_from_report."""
from __future__ import annotations

import pytest

from src.features.extractor import FeatureExtractor, MatchFeatures
from src.labels.weak_labeler import WeakLabels
from src.tools.prepare_evaluation import prepare_evaluation, _detect_input_shape


# ── Fixtures ────────────────────────────────────────────────────────


def _raw_match_json() -> dict:
    """Raw match JSON from fetch_match_data."""
    return {
        "fixture_id": 12345,
        "date": "2025-05-01T15:00:00",
        "competition": "Premier League",
        "home_team": "Arsenal",
        "away_team": "Bournemouth",
        "home_score": 3,
        "away_score": 2,
        "home_stats": {
            "Ball Possession": "62%",
            "Total Shots": 18,
            "Shots on Goal": 7,
            "Passes %": "88%",
            "Corner Kicks": 9,
            "Fouls": 10,
        },
        "away_stats": {
            "Ball Possession": "38%",
            "Total Shots": 11,
            "Shots on Goal": 4,
            "Passes %": "76%",
            "Corner Kicks": 3,
            "Fouls": 14,
        },
        "events": [
            {"minute": 12, "type": "Goal", "team": "home", "player": "Saka", "detail": "Normal Goal"},
            {"minute": 45, "type": "Goal", "team": "away", "player": "Solanke", "detail": "Normal Goal"},
            {"minute": 80, "type": "Goal", "team": "home", "player": "Nketiah", "detail": "Normal Goal"},
            {"minute": 85, "type": "Goal", "team": "home", "player": "Havertz", "detail": "Normal Goal"},
            {"minute": 90, "type": "Goal", "team": "away", "player": "Tavernier", "detail": "Normal Goal"},
        ],
    }


def _analyze_report_json() -> dict:
    """Simulated analyze_match report output."""
    return {
        "ok": True,
        "report": {
            "match": {
                "fixture_id": 12345,
                "date": "2025-05-01T15:00:00",
                "competition": "Premier League",
                "home_team": "Arsenal",
                "away_team": "Bournemouth",
                "home_score": 3,
                "away_score": 2,
                "arsenal_score": 3,
                "opponent_score": 2,
                "result": "W",
            },
            "predicted_plan": {},
            "context": {
                "opponent": "Bournemouth",
                "opponent_quality": "mid_table",
                "venue": "home",
                "competition_stage": "league_late",
            },
            "stats": {
                "score": {"arsenal": 3, "opponent": 2},
                "xg": {"arsenal": None, "opponent": None},
                "possession": {"arsenal": "62%", "opponent": "38%"},
                "shots": {"arsenal": 18, "opponent": 11},
                "shots_on_target": {"arsenal": 7, "opponent": 4},
                "passes": {
                    "arsenal": {"total": None, "accuracy": "88%"},
                    "opponent": {"total": None, "accuracy": "76%"},
                },
                "fouls": {"arsenal": 10, "opponent": 14},
                "corners": {"arsenal": 9, "opponent": 3},
                "goals": {"arsenal": {"total": 3}, "opponent": {"total": 2}},
                "cards": {"arsenal": {"yellow": 0, "red": 0}, "opponent": {"yellow": 0, "red": 0}},
            },
            "key_events": [
                {"minute": 12, "type": "goal", "raw_type": "Goal", "team": "Arsenal", "player": "Saka", "detail": "Normal Goal", "is_arsenal": True},
                {"minute": 45, "type": "goal", "raw_type": "Goal", "team": "Bournemouth", "player": "Solanke", "detail": "Normal Goal", "is_arsenal": False},
                {"minute": 80, "type": "goal", "raw_type": "Goal", "team": "Arsenal", "player": "Nketiah", "detail": "Normal Goal", "is_arsenal": True},
                {"minute": 85, "type": "goal", "raw_type": "Goal", "team": "Arsenal", "player": "Havertz", "detail": "Normal Goal", "is_arsenal": True},
                {"minute": 90, "type": "goal", "raw_type": "Goal", "team": "Bournemouth", "player": "Tavernier", "detail": "Normal Goal", "is_arsenal": False},
            ],
            "set_pieces": {"arsenal": 0, "opponent": 0, "details": []},
            "sub_impact": [],
            "one_line_summary": "Arsenal 3-2 Bournemouth (Premier League)",
        },
        "search_queries": [],
    }


def _empty_report() -> dict:
    """Report with minimal data — missing key fields."""
    return {"match": {"home_team": "", "away_team": "", "home_score": None, "away_score": None}, "stats": {}, "key_events": [], "context": {}, "set_pieces": {}, "sub_impact": []}


# ── Tests: Input shape detection ────────────────────────────────────


class TestDetectInputShape:

    def test_detects_raw_match(self):
        assert _detect_input_shape(_raw_match_json()) == "match"

    def test_detects_report(self):
        report = _analyze_report_json()
        assert _detect_input_shape(report) == "report"

    def test_detects_nested_report(self):
        wrapper = _analyze_report_json()
        assert _detect_input_shape(wrapper) == "report"

    def test_unknown_shape(self):
        assert _detect_input_shape({"foo": "bar"}) == "unknown"


# ── Tests: extract_from_report ──────────────────────────────────────


class TestExtractFromReport:

    def test_basic_extraction(self):
        report = _analyze_report_json()["report"]
        features = FeatureExtractor.extract_from_report(report)
        assert features.result == "W"
        assert features.arsenal_goals == 3
        assert features.opponent_goals == 2
        assert features.opponent_name == "Bournemouth"
        assert features.venue == "home"

    def test_missing_match_raises(self):
        with pytest.raises(ValueError, match="缺少 'match' 字段"):
            FeatureExtractor.extract_from_report({"stats": {}})

    def test_empty_teams_raises(self):
        with pytest.raises(ValueError, match="数据不完整"):
            FeatureExtractor.extract_from_report(_empty_report())

    def test_away_arsenal_report(self):
        """Arsenal playing away in a report."""
        report = {
            "match": {
                "fixture_id": 88888,
                "date": "2025-04-01T20:00:00",
                "competition": "Premier League",
                "home_team": "Man City",
                "away_team": "Arsenal",
                "home_score": 1,
                "away_score": 1,
                "arsenal_score": 1,
                "opponent_score": 1,
                "result": "D",
            },
            "stats": {},
            "key_events": [
                {"minute": 34, "type": "goal", "raw_type": "Goal", "team": "Man City", "player": "Haaland", "detail": "Normal Goal", "is_arsenal": False},
                {"minute": 72, "type": "goal", "raw_type": "Goal", "team": "Arsenal", "player": "Rice", "detail": "Normal Goal", "is_arsenal": True},
            ],
            "context": {},
            "set_pieces": {},
            "sub_impact": [],
        }
        features = FeatureExtractor.extract_from_report(report)
        assert features.result == "D"
        assert features.venue == "away"
        assert features.opponent_name == "Man City"

    def test_extract_from_report_deterministic(self):
        """Same report twice → same features."""
        report = _analyze_report_json()["report"]
        ext = FeatureExtractor()
        f1 = FeatureExtractor.extract_from_report(report)
        f2 = FeatureExtractor.extract_from_report(report)
        assert f1.to_dict() == f2.to_dict()


# ── Tests: prepare_evaluation ───────────────────────────────────────


class TestPrepareEvaluation:

    def test_raw_match_json(self):
        """Raw match JSON → features, weak_labels, prompt."""
        result = prepare_evaluation(_raw_match_json())
        assert result["ok"] is True
        assert "features" in result
        assert "weak_labels" in result
        assert "rubric_version" in result
        assert "prompt" in result
        assert result["features"]["result"] == "W"
        assert result["weak_labels"]["overall_signal"] in ("🟢", "🟡", "🔴")

    def test_analyze_report_json(self):
        """Analyze report → features, weak_labels, prompt."""
        report = _analyze_report_json()
        result = prepare_evaluation(report)
        assert result["ok"] is True
        assert result["features"]["result"] == "W"
        assert result["features"]["arsenal_goals"] == 3

    def test_report_json_direct(self):
        """Direct report dict (without ok wrapper)."""
        report = _analyze_report_json()["report"]
        result = prepare_evaluation(report)
        assert result["ok"] is True
        assert result["features"]["result"] == "W"

    def test_format_prompt(self):
        """--format prompt returns only the prompt string."""
        result = prepare_evaluation(_raw_match_json(), output_format="prompt")
        assert isinstance(result, str)
        assert len(result) > 100
        # Prompt should mention the match
        assert "3" in result or "阿森纳" in result or "Arsenal" in result

    def test_unknown_input_returns_error(self):
        """Underspecified input → structured error."""
        result = prepare_evaluation({"foo": "bar"})
        assert result["ok"] is False
        assert result["error"]["code"] == "UNSUPPORTED_INPUT"

    def test_empty_report_returns_error(self):
        """Report with no valid data → structured error."""
        result = prepare_evaluation(_empty_report())
        assert result["ok"] is False
        assert result["error"]["code"] == "EXTRACTION_FAILED"

    def test_features_has_expected_keys(self):
        """Features dict contains all expected feature fields."""
        result = prepare_evaluation(_raw_match_json())
        features = result["features"]
        assert "result" in features
        assert "score_margin" in features
        assert "possession_delta" in features
        assert "missing_data" in features

    def test_weak_labels_has_expected_keys(self):
        """Weak labels dict contains all expected fields."""
        result = prepare_evaluation(_raw_match_json())
        wl = result["weak_labels"]
        assert "model_signals" in wl
        assert "dimension_signals" in wl
        assert "overall_signal" in wl
        assert "confidence" in wl


# ── Tests: Report vs raw match feature parity ───────────────────────


class TestReportVsRawParity:
    """Features from report should roughly match features from raw match."""

    def test_result_parity(self):
        """Same match via raw and report → same result."""
        raw_features = FeatureExtractor().extract(_raw_match_json())
        report_features = FeatureExtractor.extract_from_report(
            _analyze_report_json()["report"]
        )
        assert raw_features.result == report_features.result
        assert raw_features.score_margin == report_features.score_margin
        assert raw_features.arsenal_goals == report_features.arsenal_goals
        assert raw_features.opponent_goals == report_features.opponent_goals
