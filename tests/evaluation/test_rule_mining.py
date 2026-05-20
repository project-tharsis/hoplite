"""Tests for rule_mining: deterministic candidate rule extraction from WK-vs-B disagreements."""
import json
import tempfile
import os

from src.evaluation.rule_mining import (
    build_feature_view,
    run_rule_mining,
)


# ── helpers ────────────────────────────────────────────────────────────

def _make_adjudication_report(rows: list[dict]) -> dict:
    return {
        "run_id": "test",
        "summary": {"total_entries": len(rows), "feature_backed": len(rows), "compared": len(rows)},
        "status_counts": {},
        "context_breakdowns": [],
        "rows": rows,
    }


def _make_row(
    match_id: str = "100",
    status: str = "wk_too_harsh",
    result: str = "W",
    opponent_quality: str = "top6",
    venue: str = "home",
    competition_stage: str = "league_early",
    features: dict | None = None,
    wk: dict | None = None,
    b: dict | None = None,
) -> dict:
    return {
        "match_id": match_id,
        "context": {
            "opponent_quality": opponent_quality,
            "venue": venue,
            "competition_stage": competition_stage,
            "result": result,
            "xg_present": features is not None and features.get("xg_for") is not None and features.get("xg_against") is not None,
        },
        "status": status,
        "wk": wk or {"overall_signal": "🟡", "model_signals": {"1": "🟡"}},
        "b": b or {"overall_signal": "🟢", "model_signals": {"1": "🟢"}},
        "differences": ["overall_signal"],
        "features": features or {},
    }


def _make_features(
    xg_delta=None, shot_delta=None, possession_delta=None, corner_delta=None,
    goals_conceded=0, yellow_cards_for=0, red_cards_for=0,
    goals_after_arsenal_subs=0, goals_by_substitutes=0,
    set_piece_goals_for=0, set_piece_goals_against=0,
    substitution_windows=None, arsenal_sub_count=0,
    xg_for=None, xg_against=None,
    missing_data=None,
    # extra raw fields
    **kwargs,
) -> dict:
    f = {
        "xg_for": xg_for, "xg_against": xg_against, "xg_delta": xg_delta,
        "shot_delta": shot_delta, "possession_delta": possession_delta,
        "corner_delta": corner_delta,
        "goals_conceded": goals_conceded,
        "yellow_cards_for": yellow_cards_for, "red_cards_for": red_cards_for,
        "goals_after_arsenal_subs": goals_after_arsenal_subs,
        "goals_by_substitutes": goals_by_substitutes,
        "set_piece_goals_for": set_piece_goals_for,
        "set_piece_goals_against": set_piece_goals_against,
        "substitution_windows": substitution_windows or [],
        "arsenal_sub_count": arsenal_sub_count,
        "missing_data": missing_data or [],
    }
    f.update(kwargs)
    return f


# ── Feature view derivation tests ─────────────────────────────────────

class TestFeatureViewDerivation:
    def test_dominant_control(self):
        """dominant_control is true when ≥2 of xg/shot/possession/corner thresholds met."""
        features = _make_features(
            xg_delta=0.8, shot_delta=6, possession_delta=5, corner_delta=2,
            xg_for=1.5, xg_against=0.7,
        )
        row = _make_row(features=features)
        fv = build_feature_view(row)
        assert fv["dominant_control"] is True

    def test_dominant_control_one_threshold(self):
        """dominant_control is false when only 1 threshold met."""
        features = _make_features(
            xg_delta=0.8, shot_delta=1, possession_delta=2, corner_delta=1,
            xg_for=1.5, xg_against=0.7,
        )
        row = _make_row(features=features)
        fv = build_feature_view(row)
        assert fv["dominant_control"] is False

    def test_poor_control(self):
        """poor_control is true when ≥2 of xg/shot/possession/corner negative thresholds met."""
        features = _make_features(
            xg_delta=-0.6, shot_delta=-5, possession_delta=2, corner_delta=1,
            xg_for=0.3, xg_against=0.9,
        )
        row = _make_row(features=features)
        fv = build_feature_view(row)
        assert fv["poor_control"] is True

    def test_poor_control_one_threshold(self):
        """poor_control is false when only 1 negative threshold met."""
        features = _make_features(
            xg_delta=-0.6, shot_delta=-1, possession_delta=2, corner_delta=1,
            xg_for=0.3, xg_against=0.9,
        )
        row = _make_row(features=features)
        fv = build_feature_view(row)
        assert fv["poor_control"] is False

    def test_clean_sheet(self):
        features = _make_features(goals_conceded=0)
        fv = build_feature_view(_make_row(features=features))
        assert fv["clean_sheet"] is True

    def test_not_clean_sheet(self):
        features = _make_features(goals_conceded=2)
        fv = build_feature_view(_make_row(features=features))
        assert fv["clean_sheet"] is False

    def test_cards_pressure(self):
        features = _make_features(yellow_cards_for=3)
        fv = build_feature_view(_make_row(features=features))
        assert fv["cards_pressure"] is True

    def test_late_subs(self):
        features = _make_features(
            substitution_windows=[{"minute": 78, "player": "X"}],
        )
        fv = build_feature_view(_make_row(features=features))
        assert fv["late_subs"] is True

    def test_sub_impact(self):
        features = _make_features(goals_by_substitutes=1)
        fv = build_feature_view(_make_row(features=features))
        assert fv["sub_impact"] is True

    def test_set_piece_edge(self):
        features = _make_features(set_piece_goals_for=2, set_piece_goals_against=0)
        fv = build_feature_view(_make_row(features=features))
        assert fv["set_piece_edge"] is True

    def test_set_piece_edge_corner_delta(self):
        features = _make_features(set_piece_goals_for=0, set_piece_goals_against=0, corner_delta=5)
        fv = build_feature_view(_make_row(features=features))
        assert fv["set_piece_edge"] is True

    def test_xg_present(self):
        features = _make_features(xg_for=1.5, xg_against=0.7)
        fv = build_feature_view(_make_row(features=features))
        assert fv["xg_present"] is True

    def test_xg_not_present_when_missing(self):
        features = _make_features(xg_for=None, xg_against=None)
        fv = build_feature_view(_make_row(features=features))
        assert fv["xg_present"] is False


# ── Missing fields tests ──────────────────────────────────────────────

class TestMissingFields:
    def test_missing_fields_dont_make_booleans_true(self):
        """When required fields are missing/None, derived booleans should be False."""
        features = _make_features(
            xg_delta=None, shot_delta=None, possession_delta=None, corner_delta=None,
        )
        fv = build_feature_view(_make_row(features=features))
        assert fv["dominant_xg"] is False
        assert fv["dominant_shots"] is False
        assert fv["dominant_control"] is False
        assert fv["poor_control"] is False

    def test_empty_features_produces_all_false(self):
        """Empty features dict should produce all-False derived booleans."""
        fv = build_feature_view(_make_row(features={}))
        assert fv["dominant_xg"] is False
        assert fv["dominant_shots"] is False
        assert fv["dominant_control"] is False
        assert fv["poor_control"] is False
        assert fv["clean_sheet"] is False  # goals_conceded defaults to 0 in extractor but empty dict means missing
        assert fv["cards_pressure"] is False
        assert fv["late_subs"] is False
        assert fv["sub_impact"] is False

    def test_missing_features_tracked(self):
        """Feature view includes missing_features listing which fields were absent."""
        features = _make_features(
            xg_delta=None, shot_delta=None, possession_delta=None, corner_delta=None,
        )
        fv = build_feature_view(_make_row(features=features))
        assert "missing_features" in fv
        assert isinstance(fv["missing_features"], list)
        # Delta fields should be listed as missing
        for field_name in ["xg_delta", "shot_delta", "possession_delta", "corner_delta"]:
            assert field_name in fv["missing_features"], f"{field_name} should be in missing_features"

    def test_present_fields_not_in_missing(self):
        """Fields that are present should not appear in missing_features."""
        features = _make_features(xg_delta=0.8, xg_for=1.5, xg_against=0.7)
        fv = build_feature_view(_make_row(features=features))
        assert "xg_delta" not in fv["missing_features"]

    def test_goals_conceded_zero_is_present(self):
        """goals_conceded=0 should NOT be treated as missing."""
        features = _make_features(goals_conceded=0)
        fv = build_feature_view(_make_row(features=features))
        assert "goals_conceded" not in fv["missing_features"]
        assert fv["goals_conceded"] == 0


# ── Candidate generation tests ───────────────────────────────────────

class TestCandidateGeneration:
    def test_repeated_wk_too_harsh_produces_upgrade_candidate(self):
        """Repeated wk_too_harrows with similar features → upgrade candidate."""
        features = _make_features(
            xg_delta=0.9, shot_delta=6, possession_delta=10, corner_delta=5,
            xg_for=1.5, xg_against=0.6,
        )
        # Need ≥2 different opponents for diversity threshold
        opponent_qualities = ["top6", "european_elite", "top6", "european_elite"]
        rows = [
            _make_row(match_id=str(i), status="wk_too_harsh", features=features, opponent_quality=opponent_qualities[i])
            for i in range(4)
        ]
        report = _make_adjudication_report(rows)

        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            json.dump(report, f)
            f.flush()
            report_path = f.name

        output_path = report_path.replace(".json", "_out.json")
        result = run_rule_mining(report_path, output_path)

        assert len(result["candidates"]) > 0
        candidate = result["candidates"][0]
        assert candidate["direction"] == "upgrade"
        assert candidate["support"] >= 3
        assert candidate["proposed_action"] == "prompt_blind_spot"

        os.unlink(report_path)
        os.unlink(output_path)

    def test_single_disagreement_is_rejected(self):
        """A single disagreement should not produce a promoted candidate."""
        features = _make_features(
            xg_delta=0.9, shot_delta=6, possession_delta=10, corner_delta=5,
            xg_for=1.5, xg_against=0.6,
        )
        rows = [_make_row(match_id="1", status="wk_too_harsh", features=features)]
        report = _make_adjudication_report(rows)

        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            json.dump(report, f)
            f.flush()
            report_path = f.name

        output_path = report_path.replace(".json", "_out.json")
        result = run_rule_mining(report_path, output_path)

        assert len(result["candidates"]) == 0
        assert len(result["rejected_candidates"]) > 0
        rejected = result["rejected_candidates"][0]
        assert "support" in rejected.get("rejection_reason", "").lower() or \
               "support" in str(rejected.get("rejection_reasons", [])).lower()

        os.unlink(report_path)
        os.unlink(output_path)

    def test_precision_below_threshold_is_rejected(self):
        """Candidate with precision < 0.70 should be rejected for prompt_blind_spot."""
        # Create conflicting rows: 3 wk_too_harsh + 2 wk_too_generous with same features
        # This should yield precision ~= 0.6 (3/5), below 0.70
        features = _make_features(
            xg_delta=0.9, shot_delta=6, possession_delta=10, corner_delta=5,
            xg_for=1.5, xg_against=0.6,
        )
        rows_harsh = [
            _make_row(match_id=f"h{i}", status="wk_too_harsh", features=features, opponent_quality="top6")
            for i in range(3)
        ]
        rows_generous = [
            _make_row(match_id=f"g{i}", status="wk_too_generous", features=features, opponent_quality="top6")
            for i in range(2)
        ]
        report = _make_adjudication_report(rows_harsh + rows_generous)

        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            json.dump(report, f)
            f.flush()
            report_path = f.name

        output_path = report_path.replace(".json", "_out.json")
        result = run_rule_mining(report_path, output_path)

        # Should have rejected candidates
        assert len(result["rejected_candidates"]) > 0
        reasons_str = json.dumps(result["rejected_candidates"])
        assert "precision" in reasons_str.lower() or "conflict" in reasons_str.lower()

        os.unlink(report_path)
        os.unlink(output_path)

    def test_wk_patch_proposal_threshold_higher(self):
        """wk_patch_proposal has stricter thresholds than prompt_blind_spot."""
        # Build 5+ rows with human_override to qualify for wk_patch_proposal
        features = _make_features(
            xg_delta=0.9, shot_delta=6, possession_delta=10, corner_delta=5,
            xg_for=1.5, xg_against=0.6,
        )
        # With only 5 support and no human_override, should get prompt_blind_spot, not wk_patch
        rows = [
            _make_row(match_id=str(i), status="wk_too_harsh", features=features, opponent_quality="top6")
            for i in range(6)
        ]
        report = _make_adjudication_report(rows)

        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            json.dump(report, f)
            f.flush()
            report_path = f.name

        output_path = report_path.replace(".json", "_out.json")
        result = run_rule_mining(report_path, output_path)

        # Should get prompt_blind_spot but NOT wk_patch_proposal (no human_override)
        if result["candidates"]:
            for c in result["candidates"]:
                assert c["proposed_action"] != "wk_patch_proposal", \
                    "wk_patch_proposal requires human_override which is not present"

        os.unlink(report_path)
        os.unlink(output_path)

    def test_feature_view_context_fields(self):
        """Feature view includes result, opponent_quality, venue, competition_stage."""
        row = _make_row(result="W", opponent_quality="top6", venue="home", competition_stage="league_early")
        fv = build_feature_view(row)
        assert fv["result"] == "W"
        assert fv["opponent_quality"] == "top6"
        assert fv["venue"] == "home"
        assert fv["competition_stage"] == "league_early"

    def test_output_format(self):
        """Output has version, candidates, rejected_candidates keys."""
        features = _make_features(xg_delta=0.9, xg_for=1.5, xg_against=0.6)
        rows = [_make_row(match_id="1", status="wk_too_harsh", features=features)]
        report = _make_adjudication_report(rows)

        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            json.dump(report, f)
            f.flush()
            report_path = f.name

        output_path = report_path.replace(".json", "_out.json")
        result = run_rule_mining(report_path, output_path)

        assert result["version"] == "v1"
        assert "candidates" in result
        assert "rejected_candidates" in result

        # Check written output
        with open(output_path) as f:
            written = json.load(f)
        assert written["version"] == "v1"
        assert "candidates" in written
        assert "rejected_candidates" in written

        os.unlink(report_path)
        os.unlink(output_path)

    def test_non_disagreement_rows_ignored(self):
        """Rows with status other than wk_too_harsh/wk_too_generous are ignored."""
        features = _make_features(xg_delta=0.9, xg_for=1.5, xg_against=0.6)
        rows = [
            _make_row(match_id="1", status="agreement_high_confidence", features=features),
            _make_row(match_id="2", status="agreement_low_confidence", features=features),
            _make_row(match_id="3", status="model_level_disagreement", features=features),
        ]
        report = _make_adjudication_report(rows)

        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            json.dump(report, f)
            f.flush()
            report_path = f.name

        output_path = report_path.replace(".json", "_out.json")
        result = run_rule_mining(report_path, output_path)

        assert len(result["candidates"]) == 0
        assert len(result["rejected_candidates"]) == 0

        os.unlink(report_path)
        os.unlink(output_path)
