"""Tests for Phase 3: JSON replay script."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from scripts.replay_history import features_from_dict, replay_weak_label_only, _compare_weak_labels
from src.features.extractor import MatchFeatures
from src.labels.weak_labeler import WeakLabeler


# ── Fixtures ────────────────────────────────────────────────────────


def _features_dict() -> dict:
    """A stored features dict that matches what save_evaluation persists."""
    return {
        "result": "W",
        "score_margin": 1,
        "arsenal_goals": 3,
        "opponent_goals": 2,
        "opponent_name": "Bournemouth",
        "opponent_quality": "mid_table",
        "venue": "home",
        "competition_stage": "league_late",
        "possession_for": 62.0,
        "possession_against": 38.0,
        "possession_delta": 24.0,
        "shots_for": 18,
        "shots_against": 11,
        "shot_delta": 7,
        "shots_on_target_for": 7,
        "shots_on_target_against": 4,
        "shot_on_target_delta": 3,
        "corners_for": 9,
        "corners_against": 3,
        "corner_delta": 6,
        "fouls_for": 10,
        "fouls_against": 14,
        "yellow_cards_for": 0,
        "red_cards_for": 0,
        "goals_conceded": 2,
        "set_piece_goals_for": 0,
        "set_piece_goals_against": 0,
        "substitution_windows": [],
        "arsenal_sub_count": 0,
        "goals_after_arsenal_subs": 0,
        "goals_by_substitutes": 0,
        "score_state_timeline": [],
        "predicted_plan_match_features": {},
        "missing_data": ["xG", "pressing", "pressing_recoveries", "transition"],
    }


def _weak_labels_dict() -> dict:
    """Weak labels that would be produced from _features_dict."""
    mf = features_from_dict(_features_dict())
    wl = WeakLabeler().label(mf)
    return {
        "model_signals": wl.model_signals,
        "dimension_signals": wl.dimension_signals,
        "overall_signal": wl.overall_signal,
        "confidence": wl.confidence,
        "evidence_refs": wl.evidence_refs,
        "missing_data_penalty": wl.missing_data_penalty,
        "weak_label_version": wl.weak_label_version,
    }


def _kb_with_mixed_entries() -> list[dict]:
    """KB with one entry with features, one without, one with mismatched labels."""
    features = _features_dict()
    wl = _weak_labels_dict()

    return [
        # Entry WITH features and correct weak labels
        {
            "match_id": "11111",
            "timestamp": "2025-05-01T15:00:00",
            "opponent": "Bournemouth",
            "score": "3-2",
            "result": "W",
            "features": features,
            "weak_labels": wl,
            "evaluation": {"overall_signal": "🟢", "model_signals": {}, "dimension_signals": {}},
        },
        # Entry WITHOUT features (legacy)
        {
            "match_id": "22222",
            "timestamp": "2025-01-01T15:00:00",
            "opponent": "Test FC",
            "score": "1-0",
            "result": "W",
            "evaluation": {"overall_signal": "🟢", "model_signals": {}, "dimension_signals": {}},
        },
        # Entry WITH features but MISMATCHED weak labels
        {
            "match_id": "33333",
            "timestamp": "2025-04-01T15:00:00",
            "opponent": "Chelsea",
            "score": "2-1",
            "result": "W",
            "features": features,
            "weak_labels": {
                **wl,
                "overall_signal": "🟢",  # deliberately wrong
            },
            "evaluation": {"overall_signal": "🟢", "model_signals": {}, "dimension_signals": {}},
        },
    ]


# ── Tests ───────────────────────────────────────────────────────────


class TestFeaturesFromDict:

    def test_roundtrip(self):
        """features_from_dict produces a valid MatchFeatures."""
        d = _features_dict()
        mf = features_from_dict(d)
        assert isinstance(mf, MatchFeatures)
        assert mf.result == "W"
        assert mf.score_margin == 1
        assert mf.possession_for == 62.0

    def test_ignores_extra_keys(self):
        """Extra keys in stored dict are ignored gracefully."""
        d = _features_dict()
        d["extra_field"] = "should_be_ignored"
        d["another_extra"] = 42
        mf = features_from_dict(d)
        assert mf.result == "W"

    def test_uses_defaults_for_missing_keys(self):
        """Missing keys use MatchFeatures defaults."""
        d = {"result": "L", "score_margin": -2}
        mf = features_from_dict(d)
        assert mf.result == "L"
        assert mf.score_margin == -2
        assert mf.arsenal_goals == 0  # default
        assert mf.missing_data == []  # default


class TestCompareWeakLabels:

    def test_no_changes(self):
        """Identical labels → empty changes."""
        wl = _weak_labels_dict()
        changes = _compare_weak_labels(wl, wl)
        assert changes == []

    def test_overall_signal_change(self):
        """Different overall_signal detected."""
        stored = _weak_labels_dict()
        recomputed = _weak_labels_dict()
        recomputed["overall_signal"] = "🟢"
        changes = _compare_weak_labels(stored, recomputed)
        assert len(changes) == 1
        assert changes[0]["field"] == "weak_labels.overall_signal"

    def test_model_signal_change(self):
        """Different model signal detected."""
        stored = _weak_labels_dict()
        recomputed = _weak_labels_dict()
        recomputed["model_signals"]["culture_as_os"] = "🔴"
        changes = _compare_weak_labels(stored, recomputed)
        assert any(c["field"] == "weak_labels.model_signals.culture_as_os" for c in changes)

    def test_dimension_signal_change(self):
        """Different dimension signal detected."""
        stored = _weak_labels_dict()
        recomputed = _weak_labels_dict()
        recomputed["dimension_signals"]["execution"] = "🔴"
        changes = _compare_weak_labels(stored, recomputed)
        assert any(c["field"] == "weak_labels.dimension_signals.execution" for c in changes)


class TestReplayWeakLabelOnly:

    def test_full_replay(self):
        """Full replay with mixed entries."""
        kb_data = _kb_with_mixed_entries()
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            json.dump(kb_data, f)
            kb_path = f.name

        report = replay_weak_label_only(kb_path)

        assert report["summary"]["total_entries"] == 3
        assert report["summary"]["replayed"] == 2  # 2 with features
        assert report["summary"]["skipped"] == 1   # 1 without features
        assert report["skipped"][0]["match_id"] == "22222"
        assert report["skipped"][0]["reason"] == "missing features"

    def test_changes_detected(self):
        """Mismatched weak labels are detected."""
        kb_data = _kb_with_mixed_entries()
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            json.dump(kb_data, f)
            kb_path = f.name

        report = replay_weak_label_only(kb_path)
        assert report["summary"]["changed"] >= 1
        # Entry 33333 has deliberately wrong overall_signal
        changed_ids = [c["match_id"] for c in report["changes"]]
        assert "33333" in changed_ids

    def test_no_changes_when_labels_match(self):
        """If all labels match, changed count is 0."""
        features = _features_dict()
        wl = _weak_labels_dict()
        kb_data = [
            {
                "match_id": "99999",
                "features": features,
                "weak_labels": wl,
            },
        ]
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            json.dump(kb_data, f)
            kb_path = f.name

        report = replay_weak_label_only(kb_path)
        assert report["summary"]["changed"] == 0
        assert report["summary"]["replayed"] == 1
        assert report["summary"]["skipped"] == 0
        assert report["changes"] == []

    def test_kb_not_mutated(self):
        """replay_history never writes to the KB file."""
        kb_data = _kb_with_mixed_entries()
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            json.dump(kb_data, f)
            kb_path = f.name

        # Read before
        with open(kb_path) as f:
            before = f.read()

        replay_weak_label_only(kb_path)

        # Read after
        with open(kb_path) as f:
            after = f.read()

        assert before == after

    def test_deterministic(self):
        """Same input twice → same report."""
        kb_data = _kb_with_mixed_entries()
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            json.dump(kb_data, f)
            kb_path = f.name

        r1 = replay_weak_label_only(kb_path)
        r2 = replay_weak_label_only(kb_path)
        assert r1 == r2

    def test_empty_kb(self):
        """Empty KB → zero everything, no crash."""
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            json.dump([], f)
            kb_path = f.name

        report = replay_weak_label_only(kb_path)
        assert report["summary"]["total_entries"] == 0
        assert report["summary"]["replayed"] == 0
        assert report["summary"]["changed"] == 0


# ── Tests: replay_compare_human ─────────────────────────────────────


def test_replay_compare_human_includes_reviewed_entries(tmp_path):
    """replay with --compare-human must include human_comparisons."""
    import json as json_mod
    kb_path = tmp_path / "kb.json"
    entries = [
        {
            "match_id": "reviewed-1",
            "features": {
                "result": "L", "opponent_quality": "lower", "venue": "away",
                "competition_stage": "regular", "opponent_name": "Southampton",
                "arsenal_goals": 1, "opponent_goals": 2, "score_margin": -1,
                "goals_conceded": 2, "yellow_cards_for": 1, "red_cards_for": 0,
                "possession_for": 64.0, "possession_against": 36.0, "possession_delta": 28.0,
                "shots_for": 23, "shots_against": 8, "shot_delta": 15,
                "shots_on_target_for": 7, "shots_on_target_against": 4, "shot_on_target_delta": 3,
                "xg_for": 2.10, "xg_against": 0.80, "xg_delta": 1.30,
                "pass_accuracy_for": 89.0, "pass_accuracy_against": 79.0, "pass_accuracy_delta": 10.0,
                "corners_for": 9, "corners_against": 4, "corner_delta": 5,
                "fouls_for": 11, "fouls_against": 9,
                "substitution_windows": [], "arsenal_sub_count": 0,
                "goals_after_arsenal_subs": 0, "goals_by_substitutes": 0,
                "score_state_timeline": [], "set_piece_goals_for": 0, "set_piece_goals_against": 0,
                "predicted_plan_match_features": {}, "missing_data": [],
            },
            "weak_labels": {"overall_signal": "🟡", "model_signals": {}, "dimension_signals": {}},
            "evaluation": {"overall_signal": "🔴", "model_signals": {}, "dimension_signals": {}},
            "human_override": {
                "reviewer": "shuo", "review_status": "confirmed",
                "corrected_overall_signal": "🔴",
                "corrected_model_signals": {"1": "🟢", "5": "🔴"},
                "corrected_dimension_signals": {"satisfaction": "🔴"},
            },
        },
    ]
    with open(kb_path, "w") as f:
        json_mod.dump(entries, f)

    from scripts.replay_history import replay_compare_human
    report = replay_compare_human(str(kb_path))

    assert "human_comparisons" in report
    assert len(report["human_comparisons"]) == 1
    comp = report["human_comparisons"][0]
    assert comp["match_id"] == "reviewed-1"
    assert comp["wk"]["overall_signal"] == "🔴"
    assert comp["llm"]["overall_signal"] == "🔴"
    assert comp["human"]["overall_signal"] == "🔴"


def test_replay_compare_human_missing_subfields_becomes_null(tmp_path):
    """Missing human subfields → null, not exception."""
    import json as json_mod
    kb_path = tmp_path / "kb.json"
    entries = [{
        "match_id": "partial",
        "features": {
            "result": "L", "opponent_quality": "lower", "venue": "away",
            "competition_stage": "regular", "opponent_name": "Unknown",
            "arsenal_goals": 1, "opponent_goals": 2, "score_margin": -1,
            "goals_conceded": 2, "yellow_cards_for": 0, "red_cards_for": 0,
            "possession_for": 60.0, "possession_against": 40.0, "possession_delta": 20.0,
            "shots_for": 20, "shots_against": 5, "shot_delta": 15,
            "shots_on_target_for": 5, "shots_on_target_against": 2, "shot_on_target_delta": 3,
            "xg_for": 2.0, "xg_against": 0.5, "xg_delta": 1.5,
            "pass_accuracy_for": 85.0, "pass_accuracy_against": 75.0, "pass_accuracy_delta": 10.0,
            "corners_for": 5, "corners_against": 2, "corner_delta": 3,
            "fouls_for": 10, "fouls_against": 10,
            "substitution_windows": [], "arsenal_sub_count": 0,
            "goals_after_arsenal_subs": 0, "goals_by_substitutes": 0,
            "score_state_timeline": [], "set_piece_goals_for": 0, "set_piece_goals_against": 0,
            "predicted_plan_match_features": {}, "missing_data": [],
        },
        "weak_labels": {"overall_signal": "🟡", "model_signals": {}, "dimension_signals": {}},
        "evaluation": {"overall_signal": "🔴", "model_signals": {}, "dimension_signals": {}},
        "human_override": {"reviewer": "shuo"},  # missing corrected fields
    }]
    with open(kb_path, "w") as f:
        json_mod.dump(entries, f)

    from scripts.replay_history import replay_compare_human
    report = replay_compare_human(str(kb_path))
    comp = report["human_comparisons"][0]
    assert comp["human"]["overall_signal"] is None


def test_replay_does_not_mutate_kb(tmp_path):
    """Replay must never write to KB."""
    import json as json_mod
    kb_path = tmp_path / "kb.json"
    entries = [{
        "match_id": "immutable",
        "features": {
            "result": "L", "opponent_quality": "lower", "venue": "away",
            "competition_stage": "regular", "opponent_name": "Test",
            "arsenal_goals": 0, "opponent_goals": 1, "score_margin": -1,
            "goals_conceded": 1, "yellow_cards_for": 0, "red_cards_for": 0,
            "possession_for": 55.0, "possession_against": 45.0, "possession_delta": 10.0,
            "shots_for": 10, "shots_against": 5, "shot_delta": 5,
            "shots_on_target_for": 3, "shots_on_target_against": 1, "shot_on_target_delta": 2,
            "xg_for": 1.0, "xg_against": 0.5, "xg_delta": 0.5,
            "pass_accuracy_for": 83.0, "pass_accuracy_against": 78.0, "pass_accuracy_delta": 5.0,
            "corners_for": 4, "corners_against": 3, "corner_delta": 1,
            "fouls_for": 10, "fouls_against": 10,
            "substitution_windows": [], "arsenal_sub_count": 0,
            "goals_after_arsenal_subs": 0, "goals_by_substitutes": 0,
            "score_state_timeline": [], "set_piece_goals_for": 0, "set_piece_goals_against": 0,
            "predicted_plan_match_features": {}, "missing_data": [],
        },
        "weak_labels": {"overall_signal": "🟡"},
        "human_override": {"reviewer": "shuo", "corrected_overall_signal": "🔴"},
    }]
    before = json_mod.dumps(entries)
    with open(kb_path, "w") as f:
        json_mod.dump(entries, f)

    from scripts.replay_history import replay_compare_human
    replay_compare_human(str(kb_path))

    with open(kb_path) as f:
        after = f.read()
    assert before == after, "KB was mutated by replay"
