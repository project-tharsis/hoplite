"""End-to-end tests for the v2 JSON pipeline.

Covers:
  1. Raw/report input → features → weak labels → structured prompt
  2. Fake strict v2 LLM output → save_evaluation (verify saved)
  3. JSON entry contains features, weak_labels, evaluation, and version fields
  4. Legacy LLM output without v2 fields is rejected by save_evaluation (strict mode)
  5. Human review writes human_override
  6. Replay weak-label-only report runs and reports skipped legacy entries
  7. Calibration hints include sample quality and guardrails
  8. Substitute scorer regression
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.features.extractor import FeatureExtractor, MatchFeatures
from src.labels.weak_labeler import WeakLabeler, MODEL_6
from src.tools.prepare_evaluation import prepare_evaluation
from src.tools.save_evaluation import save_evaluation
from src.tools.review import review_evaluation
from src.evaluation.calibration import CalibrationComputer
from src.evaluation.knowledge import KnowledgeBase
from scripts.replay_history import replay_weak_label_only


# ═══════════════════════════════════════════════════════════════════════
# Synthetic fixtures
# ═══════════════════════════════════════════════════════════════════════


def _raw_match_json() -> dict:
    """Synthetic Arsenal 3-2 Bournemouth raw match JSON (inspired by fixture 1379160)."""
    return {
        "fixture_id": 1379160,
        "date": "2026-05-10T15:00:00",
        "competition": "Premier League",
        "home_team": "Arsenal",
        "away_team": "Bournemouth",
        "home_score": 3,
        "away_score": 2,
        "home_xg": 2.1,
        "away_xg": 1.3,
        "home_stats": {
            "Ball Possession": "58%",
            "Total Shots": 15,
            "Shots on Goal": 7,
            "Passes %": "86%",
            "Corner Kicks": 8,
            "Fouls": 11,
        },
        "away_stats": {
            "Ball Possession": "42%",
            "Total Shots": 10,
            "Shots on Goal": 4,
            "Passes %": "78%",
            "Corner Kicks": 3,
            "Fouls": 13,
        },
        "events": [
            {"minute": 12, "type": "Goal", "team": "home", "player": "Saka", "detail": "Normal Goal"},
            {"minute": 34, "type": "Goal", "team": "away", "player": "Solanke", "detail": "Normal Goal"},
            {"minute": 58, "type": "Goal", "team": "away", "player": "Tavernier", "detail": "Normal Goal"},
            {"minute": 60, "type": "subst", "team": "home", "player": "Trossard", "detail": "Substitution - Trossard in"},
            {"minute": 72, "type": "Goal", "team": "home", "player": "Trossard", "detail": "Normal Goal"},
            {"minute": 85, "type": "Goal", "team": "home", "player": "Havertz", "detail": "Normal Goal"},
        ],
    }


def _sub_scorer_match_json() -> dict:
    """Minimal synthetic match: Arsenal home, sub Trossard comes on and scores.

    All stats provided to minimise missing_data (only pressing/transition remain).
    """
    return {
        "fixture_id": 999999,
        "date": "2026-04-01T20:00:00",
        "competition": "Premier League",
        "home_team": "Arsenal",
        "away_team": "Wolves",
        "home_score": 2,
        "away_score": 0,
        "home_xg": 1.8,
        "away_xg": 0.4,
        "home_stats": {
            "Ball Possession": "65%",
            "Total Shots": 14,
            "Shots on Goal": 6,
            "Passes %": "89%",
            "Corner Kicks": 7,
            "Fouls": 8,
        },
        "away_stats": {
            "Ball Possession": "35%",
            "Total Shots": 6,
            "Shots on Goal": 2,
            "Passes %": "74%",
            "Corner Kicks": 2,
            "Fouls": 12,
        },
        "events": [
            {"minute": 25, "type": "Goal", "team": "home", "player": "Saka", "detail": "Normal Goal"},
            {"minute": 58, "type": "subst", "team": "home", "player": "Trossard", "detail": "Substitution - Trossard in"},
            {"minute": 73, "type": "Goal", "team": "home", "player": "Trossard", "detail": "Normal Goal", "assist": "Saka"},
        ],
    }


def _strict_v2_evaluation() -> dict:
    """A valid strict v2 LLM evaluation output."""
    return {
        "overall_signal": "🟡",
        "model_signals": {
            "1": "🟡", "2": "🟡", "3": "🟡",
            "4": "🟢", "5": "🟡", "6": "🟢",
        },
        "dimension_signals": {
            "execution": "🟡",
            "adjustment": "🟢",
            "satisfaction": "🟡",
        },
        "confidence": {
            "1": "medium", "2": "medium", "3": "medium",
            "4": "high", "5": "medium", "6": "high",
        },
        "evidence": {
            "1": ["yellow_cards_for=2"],
            "2": ["shot_delta=-3", "possession_delta=16.0"],
            "3": ["goals_conceded=2"],
            "4": ["set_piece_goals_for=0"],
            "5": ["result=W", "pass_accuracy_for=86.0"],
            "6": ["arsenal_sub_count=1", "goals_by_substitutes=1"],
        },
        "missing_or_weak_evidence": ["xG", "pressing"],
        "weak_label_disagreements": [],
        "narrative": "阿森纳主场3-2逆转伯恩茅斯。上半场Saka破门但对手连入两球反超，下半场Trossard替补登场后迅速扳平，Havertz绝杀。球队展现了强大的精神力和调整能力，但防守端仍有隐患。Arteta的换人时机精准，替补球员的即时影响力值得肯定。整体而言，这是一场体现Culture as OS精神的比赛——在逆境中保持信念，最终拿下三分。",
    }


def _legacy_evaluation() -> dict:
    """Legacy LLM output — missing v2 fields (evidence, confidence, etc.)."""
    return {
        "overall_signal": "🟡",
        "model_signals": {
            "1": "🟡", "2": "🟡", "3": "🟡",
            "4": "🟢", "5": "🟡", "6": "🟢",
        },
        "dimension_signals": {
            "execution": "🟡",
            "adjustment": "🟢",
            "satisfaction": "🟡",
        },
        "narrative": "简短的比赛叙述。",
    }


def _minimal_report() -> dict:
    """Minimal report JSON for save_evaluation input."""
    return {
        "match": {
            "fixture_id": 1379160,
            "date": "2026-05-10T15:00:00",
            "competition": "Premier League",
            "home_team": "Arsenal",
            "away_team": "Bournemouth",
            "arsenal_score": 3,
            "opponent_score": 2,
            "result": "W",
        },
        "context": {
            "opponent": "Bournemouth",
            "opponent_quality": "mid_table",
            "venue": "home",
            "competition_stage": "league_late",
        },
        "predicted_plan": {"focus_areas": ["set_pieces", "transitions"]},
    }


# ═══════════════════════════════════════════════════════════════════════
# 1. Raw/report → features → weak labels → structured prompt
# ═══════════════════════════════════════════════════════════════════════


class TestPrepareEvaluationPipeline:
    """Test 1: prepare_evaluation produces features, weak labels, and prompt."""

    def test_raw_match_produces_full_output(self):
        result = prepare_evaluation(_raw_match_json())
        assert result["ok"] is True
        assert "features" in result
        assert "weak_labels" in result
        assert "rubric_version" in result
        assert "prompt" in result

    def test_features_include_result_and_goals(self):
        result = prepare_evaluation(_raw_match_json())
        features = result["features"]
        assert features["result"] == "W"
        assert features["arsenal_goals"] == 3
        assert features["opponent_goals"] == 2
        assert features["score_margin"] == 1

    def test_weak_labels_include_model_signals(self):
        result = prepare_evaluation(_raw_match_json())
        wl = result["weak_labels"]
        assert "model_signals" in wl
        assert "dimension_signals" in wl
        assert "overall_signal" in wl
        assert wl["overall_signal"] in ("🟢", "🟡", "🔴")
        # All 6 models present
        assert len(wl["model_signals"]) == 6

    def test_prompt_is_nonempty_string(self):
        result = prepare_evaluation(_raw_match_json(), output_format="prompt")
        assert isinstance(result, str)
        assert len(result) > 100


# ═══════════════════════════════════════════════════════════════════════
# 2. Strict v2 LLM output → save_evaluation (verify saved)
# ═══════════════════════════════════════════════════════════════════════


class TestSaveEvaluationV2:
    """Tests 2 & 3: save_evaluation with strict v2 output persists all fields."""

    def _save_and_read(self, tmp_path: Path) -> dict:
        """Save a v2 evaluation to a temp KB and return the saved entry."""
        kb_path = tmp_path / "knowledge.json"
        # Monkey-patch paths for this test
        import src.paths as paths
        orig = paths.DEFAULT_KB_PATH
        paths.DEFAULT_KB_PATH = kb_path
        try:
            result = save_evaluation(
                _minimal_report(),
                _strict_v2_evaluation(),
                weak_labels={"overall_signal": "🟡", "model_signals": {}},
                versions={
                    "features": "v1",
                    "weak_label": "v1",
                    "rubric": "arteta_v1",
                    "prompt_builder": "v1",
                },
                features={"result": "W", "score_margin": 1},
            )
            assert result["ok"] is True
            return result["entry"]
        finally:
            paths.DEFAULT_KB_PATH = orig

    def test_save_returns_ok(self, tmp_path):
        entry = self._save_and_read(tmp_path)
        assert entry["match_id"] == "1379160"

    def test_entry_contains_features(self, tmp_path):
        entry = self._save_and_read(tmp_path)
        assert "features" in entry
        assert entry["features"]["result"] == "W"

    def test_entry_contains_weak_labels(self, tmp_path):
        entry = self._save_and_read(tmp_path)
        assert "weak_labels" in entry
        assert entry["weak_labels"]["overall_signal"] == "🟡"

    def test_entry_contains_evaluation(self, tmp_path):
        entry = self._save_and_read(tmp_path)
        assert "evaluation" in entry
        assert entry["evaluation"]["source"] == "llm"
        assert entry["evaluation"]["overall_signal"] == "🟡"
        assert "1" in entry["evaluation"]["model_signals"]
        assert "evidence" in entry["evaluation"]
        assert "confidence" in entry["evaluation"]

    def test_entry_contains_version_fields(self, tmp_path):
        entry = self._save_and_read(tmp_path)
        assert entry["features_version"] == "v1"
        assert entry["weak_label_version"] == "v1"
        assert entry["rubric_version"] == "arteta_v1"
        assert entry["prompt_builder_version"] == "v1"

    def test_entry_has_human_override_null(self, tmp_path):
        entry = self._save_and_read(tmp_path)
        assert entry["human_override"] is None


# ═══════════════════════════════════════════════════════════════════════
# 4. Legacy output rejected by save_evaluation (strict mode)
# ═══════════════════════════════════════════════════════════════════════


class TestLegacyEvaluationRejected:
    """Test 4: Legacy LLM output without v2 fields is rejected."""

    def test_legacy_output_rejected(self, tmp_path):
        import src.paths as paths
        orig = paths.DEFAULT_KB_PATH
        paths.DEFAULT_KB_PATH = tmp_path / "knowledge.json"
        try:
            result = save_evaluation(
                _minimal_report(),
                _legacy_evaluation(),
            )
            assert result["ok"] is False
            assert result["error"]["code"] == "VALIDATION_FAILED"
            # The error message should mention strict mode
            assert "strict" in result["error"]["message"].lower() or "Strict" in result["error"]["message"]
        finally:
            paths.DEFAULT_KB_PATH = orig


# ═══════════════════════════════════════════════════════════════════════
# 5. Human review writes human_override
# ═══════════════════════════════════════════════════════════════════════


class TestHumanReview:
    """Test 5: review_evaluation writes human_override into KB entry."""

    def _save_then_review(self, tmp_path: Path) -> dict:
        """Save an entry, then review it, return the reviewed entry."""
        import src.paths as paths
        orig = paths.DEFAULT_KB_PATH
        kb_path = tmp_path / "knowledge.json"
        paths.DEFAULT_KB_PATH = kb_path
        try:
            # Save first
            save_evaluation(
                _minimal_report(),
                _strict_v2_evaluation(),
                weak_labels={"overall_signal": "🟡"},
                versions={"features": "v1", "weak_label": "v1", "rubric": "arteta_v1", "prompt_builder": "v1"},
                features={"result": "W"},
            )

            # Review
            review_input = {
                "match_id": "1379160",
                "reviewer": "shuo",
                "review_status": "corrected",
                "corrected_overall_signal": "🟢",
                "corrected_model_signals": {
                    "1": "🟢", "2": "🟡", "3": "🟡",
                    "4": "🟢", "5": "🟢", "6": "🟢",
                },
                "corrected_dimension_signals": {
                    "execution": "🟢",
                    "adjustment": "🟢",
                    "satisfaction": "🟢",
                },
                "comments": "防守问题被进攻效率弥补了。",
            }
            result = review_evaluation(review_input)
            assert result["ok"] is True
            return result["entry"]
        finally:
            paths.DEFAULT_KB_PATH = orig

    def test_review_writes_human_override(self, tmp_path):
        entry = self._save_then_review(tmp_path)
        assert entry["human_override"] is not None

    def test_review_preserves_original_evaluation(self, tmp_path):
        entry = self._save_then_review(tmp_path)
        # Original evaluation should still be present
        assert entry["evaluation"]["overall_signal"] == "🟡"
        # Human override has different signal
        assert entry["human_override"]["corrected_overall_signal"] == "🟢"

    def test_review_has_reviewer_and_timestamp(self, tmp_path):
        entry = self._save_then_review(tmp_path)
        override = entry["human_override"]
        assert override["reviewer"] == "shuo"
        assert "reviewed_at" in override
        assert override["review_status"] == "corrected"

    def test_review_has_corrected_signals(self, tmp_path):
        entry = self._save_then_review(tmp_path)
        override = entry["human_override"]
        assert override["corrected_overall_signal"] == "🟢"
        assert override["corrected_model_signals"]["1"] == "🟢"
        assert override["corrected_dimension_signals"]["execution"] == "🟢"
        assert "防守问题" in override["comments"]


# ═══════════════════════════════════════════════════════════════════════
# 6. Replay reports skipped legacy entries
# ═══════════════════════════════════════════════════════════════════════


class TestReplayHistory:
    """Test 6: replay_history skips legacy entries without features."""

    def test_replay_skips_legacy_entries(self, tmp_path):
        kb_path = tmp_path / "knowledge.json"
        # Create KB with one legacy entry (no features) and one v2 entry
        entries = [
            {
                "match_id": "legacy-1",
                "opponent": "Chelsea",
                "result": "L",
                "score": "0-1",
                "evaluation": {
                    "overall_signal": "🔴",
                    "model_signals": {"1": "🔴"},
                    "dimension_signals": {},
                },
                # No features — legacy entry
            },
            {
                "match_id": "v2-1",
                "opponent": "Bournemouth",
                "result": "W",
                "score": "3-2",
                "features": {
                    "result": "W",
                    "score_margin": 1,
                    "arsenal_goals": 3,
                    "opponent_goals": 2,
                    "yellow_cards_for": 1,
                    "red_cards_for": 0,
                    "fouls_for": 10,
                    "fouls_against": 12,
                    "possession_for": 58.0,
                    "possession_against": 42.0,
                    "possession_delta": 16.0,
                    "shots_for": 15,
                    "shots_against": 10,
                    "shot_delta": 5,
                    "shots_on_target_for": 7,
                    "shots_on_target_against": 4,
                    "shot_on_target_delta": 3,
                    "xg_for": 2.1,
                    "xg_against": 1.3,
                    "xg_delta": 0.8,
                    "pass_accuracy_for": 86.0,
                    "pass_accuracy_against": 78.0,
                    "pass_accuracy_delta": 8.0,
                    "corners_for": 8,
                    "corners_against": 3,
                    "corner_delta": 5,
                    "opponent_shots_on_target": 4,
                    "set_piece_goals_for": 0,
                    "set_piece_goals_against": 0,
                    "goals_conceded": 2,
                    "arsenal_sub_count": 0,
                    "goals_after_arsenal_subs": 0,
                    "goals_by_substitutes": 0,
                    "substitution_windows": [],
                    "score_state_timeline": [],
                    "missing_data": [],
                },
                "weak_labels": {
                    "overall_signal": "🟡",
                    "model_signals": {"1": "🟡"},
                    "dimension_signals": {"execution": "🟡", "adjustment": "🟡", "satisfaction": "🟡"},
                },
            },
        ]
        with open(kb_path, "w") as f:
            json.dump(entries, f)

        report = replay_weak_label_only(str(kb_path))

        # Summary
        assert report["summary"]["total_entries"] == 2
        assert report["summary"]["skipped"] == 1
        assert report["summary"]["replayed"] == 1

        # Skipped entry
        assert len(report["skipped"]) == 1
        assert report["skipped"][0]["match_id"] == "legacy-1"
        assert "missing features" in report["skipped"][0]["reason"]

    def test_replay_is_deterministic(self, tmp_path):
        """Running replay twice gives identical results."""
        kb_path = tmp_path / "knowledge.json"
        entries = [
            {
                "match_id": "v2-1",
                "features": {
                    "result": "W", "score_margin": 1, "arsenal_goals": 2,
                    "opponent_goals": 1, "yellow_cards_for": 0, "red_cards_for": 0,
                    "fouls_for": 8, "fouls_against": 10, "possession_for": 55.0,
                    "possession_against": 45.0, "possession_delta": 10.0,
                    "shots_for": 12, "shots_against": 8, "shot_delta": 4,
                    "shots_on_target_for": 5, "shots_on_target_against": 3,
                    "shot_on_target_delta": 2, "xg_for": 1.5, "xg_against": 0.8,
                    "xg_delta": 0.7, "pass_accuracy_for": 85.0,
                    "pass_accuracy_against": 80.0, "pass_accuracy_delta": 5.0,
                    "corners_for": 6, "corners_against": 3, "corner_delta": 3,
                    "opponent_shots_on_target": 3, "set_piece_goals_for": 1,
                    "set_piece_goals_against": 0, "goals_conceded": 1,
                    "arsenal_sub_count": 0, "goals_after_arsenal_subs": 0,
                    "goals_by_substitutes": 0, "substitution_windows": [],
                    "score_state_timeline": [], "missing_data": [],
                },
                "weak_labels": {
                    "overall_signal": "🟢",
                    "model_signals": {"1": "🟢", "2": "🟢", "3": "🟢", "4": "🟢", "5": "🟢", "6": "🟡"},
                    "dimension_signals": {"execution": "🟢", "adjustment": "🟡", "satisfaction": "🟢"},
                },
            },
        ]
        with open(kb_path, "w") as f:
            json.dump(entries, f)

        r1 = replay_weak_label_only(str(kb_path))
        r2 = replay_weak_label_only(str(kb_path))
        assert r1 == r2

    def test_replay_never_mutates_kb(self, tmp_path):
        """Replay does not modify knowledge.json."""
        kb_path = tmp_path / "knowledge.json"
        entries = [{"match_id": "legacy-1", "result": "W"}]
        with open(kb_path, "w") as f:
            json.dump(entries, f)

        before = kb_path.read_text()
        replay_weak_label_only(str(kb_path))
        after = kb_path.read_text()
        assert before == after


# ═══════════════════════════════════════════════════════════════════════
# 7. Calibration hints include sample quality and guardrails
# ═══════════════════════════════════════════════════════════════════════


class TestCalibrationHints:
    """Test 7: CalibrationComputer produces guarded hints with sample quality."""

    def _seed_kb(self, tmp_path: Path, n: int = 5, with_features: bool = True) -> str:
        """Create a KB with n entries for calibration testing."""
        kb_path = tmp_path / "knowledge.json"
        entries = []
        for i in range(n):
            entry = {
                "match_id": str(100 + i),
                "opponent": "Bournemouth",
                "result": "W" if i % 2 == 0 else "D",
                "score": "2-1" if i % 2 == 0 else "1-1",
                "pre_match_context": {
                    "opponent": "Bournemouth",
                    "opponent_quality": "mid_table",
                    "venue": "home",
                    "competition_stage": "league_late",
                },
                "evaluation": {
                    "overall_signal": "🟢" if i % 2 == 0 else "🟡",
                    "model_signals": {
                        "1": "🟢", "2": "🟡", "3": "🟢",
                        "4": "🟡", "5": "🟢", "6": "🟡",
                    },
                    "dimension_signals": {
                        "execution": "🟢",
                        "adjustment": "🟡",
                        "satisfaction": "🟢",
                    },
                },
            }
            if with_features:
                entry["features"] = {"result": "W", "missing_data": ["xG"]}
            entries.append(entry)
        with open(kb_path, "w") as f:
            json.dump(entries, f)
        return str(kb_path)

    def test_hints_include_sample_quality(self, tmp_path):
        kb_path = self._seed_kb(tmp_path, n=5)
        cc = CalibrationComputer(kb_path)
        hints = cc.build_hints(
            {"opponent_quality": "mid_table", "venue": "home", "competition_stage": "league_late"},
            limit=5,
        )
        assert "sample_quality" in hints
        sq = hints["sample_quality"]
        assert "with_features" in sq
        assert "with_human_review" in sq
        assert "legacy_only" in sq
        assert sq["with_features"] == 5

    def test_hints_include_guardrails(self, tmp_path):
        kb_path = self._seed_kb(tmp_path, n=5)
        cc = CalibrationComputer(kb_path)
        hints = cc.build_hints(
            {"opponent_quality": "mid_table", "venue": "home"},
            limit=5,
        )
        assert "guardrails" in hints
        assert len(hints["guardrails"]) > 0
        assert any("reference only" in g.lower() for g in hints["guardrails"])

    def test_hints_confidence_high_with_sufficient_v2_entries(self, tmp_path):
        kb_path = self._seed_kb(tmp_path, n=6, with_features=True)
        cc = CalibrationComputer(kb_path)
        hints = cc.build_hints(
            {"opponent_quality": "mid_table", "venue": "home", "competition_stage": "league_late"},
            limit=6,
        )
        assert hints["confidence"] == "high"
        assert hints["count"] == 6

    def test_hints_confidence_medium_with_few_entries(self, tmp_path):
        kb_path = self._seed_kb(tmp_path, n=3, with_features=True)
        cc = CalibrationComputer(kb_path)
        hints = cc.build_hints(
            {"opponent_quality": "mid_table", "venue": "home", "competition_stage": "league_late"},
            limit=5,
        )
        assert hints["confidence"] == "medium"

    def test_hints_confidence_low_with_few_entries(self, tmp_path):
        kb_path = self._seed_kb(tmp_path, n=2, with_features=True)
        cc = CalibrationComputer(kb_path)
        hints = cc.build_hints(
            {"opponent_quality": "mid_table", "venue": "home", "competition_stage": "league_late"},
            limit=5,
        )
        assert hints["confidence"] == "low"

    def test_hints_confidence_capped_when_mostly_legacy(self, tmp_path):
        """When most entries are legacy-only, confidence caps at medium."""
        kb_path = tmp_path / "knowledge.json"
        entries = []
        for i in range(6):
            entry = {
                "match_id": str(200 + i),
                "opponent": "Bournemouth",
                "result": "W",
                "score": "2-1",
                "pre_match_context": {
                    "opponent_quality": "mid_table",
                    "venue": "home",
                    "competition_stage": "league_late",
                },
                "evaluation": {
                    "overall_signal": "🟢",
                    "model_signals": {"1": "🟢", "2": "🟡", "3": "🟢", "4": "🟡", "5": "🟢", "6": "🟡"},
                    "dimension_signals": {"execution": "🟢", "adjustment": "🟡", "satisfaction": "🟢"},
                },
            }
            # Only 1 out of 6 has features
            if i == 0:
                entry["features"] = {"result": "W", "missing_data": []}
            entries.append(entry)
        with open(kb_path, "w") as f:
            json.dump(entries, f)

        cc = CalibrationComputer(str(kb_path))
        hints = cc.build_hints(
            {"opponent_quality": "mid_table", "venue": "home", "competition_stage": "league_late"},
            limit=6,
        )
        # Most are legacy-only → capped at medium
        assert hints["confidence"] == "medium"
        assert hints["sample_quality"]["legacy_only"] == 5

    def test_hints_empty_when_no_matches(self, tmp_path):
        kb_path = tmp_path / "knowledge.json"
        with open(kb_path, "w") as f:
            json.dump([], f)

        cc = CalibrationComputer(str(kb_path))
        hints = cc.build_hints({"opponent_quality": "top6"}, limit=5)
        assert hints["count"] == 0
        assert hints["confidence"] == "low"
        assert hints["sample_quality"]["with_features"] == 0


# ═══════════════════════════════════════════════════════════════════════
# 8. Substitute scorer regression
# ═══════════════════════════════════════════════════════════════════════


class TestSubstituteScorerRegression:
    """Test 8: Substitute who scores → goals_by_substitutes > 0, model 6 green + high confidence."""

    def test_sub_appears_in_extract_sub_impact(self):
        """Substitution player appears in extract_sub_impact as 'player' field."""
        from src.tools.extract import extract_key_events, extract_sub_impact

        match = _sub_scorer_match_json()
        events = extract_key_events(match)
        subs = extract_sub_impact(events)

        # Trossard should appear as a sub
        sub_players = [s["player"] for s in subs]
        assert "Trossard" in sub_players

    def test_sub_scorer_goals_by_substitutes_positive(self):
        """Same player scores after coming on → features.goals_by_substitutes > 0."""
        features = FeatureExtractor().extract(_sub_scorer_match_json())
        assert features.goals_by_substitutes > 0
        assert features.goals_by_substitutes == 1

    def test_sub_scorer_goals_after_subs_positive(self):
        """Goals after Arsenal subs should also be > 0."""
        features = FeatureExtractor().extract(_sub_scorer_match_json())
        assert features.goals_after_arsenal_subs > 0

    def test_sub_scorer_sub_windows_correct(self):
        """Substitution windows record Trossard at minute 58."""
        features = FeatureExtractor().extract(_sub_scorer_match_json())
        assert len(features.substitution_windows) == 1
        assert features.substitution_windows[0]["player"] == "Trossard"
        assert features.substitution_windows[0]["minute"] == 58

    def test_model_6_confidence_high_with_sub_goal(self):
        """Model 6 confidence is high when sub scores (no missing data penalty)."""
        # Build features manually with empty missing_data to avoid penalty
        features = MatchFeatures(
            result="W",
            score_margin=2,
            arsenal_goals=2,
            opponent_goals=0,
            goals_conceded=0,
            yellow_cards_for=0,
            red_cards_for=0,
            fouls_for=8,
            fouls_against=12,
            possession_for=65.0,
            possession_against=35.0,
            possession_delta=30.0,
            shots_for=14,
            shots_against=6,
            shot_delta=8,
            shots_on_target_for=6,
            shots_on_target_against=2,
            shot_on_target_delta=4,
            xg_for=1.8,
            xg_against=0.4,
            xg_delta=1.4,
            pass_accuracy_for=89.0,
            pass_accuracy_against=74.0,
            pass_accuracy_delta=15.0,
            corners_for=7,
            corners_against=2,
            corner_delta=5,
            opponent_shots_on_target=2,
            set_piece_goals_for=0,
            set_piece_goals_against=0,
            arsenal_sub_count=1,
            goals_after_arsenal_subs=1,
            goals_by_substitutes=1,
            substitution_windows=[{"minute": 58, "player": "Trossard", "scored_after": True}],
            score_state_timeline=[
                {"minute": 0, "arsenal_score": 0, "opponent_score": 0},
                {"minute": 25, "arsenal_score": 1, "opponent_score": 0},
                {"minute": 73, "arsenal_score": 2, "opponent_score": 0},
            ],
            missing_data=[],  # No missing data → no penalty
        )

        wl = WeakLabeler().label(features)

        # Model 6 should be GREEN with high confidence
        assert wl.model_signals[MODEL_6] == "🟢"
        assert wl.confidence[MODEL_6] == "high"

    def test_model_6_green_through_full_pipeline(self):
        """Full pipeline: sub scorer → model 6 signal is GREEN."""
        features = FeatureExtractor().extract(_sub_scorer_match_json())
        wl = WeakLabeler().label(features)

        # Model 6 signal should be GREEN (sub before 70', goals after, goals_by_sub > 0)
        assert wl.model_signals[MODEL_6] == "🟢"

    def test_sub_scorer_match_result(self):
        """The sub-scorer match should be a clean win."""
        features = FeatureExtractor().extract(_sub_scorer_match_json())
        assert features.result == "W"
        assert features.score_margin == 2
        assert features.opponent_name == "Wolves"
