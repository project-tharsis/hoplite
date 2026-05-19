"""Tests for Phase 2: features persistence in save_evaluation."""
from __future__ import annotations

import copy
import json
import tempfile

import pytest

from src.evaluation.llm_result import validate_llm_result


# ── Fixtures ────────────────────────────────────────────────────────

VALID_EVALUATION = {
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

SAMPLE_REPORT = {
    "match": {
        "fixture_id": 12345,
        "date": "2025-05-01T15:00:00",
        "competition": "Premier League",
        "arsenal_score": 3,
        "opponent_score": 2,
        "result": "W",
    },
    "context": {"opponent": "Bournemouth", "opponent_quality": "mid_table", "venue": "home"},
    "predicted_plan": {"focus_areas": ["控制中场"]},
}

SAMPLE_FEATURES = {
    "result": "W",
    "score_margin": 1,
    "arsenal_goals": 3,
    "opponent_goals": 2,
    "opponent_name": "Bournemouth",
    "venue": "home",
    "opponent_quality": "mid_table",
    "possession_for": 62.0,
    "possession_against": 38.0,
    "possession_delta": 24.0,
    "shots_for": 18,
    "shots_against": 11,
    "shot_delta": 7,
    "missing_data": ["xG", "pressing", "pressing_recoveries", "transition"],
}

SAMPLE_WEAK_LABELS = {
    "model_signals": {
        "culture_as_os": "🟢",
        "where_game_is_played": "🟡",
        "defence_as_attacking_identity": "🟡",
        "marginal_gains": "🟡",
        "add_capability_keep_identity": "🟡",
        "role_clarity": "🟡",
    },
    "dimension_signals": {
        "execution": "🟡",
        "adjustment": "🟡",
        "satisfaction": "🟡",
    },
    "overall_signal": "🟡",
    "confidence": {},
    "evidence_refs": {},
    "missing_data_penalty": True,
    "weak_label_version": "v1",
}

SAMPLE_VERSIONS = {
    "features": "v1",
    "weak_label": "v1",
    "rubric": "arteta_v1",
    "prompt_builder": "v1",
}


def _fresh_eval():
    return copy.deepcopy(VALID_EVALUATION)


# ── Tests ───────────────────────────────────────────────────────────


class TestSaveEvaluationFeatures:
    """Phase 2: features are persisted in the KB entry."""

    def test_features_persisted_in_entry(self):
        """When features are provided, they appear in the saved entry."""
        from src.tools.save_evaluation import save_evaluation
        import src.paths as paths

        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            f.write("[]")
            fname = f.name

        orig = paths.DEFAULT_KB_PATH
        paths.DEFAULT_KB_PATH = fname
        try:
            result = save_evaluation(
                SAMPLE_REPORT,
                _fresh_eval(),
                weak_labels=SAMPLE_WEAK_LABELS,
                versions=SAMPLE_VERSIONS,
                features=SAMPLE_FEATURES,
            )
            assert result["ok"] is True
            entry = result["entry"]
            assert "features" in entry
            assert entry["features"]["result"] == "W"
            assert entry["features"]["score_margin"] == 1
            assert entry["features"]["possession_delta"] == 24.0
        finally:
            paths.DEFAULT_KB_PATH = orig

    def test_features_empty_when_not_provided(self):
        """Without features param, entry has empty features dict."""
        from src.tools.save_evaluation import save_evaluation
        import src.paths as paths

        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            f.write("[]")
            fname = f.name

        orig = paths.DEFAULT_KB_PATH
        paths.DEFAULT_KB_PATH = fname
        try:
            result = save_evaluation(
                SAMPLE_REPORT,
                _fresh_eval(),
                weak_labels=SAMPLE_WEAK_LABELS,
                versions=SAMPLE_VERSIONS,
            )
            assert result["ok"] is True
            entry = result["entry"]
            assert "features" in entry
            assert entry["features"] == {}
        finally:
            paths.DEFAULT_KB_PATH = orig

    def test_version_fields_persisted(self):
        """All version fields are persisted."""
        from src.tools.save_evaluation import save_evaluation
        import src.paths as paths

        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            f.write("[]")
            fname = f.name

        orig = paths.DEFAULT_KB_PATH
        paths.DEFAULT_KB_PATH = fname
        try:
            result = save_evaluation(
                SAMPLE_REPORT,
                _fresh_eval(),
                versions=SAMPLE_VERSIONS,
                features=SAMPLE_FEATURES,
            )
            entry = result["entry"]
            assert entry["features_version"] == "v1"
            assert entry["weak_label_version"] == "v1"
            assert entry["rubric_version"] == "arteta_v1"
            assert entry["prompt_builder_version"] == "v1"
        finally:
            paths.DEFAULT_KB_PATH = orig

    def test_legacy_entry_readable_after_new_save(self):
        """Legacy entries (no features) can coexist with new entries."""
        from src.tools.save_evaluation import save_evaluation
        from src.evaluation.knowledge import KnowledgeBase
        import src.paths as paths

        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            # Write a legacy entry (no features field)
            legacy = [{
                "match_id": "legacy-1",
                "timestamp": "2024-01-01T00:00:00",
                "opponent": "Test FC",
                "score": "1-0",
                "result": "W",
                "evaluation": {"overall_signal": "🟢", "model_signals": {}, "dimension_signals": {}},
                "human_override": None,
            }]
            json.dump(legacy, f)
            fname = f.name

        orig = paths.DEFAULT_KB_PATH
        paths.DEFAULT_KB_PATH = fname
        try:
            # Save a new entry with features
            result = save_evaluation(
                SAMPLE_REPORT,
                _fresh_eval(),
                features=SAMPLE_FEATURES,
                versions=SAMPLE_VERSIONS,
            )
            assert result["ok"] is True

            # Read back — both entries should be present
            kb = KnowledgeBase(fname)
            data = kb.get_all()
            assert len(data) == 2

            # Legacy entry has no features
            legacy_entry = next(e for e in data if e["match_id"] == "legacy-1")
            assert "features" not in legacy_entry

            # New entry has features
            new_entry = next(e for e in data if e["match_id"] == "12345")
            assert new_entry["features"]["result"] == "W"
        finally:
            paths.DEFAULT_KB_PATH = orig

    def test_strict_validation_still_enforced(self):
        """Strict validation still rejects invalid evaluations."""
        from src.tools.save_evaluation import save_evaluation

        bad_eval = _fresh_eval()
        bad_eval["overall_signal"] = "INVALID"

        result = save_evaluation(SAMPLE_REPORT, bad_eval)
        assert result["ok"] is False
        assert result["error"]["code"] == "VALIDATION_FAILED"
