"""Unit tests for predicate mining enhancement (Phases 1-5).

Tests:
1. diagnostics covers all rejected candidates
2. feature search space derives from existing features only
3. missing input → derived boolean is false
4. predicate enumeration never generates empty predicate
5. predicate size <= 4
6. result=W alone cannot enter candidates
7. precision uses support / matched_total
8. wk_too_generous uses higher gate
9. exploratory candidate doesn't trigger implementation spec
10. replay empty candidates → before == after
11. replay writes passes
12. summary outputs correct decisions
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.self_iterate import (
    _derive_feature_view,
    run_diagnose_predicate_mining,
    run_build_predicate_search_space,
    run_mine_enhanced_wk_predicates,
    run_replay_wk_candidates,
    run_summarize_predicate_mining,
)


# ── Helpers ────────────────────────────────────────────────────────

def _make_entry(match_id: str, result: str = "W", opponent: str = "Chelsea", **kwargs) -> dict:
    return {
        "match_id": match_id,
        "features": {
            "result": result,
            "score_margin": kwargs.get("score_margin", 1),
            "opponent_name": opponent,
            "opponent_quality": kwargs.get("opponent_quality", "mid_table"),
            "venue": kwargs.get("venue", "home"),
            "competition_stage": kwargs.get("competition_stage", "league"),
            "goals_conceded": kwargs.get("goals_conceded", 0),
            "xg_delta": kwargs.get("xg_delta", 0.5),
            "xg_against": kwargs.get("xg_against", 0.8),
            "opponent_shots_on_target": kwargs.get("opponent_shots_on_target", 3),
            "possession_delta": kwargs.get("possession_delta", 5),
            "corner_delta": kwargs.get("corner_delta", 2),
            "shot_delta": kwargs.get("shot_delta", 5),
            "shot_on_target_delta": kwargs.get("shot_on_target_delta", 2),
            "set_piece_goals_for": kwargs.get("set_piece_goals_for", 0),
            "set_piece_goals_against": kwargs.get("set_piece_goals_against", 0),
            "substitution_windows": kwargs.get("substitution_windows", []),
            "goals_after_arsenal_subs": kwargs.get("goals_after_arsenal_subs", 0),
        },
        "evaluation": {"source": "llm"},
    }


def _make_adj_row(match_id: str, status: str = "agreement_high_confidence", **kwargs) -> dict:
    default_dims = {"execution": "🟢", "adjustment": "🟢", "satisfaction": "🟢"}
    default_models = {str(i): "🟡" for i in range(1, 7)}
    default_models["1"] = "🟢"
    return {
        "match_id": match_id,
        "status": status,
        "differences": kwargs.get("differences", []),
        "wk": {
            "overall_signal": kwargs.get("wk_overall", "🟢"),
            "dimension_signals": kwargs.get("wk_dims", dict(default_dims)),
            "model_signals": kwargs.get("wk_models", dict(default_models)),
        },
        "b": {
            "overall_signal": kwargs.get("b_overall", "🟢"),
            "dimension_signals": kwargs.get("b_dims", dict(default_dims)),
            "model_signals": kwargs.get("b_models", dict(default_models)),
        },
    }


def _write_json(path: Path, data) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return str(path)


# ── Test 1: diagnostics covers all rejected ───────────────────────

class TestDiagnostics:
    def test_covers_all_rejected(self, tmp_path):
        rejected = [
            {"id": "c1", "support": 1, "precision_vs_b": 0.5, "false_positive_count": 2,
             "target": "overall_signal", "direction": "upgrade",
             "rejection_reason": "gate: support=1<5 or precision=0.50<0.80 or fp=2>1"},
            {"id": "c2", "support": 8, "precision_vs_b": 0.14, "false_positive_count": 48,
             "target": "dimension_signals.execution", "direction": "downgrade",
             "rejection_reason": "empty predicate: no deterministic feature predicate found"},
        ]
        rej_path = _write_json(tmp_path / "rej.json", rejected)
        kb_path = _write_json(tmp_path / "kb.json", [])
        adj_path = _write_json(tmp_path / "adj.json", {"rows": []})
        out_path = str(tmp_path / "diag.json")

        result = run_diagnose_predicate_mining(kb_path, adj_path, rej_path, out_path)
        assert result["summary"]["total_rejected"] == 2


# ── Test 2: feature search space from existing features ───────────

class TestSearchSpace:
    def test_derives_from_existing_features(self, tmp_path):
        entries = [_make_entry("100", xg_delta=1.2, score_margin=2)]
        adj_path = _write_json(tmp_path / "adj.json", {
            "rows": [_make_adj_row("100")]
        })
        kb_path = _write_json(tmp_path / "kb.json", entries)
        out_path = str(tmp_path / "ss.json")

        result = run_build_predicate_search_space(kb_path, adj_path, out_path)
        ss = json.loads(Path(out_path).read_text())
        row = ss["rows"][0]
        assert row["features"]["big_win"] is True
        assert row["features"]["strong_xg_edge"] is True


# ── Test 3: missing input → derived boolean false ─────────────────

class TestDerivedFeatureDefaults:
    def test_missing_xg_delta_makes_xg_features_false(self, tmp_path):
        entry = _make_entry("200")
        entry["features"]["xg_delta"] = None
        entry["features"]["shot_delta"] = None
        fv = _derive_feature_view(entry)
        assert fv["strong_xg_edge"] is False
        assert fv["moderate_xg_edge"] is False
        assert fv["shot_volume_edge"] is False

    def test_missing_sub_windows(self, tmp_path):
        entry = _make_entry("201")
        entry["features"]["substitution_windows"] = []
        fv = _derive_feature_view(entry)
        assert fv["late_sub_window"] is False
        assert fv["early_sub_window"] is False


# ── Test 4+5: predicate enumeration ───────────────────────────────

class TestPredicateEnumeration:
    def test_no_empty_predicates(self, tmp_path):
        """Enumerated predicates must never be empty."""
        entries = [_make_entry(str(i), result="W") for i in range(10)]
        rows = [_make_adj_row(str(i), status="wk_too_harsh", differences=["overall"],
                               wk_overall="🟡", b_overall="🟢") for i in range(10)]
        # Build search space manually
        ss_rows = [{"match_id": str(i), "features": {"result": "W"}, "missing_features": []} for i in range(10)]
        ss_path = _write_json(tmp_path / "ss.json", {"rows": ss_rows, "feature_definitions": {}})
        diag_path = _write_json(tmp_path / "diag.json", {"total_rejected": 0, "failure_breakdown": {}})
        adj_path = _write_json(tmp_path / "adj.json", {"rows": rows})
        base_path = _write_json(tmp_path / "base.json", {"rows": rows})
        kb_path = _write_json(tmp_path / "kb.json", entries)
        out_path = str(tmp_path / "cand.json")

        run_mine_enhanced_wk_predicates(kb_path, adj_path, base_path, ss_path, diag_path, out_path)
        data = json.loads(Path(out_path).read_text())
        for c in data.get("candidates", []) + data.get("exploratory_candidates", []) + data.get("rejected_candidates", []):
            assert len(c.get("predicate", {})) > 0, f"Empty predicate in {c.get('id')}"

    def test_predicate_size_max_4(self, tmp_path):
        """Predicate size must be <= 4."""
        entries = [_make_entry(str(i), result="W") for i in range(10)]
        rows = [_make_adj_row(str(i), status="wk_too_harsh", differences=["overall"],
                               wk_overall="🟡", b_overall="🟢") for i in range(10)]
        ss_rows = [{"match_id": str(i), "features": {"result": "W", "big_win": True}, "missing_features": []} for i in range(10)]
        ss_path = _write_json(tmp_path / "ss.json", {"rows": ss_rows, "feature_definitions": {}})
        diag_path = _write_json(tmp_path / "diag.json", {"total_rejected": 0, "failure_breakdown": {}})
        adj_path = _write_json(tmp_path / "adj.json", {"rows": rows})
        base_path = _write_json(tmp_path / "base.json", {"rows": rows})
        kb_path = _write_json(tmp_path / "kb.json", entries)
        out_path = str(tmp_path / "cand.json")

        run_mine_enhanced_wk_predicates(kb_path, adj_path, base_path, ss_path, diag_path, out_path)
        data = json.loads(Path(out_path).read_text())
        for c in data.get("candidates", []) + data.get("exploratory_candidates", []) + data.get("rejected_candidates", []):
            assert len(c.get("predicate", {})) <= 4, f"Predicate too large: {c.get('id')}"


# ── Test 6: result=W alone cannot enter candidates ────────────────

class TestResultAloneRejected:
    def test_result_w_alone_not_candidate(self, tmp_path):
        """result=W as sole predicate is too broad — should not be a candidate."""
        entries = [_make_entry(str(i), result="W") for i in range(20)]
        rows = [_make_adj_row(str(i), status="wk_too_harsh", differences=["overall"],
                               wk_overall="🟡", b_overall="🟢") for i in range(20)]
        ss_rows = [{"match_id": str(i), "features": {"result": "W"}, "missing_features": []} for i in range(20)]
        ss_path = _write_json(tmp_path / "ss.json", {"rows": ss_rows, "feature_definitions": {}})
        diag_path = _write_json(tmp_path / "diag.json", {"total_rejected": 0, "failure_breakdown": {}})
        adj_path = _write_json(tmp_path / "adj.json", {"rows": rows})
        base_path = _write_json(tmp_path / "base.json", {"rows": rows})
        kb_path = _write_json(tmp_path / "kb.json", entries)
        out_path = str(tmp_path / "cand.json")

        run_mine_enhanced_wk_predicates(kb_path, adj_path, base_path, ss_path, diag_path, out_path)
        data = json.loads(Path(out_path).read_text())
        # result=W alone matches ALL entries → precision = support/matched_total would be low
        # If it somehow passes, it should at least not be implementation_eligible
        for c in data.get("candidates", []):
            if list(c["predicate"].keys()) == ["result"]:
                assert False, "result=W alone should not be implementation_eligible"


# ── Test 7: precision = support / matched_total ───────────────────

class TestPrecisionCalculation:
    def test_precision_uses_matched_total(self, tmp_path):
        """Precision must be support / matched_total, not just support / group_size."""
        entries = [_make_entry(str(i), result="W") for i in range(10)]
        # 5 disagree, 5 agree — if predicate matches all 10, precision = 5/10 = 0.5
        rows = [_make_adj_row(str(i), status="wk_too_harsh", differences=["overall"],
                               wk_overall="🟡", b_overall="🟢") for i in range(5)]
        rows += [_make_adj_row(str(i), status="agreement_high_confidence") for i in range(5, 10)]
        ss_rows = [{"match_id": str(i), "features": {"result": "W"}, "missing_features": []} for i in range(10)]
        ss_path = _write_json(tmp_path / "ss.json", {"rows": ss_rows, "feature_definitions": {}})
        diag_path = _write_json(tmp_path / "diag.json", {"total_rejected": 0, "failure_breakdown": {}})
        adj_path = _write_json(tmp_path / "adj.json", {"rows": rows})
        base_path = _write_json(tmp_path / "base.json", {"rows": rows})
        kb_path = _write_json(tmp_path / "kb.json", entries)
        out_path = str(tmp_path / "cand.json")

        run_mine_enhanced_wk_predicates(kb_path, adj_path, base_path, ss_path, diag_path, out_path)
        data = json.loads(Path(out_path).read_text())
        for c in data.get("rejected_candidates", []):
            if c.get("predicate") == {"result": "W"}:
                assert c["precision_vs_b"] == 0.5, f"Expected precision=0.5 for result=W, got {c['precision_vs_b']}"


# ── Test 8: generous higher gate ──────────────────────────────────

class TestGenerousGate:
    def test_generous_requires_higher_thresholds(self, tmp_path):
        """wk_too_generous candidates need support>=5, precision>=0.90, fp==0."""
        entries = [_make_entry(str(i)) for i in range(10)]
        rows = [_make_adj_row(str(i), status="wk_too_generous", differences=["overall"],
                               wk_overall="🟢", b_overall="🟡") for i in range(4)]
        rows += [_make_adj_row(str(i), status="agreement_high_confidence") for i in range(4, 10)]
        ss_rows = [{"match_id": str(i), "features": {"result": "W", "clean_sheet": True}, "missing_features": []} for i in range(10)]
        ss_path = _write_json(tmp_path / "ss.json", {"rows": ss_rows, "feature_definitions": {}})
        diag_path = _write_json(tmp_path / "diag.json", {"total_rejected": 0, "failure_breakdown": {}})
        adj_path = _write_json(tmp_path / "adj.json", {"rows": rows})
        base_path = _write_json(tmp_path / "base.json", {"rows": rows})
        kb_path = _write_json(tmp_path / "kb.json", entries)
        out_path = str(tmp_path / "cand.json")

        run_mine_enhanced_wk_predicates(kb_path, adj_path, base_path, ss_path, diag_path, out_path)
        data = json.loads(Path(out_path).read_text())
        # support=4 < 5 → cannot be implementation_eligible
        assert len(data.get("candidates", [])) == 0


# ── Test 9: exploratory doesn't trigger spec ──────────────────────

class TestExploratoryNoSpec:
    def test_exploratory_only_no_implementation_spec(self, tmp_path):
        """Summary with only exploratory candidates → no proceed_to_wk_v1_2_spec."""
        diag = _write_json(tmp_path / "diag.json", {"total_rejected": 5, "failure_breakdown": {"precision_too_low": 3}})
        cand = _write_json(tmp_path / "cand.json", {
            "candidates": [],
            "exploratory_candidates": [{"id": "exp1", "support": 3, "precision_vs_b": 0.85}],
        })
        replay = _write_json(tmp_path / "replay.json", {"passes": False})
        out_path = str(tmp_path / "summary.json")

        result = run_summarize_predicate_mining(diag, cand, replay, out_path)
        assert result["summary"]["decision"] != "proceed_to_wk_v1_2_spec"


# ── Test 10+11: replay empty → before==after + passes ─────────────

class TestReplayEmpty:
    def test_before_equals_after(self, tmp_path):
        entries = [_make_entry("100")]
        rows = [_make_adj_row("100")]
        adj_path = _write_json(tmp_path / "adj.json", {"rows": rows})
        cand_path = _write_json(tmp_path / "cand.json", {"candidates": [], "exploratory_candidates": []})
        kb_path = _write_json(tmp_path / "kb.json", entries)
        out_path = str(tmp_path / "replay.json")

        result = run_replay_wk_candidates(kb_path, adj_path, cand_path, out_path)
        assert result["summary"]["before"] == result["summary"]["after"]

    def test_passes_in_artifact(self, tmp_path):
        entries = [_make_entry("100")]
        rows = [_make_adj_row("100")]
        adj_path = _write_json(tmp_path / "adj.json", {"rows": rows})
        cand_path = _write_json(tmp_path / "cand.json", {"candidates": []})
        kb_path = _write_json(tmp_path / "kb.json", entries)
        out_path = str(tmp_path / "replay.json")

        run_replay_wk_candidates(kb_path, adj_path, cand_path, out_path)
        artifact = json.loads(Path(out_path).read_text())
        assert "passes" in artifact


# ── Test 12: summary decisions ────────────────────────────────────

class TestSummaryDecisions:
    def test_collect_more_features_when_low_precision(self, tmp_path):
        diag = _write_json(tmp_path / "diag.json", {"total_rejected": 10, "failure_breakdown": {"precision_too_low": 8}})
        cand = _write_json(tmp_path / "cand.json", {"candidates": [], "exploratory_candidates": []})
        replay = _write_json(tmp_path / "replay.json", {"passes": False})
        out_path = str(tmp_path / "summary.json")

        result = run_summarize_predicate_mining(diag, cand, replay, out_path)
        assert result["summary"]["decision"] == "collect_more_features"
        assert len(result["summary"]["feature_gaps"]) > 0

    def test_proceed_when_candidates_pass_replay(self, tmp_path):
        diag = _write_json(tmp_path / "diag.json", {"total_rejected": 0, "failure_breakdown": {}})
        cand = _write_json(tmp_path / "cand.json", {"candidates": [{"id": "c1"}], "exploratory_candidates": []})
        replay = _write_json(tmp_path / "replay.json", {"passes": True})
        out_path = str(tmp_path / "summary.json")

        result = run_summarize_predicate_mining(diag, cand, replay, out_path)
        assert result["summary"]["decision"] == "proceed_to_wk_v1_2_spec"

    def test_no_action_when_exploratory_only(self, tmp_path):
        diag = _write_json(tmp_path / "diag.json", {"total_rejected": 5, "failure_breakdown": {}})
        cand = _write_json(tmp_path / "cand.json", {"candidates": [], "exploratory_candidates": [{"id": "e1"}]})
        replay = _write_json(tmp_path / "replay.json", {"passes": False})
        out_path = str(tmp_path / "summary.json")

        result = run_summarize_predicate_mining(diag, cand, replay, out_path)
        assert result["summary"]["decision"] == "no_action"
