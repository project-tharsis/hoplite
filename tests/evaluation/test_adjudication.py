"""Tests for WK vs Evaluator B adjudication module."""

import pytest

from src.evaluation.adjudication import Adjudicator


# ── Fixtures ──────────────────────────────────────────────────────────────

def _make_entry(
    match_id: str = "9999999",
    features: dict | None = None,
    weak_labels: dict | None = None,
    evaluation: dict | None = None,
) -> dict:
    """Build a minimal KB entry."""
    if features is None:
        features = {
            "result": "W",
            "score_margin": 2,
            "opponent_quality": "mid_table",
            "venue": "home",
            "competition_stage": "league_early",
            "xg_for": 1.5,
            "xg_against": 0.5,
        }
    entry: dict = {"match_id": match_id, "features": features}
    if weak_labels is not None:
        entry["weak_labels"] = weak_labels
    if evaluation is not None:
        entry["evaluation"] = evaluation
    return entry


def _wk_signals(overall="🟢", dims=None, models=None) -> dict:
    """Build a weak_labels dict with semantic model keys."""
    if dims is None:
        dims = {"execution": "🟢", "adjustment": "🟢", "satisfaction": "🟢"}
    if models is None:
        models = {
            "culture_as_os": "🟢",
            "where_game_is_played": "🟢",
            "defence_as_attacking_identity": "🟢",
            "marginal_gains": "🟢",
            "add_capability_keep_identity": "🟢",
            "role_clarity": "🟢",
        }
    return {
        "overall_signal": overall,
        "dimension_signals": dims,
        "model_signals": models,
        "weak_label_version": "v1.1",
    }


def _b_eval(
    overall="🟢",
    dims=None,
    models=None,
    confidence=None,
    missing_or_weak_evidence=None,
    weak_label_disagreements=None,
) -> dict:
    """Build an Evaluator B evaluation dict with numeric model keys."""
    if dims is None:
        dims = {"execution": "🟢", "adjustment": "🟢", "satisfaction": "🟢"}
    if models is None:
        models = {
            "1": "🟢", "2": "🟢", "3": "🟢",
            "4": "🟢", "5": "🟢", "6": "🟢",
        }
    if confidence is None:
        confidence = {
            "1": "high", "2": "high", "3": "high",
            "4": "high", "5": "high", "6": "high",
        }
    if missing_or_weak_evidence is None:
        missing_or_weak_evidence = []
    if weak_label_disagreements is None:
        weak_label_disagreements = []
    return {
        "source": "llm",
        "overall_signal": overall,
        "dimension_signals": dims,
        "model_signals": models,
        "confidence": confidence,
        "missing_or_weak_evidence": missing_or_weak_evidence,
        "weak_label_disagreements": weak_label_disagreements,
        "narrative": "test narrative",
    }


# ── Model key normalization ──────────────────────────────────────────────


class TestModelKeyNormalization:
    def test_semantic_keys_normalized_to_numeric(self):
        """WK semantic model keys must be normalized to numeric keys."""
        entry = _make_entry(
            weak_labels=_wk_signals(
                models={
                    "culture_as_os": "🟡",
                    "where_game_is_played": "🟢",
                    "defence_as_attacking_identity": "🟢",
                    "marginal_gains": "🟢",
                    "add_capability_keep_identity": "🟢",
                    "role_clarity": "🟢",
                }
            ),
            evaluation=_b_eval(
                models={
                    "1": "🟡", "2": "🟢", "3": "🟢",
                    "4": "🟢", "5": "🟢", "6": "🟢",
                }
            ),
        )
        adj = Adjudicator(entries=[entry])
        report = adj.run()
        row = report["rows"][0]
        # WK model_signals in output must use numeric keys
        assert "1" in row["wk"]["model_signals"]
        assert "culture_as_os" not in row["wk"]["model_signals"]
        assert row["wk"]["model_signals"]["1"] == "🟡"

    def test_all_semantic_keys_present(self):
        """All 6 semantic keys must be mapped."""
        mapping = {
            "culture_as_os": "1",
            "where_game_is_played": "2",
            "defence_as_attacking_identity": "3",
            "marginal_gains": "4",
            "add_capability_keep_identity": "5",
            "role_clarity": "6",
        }
        entry = _make_entry(
            weak_labels=_wk_signals(
                models={k: "🟢" for k in mapping}
            ),
            evaluation=_b_eval(),
        )
        adj = Adjudicator(entries=[entry])
        report = adj.run()
        row = report["rows"][0]
        for num_key in mapping.values():
            assert num_key in row["wk"]["model_signals"], f"Missing numeric key {num_key}"


# ── Status classification ────────────────────────────────────────────────


class TestStatusClassification:
    def test_wk_too_harsh(self):
        """WK 🟡 overall vs B 🟢 overall → wk_too_harsh."""
        entry = _make_entry(
            weak_labels=_wk_signals(overall="🟡"),
            evaluation=_b_eval(overall="🟢"),
        )
        adj = Adjudicator(entries=[entry])
        report = adj.run()
        assert report["rows"][0]["status"] == "wk_too_harsh"

    def test_wk_too_generous(self):
        """WK 🟢 overall vs B 🔴 overall → wk_too_generous."""
        entry = _make_entry(
            weak_labels=_wk_signals(overall="🟢"),
            evaluation=_b_eval(
                overall="🔴",
                dims={"execution": "🔴", "adjustment": "🔴", "satisfaction": "🔴"},
                models={str(i): "🔴" for i in range(1, 7)},
            ),
        )
        adj = Adjudicator(entries=[entry])
        report = adj.run()
        assert report["rows"][0]["status"] == "wk_too_generous"

    def test_model_level_disagreement(self):
        """Overall + dims match, but one model signal differs → model_level_disagreement."""
        entry = _make_entry(
            weak_labels=_wk_signals(
                overall="🟢",
                dims={"execution": "🟢", "adjustment": "🟢", "satisfaction": "🟢"},
                models={
                    "culture_as_os": "🟢",
                    "where_game_is_played": "🟢",
                    "defence_as_attacking_identity": "🟢",
                    "marginal_gains": "🟡",  # ← differs from B
                    "add_capability_keep_identity": "🟢",
                    "role_clarity": "🟢",
                },
            ),
            evaluation=_b_eval(
                overall="🟢",
                dims={"execution": "🟢", "adjustment": "🟢", "satisfaction": "🟢"},
                models={
                    "1": "🟢", "2": "🟢", "3": "🟢",
                    "4": "🟢",  # ← different from WK's 🟡
                    "5": "🟢", "6": "🟢",
                },
            ),
        )
        adj = Adjudicator(entries=[entry])
        report = adj.run()
        assert report["rows"][0]["status"] == "model_level_disagreement"

    def test_dimension_level_disagreement(self):
        """Overall matches, but a dimension differs → dimension_level_disagreement."""
        entry = _make_entry(
            weak_labels=_wk_signals(
                overall="🟢",
                dims={"execution": "🟢", "adjustment": "🟡", "satisfaction": "🟢"},
            ),
            evaluation=_b_eval(
                overall="🟢",
                dims={"execution": "🟢", "adjustment": "🟢", "satisfaction": "🟢"},
            ),
        )
        adj = Adjudicator(entries=[entry])
        report = adj.run()
        assert report["rows"][0]["status"] == "dimension_level_disagreement"

    def test_agreement_high_confidence(self):
        """All signals match, all B confidence high/medium → agreement_high_confidence."""
        entry = _make_entry(
            weak_labels=_wk_signals(overall="🟢"),
            evaluation=_b_eval(overall="🟢"),
        )
        adj = Adjudicator(entries=[entry])
        report = adj.run()
        assert report["rows"][0]["status"] == "agreement_high_confidence"

    def test_agreement_low_confidence(self):
        """Signals match but one B confidence is low → agreement_low_confidence."""
        entry = _make_entry(
            weak_labels=_wk_signals(overall="🟢"),
            evaluation=_b_eval(
                overall="🟢",
                confidence={
                    "1": "high", "2": "high", "3": "high",
                    "4": "high", "5": "high", "6": "low",  # ← low
                },
            ),
        )
        adj = Adjudicator(entries=[entry])
        report = adj.run()
        assert report["rows"][0]["status"] == "agreement_low_confidence"

    def test_missing_evaluator_b(self):
        """Feature-backed but no evaluation → missing_evaluator_b."""
        entry = _make_entry(
            weak_labels=_wk_signals(),
            evaluation=None,  # no evaluation
        )
        # Need features to be feature-backed
        adj = Adjudicator(entries=[entry])
        report = adj.run()
        assert report["rows"][0]["status"] == "missing_evaluator_b"

    def test_invalid_evaluator_b(self):
        """Evaluation exists but source != llm → invalid_evaluator_b."""
        entry = _make_entry(
            weak_labels=_wk_signals(),
            evaluation={"source": "human", "overall_signal": "🟢"},  # not llm, missing fields
        )
        adj = Adjudicator(entries=[entry])
        report = adj.run()
        assert report["rows"][0]["status"] == "invalid_evaluator_b"

    def test_needs_second_pass_low_confidence_no_disagreements(self):
        """B has low confidence, disagreements exist, but no weak_label_disagreements → needs_second_pass."""
        entry = _make_entry(
            weak_labels=_wk_signals(overall="🟡"),
            evaluation=_b_eval(
                overall="🟢",  # different from WK → disagreement
                confidence={
                    "1": "low", "2": "high", "3": "high",
                    "4": "high", "5": "high", "6": "high",
                },
                weak_label_disagreements=[],
                missing_or_weak_evidence=["pressing unavailable"],
            ),
        )
        adj = Adjudicator(entries=[entry])
        report = adj.run()
        assert report["rows"][0]["status"] == "needs_second_pass"


# ── xg_present ────────────────────────────────────────────────────────────


class TestXgPresent:
    def test_xg_present_when_both_non_none(self):
        """xg_present is True when both xg_for and xg_against are non-None."""
        entry = _make_entry(
            features={
                "result": "W",
                "opponent_quality": "mid_table",
                "venue": "home",
                "competition_stage": "league_early",
                "xg_for": 1.5,
                "xg_against": 0.5,
            },
            weak_labels=_wk_signals(),
            evaluation=_b_eval(),
        )
        adj = Adjudicator(entries=[entry])
        report = adj.run()
        assert report["rows"][0]["context"]["xg_present"] is True

    def test_xg_not_present_when_xg_for_none(self):
        """xg_present is False when xg_for is None."""
        entry = _make_entry(
            features={
                "result": "W",
                "opponent_quality": "mid_table",
                "venue": "home",
                "competition_stage": "league_early",
                "xg_for": None,
                "xg_against": 0.5,
            },
            weak_labels=_wk_signals(),
            evaluation=_b_eval(),
        )
        adj = Adjudicator(entries=[entry])
        report = adj.run()
        assert report["rows"][0]["context"]["xg_present"] is False

    def test_xg_not_present_when_both_none(self):
        """xg_present is False when both are None."""
        entry = _make_entry(
            features={
                "result": "W",
                "opponent_quality": "mid_table",
                "venue": "home",
                "competition_stage": "league_early",
                "xg_for": None,
                "xg_against": None,
            },
            weak_labels=_wk_signals(),
            evaluation=_b_eval(),
        )
        adj = Adjudicator(entries=[entry])
        report = adj.run()
        assert report["rows"][0]["context"]["xg_present"] is False


# ── Report structure ──────────────────────────────────────────────────────


class TestReportStructure:
    def test_report_has_required_keys(self):
        """Report must have run_id, summary, status_counts, context_breakdowns, rows."""
        adj = Adjudicator(entries=[], run_id="test-001")
        report = adj.run()
        assert "run_id" in report
        assert "summary" in report
        assert "status_counts" in report
        assert "context_breakdowns" in report
        assert "rows" in report
        assert report["run_id"] == "test-001"

    def test_summary_counts(self):
        """Summary counts are correct."""
        entries = [
            _make_entry(weak_labels=_wk_signals(), evaluation=_b_eval()),
            _make_entry(
                match_id="8888888",
                weak_labels=_wk_signals(),
                evaluation=None,
            ),
        ]
        adj = Adjudicator(entries=entries)
        report = adj.run()
        assert report["summary"]["total_entries"] == 2
        assert report["summary"]["feature_backed"] == 2

    def test_non_feature_backed_skipped(self):
        """Entries without features are not included in adjudication."""
        entry = {"match_id": "7777777"}  # no features
        adj = Adjudicator(entries=[entry])
        report = adj.run()
        assert report["summary"]["total_entries"] == 1
        assert report["summary"]["feature_backed"] == 0
        assert len(report["rows"]) == 0

    def test_row_has_context_and_differences(self):
        """Each row has context, differences, wk, b."""
        entry = _make_entry(
            weak_labels=_wk_signals(overall="🟡"),
            evaluation=_b_eval(overall="🟢"),
        )
        adj = Adjudicator(entries=[entry])
        report = adj.run()
        row = report["rows"][0]
        assert "context" in row
        assert "differences" in row
        assert "wk" in row
        assert "b" in row
        assert "features" in row
        assert row["match_id"] == "9999999"

    def test_agreement_rate_calculation(self):
        """Agreement rates are calculated correctly."""
        entries = [
            _make_entry(weak_labels=_wk_signals(), evaluation=_b_eval()),  # agree
            _make_entry(
                match_id="8888888",
                weak_labels=_wk_signals(overall="🟡"),
                evaluation=_b_eval(overall="🟢"),  # disagree
            ),
        ]
        adj = Adjudicator(entries=entries)
        report = adj.run()
        # 1/2 overall agreement
        assert report["summary"]["overall_agreement_rate"] == pytest.approx(0.5)

    def test_context_breakdowns_present(self):
        """Context breakdowns are generated."""
        entry = _make_entry(
            weak_labels=_wk_signals(),
            evaluation=_b_eval(),
        )
        adj = Adjudicator(entries=[entry])
        report = adj.run()
        assert isinstance(report["context_breakdowns"], list)
