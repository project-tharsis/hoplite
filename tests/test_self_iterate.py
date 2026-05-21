"""Unit tests for scripts/self_iterate.py helpers.

Tests: report lookup logic, prompt source detection, WK drift detection,
version stale-evaluation logic.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.self_iterate import (
    _find_report,
    _load_existing_self_iteration_job,
    _find_prompt_from_backfill_job,
    _detect_wk_drift,
    _is_stale_evaluation,
    _filter_entries,
    run_decide_experiment,
)


# ── Fixtures ───────────────────────────────────────────────────────


@pytest.fixture
def tmp_run(tmp_path):
    """Create a temp run directory with structure."""
    run = tmp_path / "runs" / "seed-002"
    (run / "reports").mkdir(parents=True)
    return run


@pytest.fixture
def sample_entry():
    return {
        "match_id": "1208154",
        "features": {"result": "W", "opponent_name": "Chelsea"},
        "weak_labels": {
            "overall_signal": "🟢",
            "model_signals": {"1": "🟢", "2": "🟢", "3": "🟢", "4": "🟡", "5": "🟡", "6": "🟡"},
            "dimension_signals": {"execution": "🟢", "adjustment": "🟡", "satisfaction": "🟢"},
        },
        "features_version": "v1",
        "weak_label_version": "v1.1",
        "rubric_version": "arteta_v1",
        "prompt_builder_version": "v1",
        "evaluation": {
            "source": "llm",
            "overall_signal": "🟢",
            "model_signals": {"1": "🟢", "2": "🟢", "3": "🟢", "4": "🟡", "5": "🟡", "6": "🟡"},
            "dimension_signals": {"execution": "🟢", "adjustment": "🟡", "satisfaction": "🟢"},
            "evidence": {"1": ["e1"], "2": ["e2"], "3": ["e3"], "4": ["e4"], "5": ["e5"], "6": ["e6"]},
            "confidence": {"1": "high", "2": "high", "3": "high", "4": "medium", "5": "medium", "6": "medium"},
            "missing_or_weak_evidence": [],
            "weak_label_disagreements": [],
            "narrative": "Test narrative.",
            "metadata": {
                "evaluator_id": "B",
                "features_version": "v1",
                "weak_label_version": "v1.1",
                "rubric_version": "arteta_v1",
                "prompt_builder_version": "v1",
            },
        },
        "backfill": {
            "run_id": "seed-002",
            "report_path": "",
            "fixture_id": "1208154",
        },
    }


# ── Report lookup tests ────────────────────────────────────────────


class TestFindReport:
    """Test _find_report priority-based lookup."""

    def test_prefers_entry_backfill_report_path(self, tmp_run, sample_entry):
        """Priority 1: entry.backfill.report_path when file exists."""
        report_path = tmp_run / "reports" / "1208154.json"
        report_path.write_text('{"match": {"fixture_id": "1208154"}}')
        sample_entry["backfill"]["report_path"] = str(report_path)

        result, candidates = _find_report(sample_entry, reports_root=str(tmp_run.parent.parent / "runs"))
        assert result == str(report_path)
        assert candidates == []

    def test_falls_back_to_run_id_lookup(self, tmp_run, sample_entry):
        """Priority 2: reports-root/<run_id>/reports/<fixture_id>.json."""
        report_path = tmp_run / "reports" / "1208154.json"
        report_path.write_text('{"match": {"fixture_id": "1208154"}}')
        sample_entry["backfill"]["report_path"] = ""

        result, candidates = _find_report(sample_entry, reports_root=str(tmp_run.parent))
        assert result is not None
        assert "1208154.json" in result

    def test_returns_none_when_no_report_found(self, sample_entry):
        """No report anywhere → returns None."""
        sample_entry["backfill"]["report_path"] = ""
        sample_entry["backfill"]["run_id"] = "nonexistent"
        result, candidates = _find_report(sample_entry, reports_root="/nonexistent/path")
        assert result is None


# ── Prompt source detection ────────────────────────────────────────


class TestPromptSource:
    """Test prompt reuse logic."""

    def test_reuse_existing_self_iteration_job(self, tmp_path, sample_entry):
        """Existing self-iteration job with same match_id → reuse prompt."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        existing_jobs = output_dir / "llm_jobs.jsonl"
        existing_row = {
            "match_id": "1208154",
            "prompt": "existing prompt text",
            "prompt_hash": "sha256:abc123",
            "prompt_source": "backfill_llm_job",
        }
        existing_jobs.write_text(json.dumps(existing_row) + "\n")

        result = _load_existing_self_iteration_job(str(output_dir), "1208154")
        assert result is not None
        assert result["prompt"] == "existing prompt text"
        assert result["prompt_source"] == "backfill_llm_job"

    def test_find_prompt_from_backfill_job(self, tmp_path, sample_entry):
        """Prompt found in backfill llm_jobs.jsonl."""
        backfill_dir = tmp_path / "backfill" / "seed-002"
        backfill_dir.mkdir(parents=True)
        jobs_file = backfill_dir / "llm_jobs.jsonl"
        row = {
            "legacy_match_id": "1208154",
            "prompt": "backfill prompt",
        }
        jobs_file.write_text(json.dumps(row) + "\n")

        result = _find_prompt_from_backfill_job(str(backfill_dir), "1208154", "1208154")
        assert result is not None
        assert result["prompt"] == "backfill prompt"


# ── WK drift detection ─────────────────────────────────────────────


class TestWkDriftDetection:
    """Test _detect_wk_drift."""

    def test_detects_overall_signal_change(self, sample_entry):
        """Different overall_signal triggers drift detection."""
        new_wk = {
            "overall_signal": "🟡",
            "model_signals": sample_entry["weak_labels"]["model_signals"],
            "dimension_signals": sample_entry["weak_labels"]["dimension_signals"],
        }
        assert _detect_wk_drift(sample_entry["weak_labels"], new_wk) is True

    def test_no_drift_when_identical(self, sample_entry):
        """Identical WK → no drift."""
        assert _detect_wk_drift(sample_entry["weak_labels"], sample_entry["weak_labels"]) is False


# ── Stale evaluation logic ─────────────────────────────────────────


class TestStaleEvaluation:
    """Test _is_stale_evaluation."""

    def test_stale_when_version_mismatch(self, sample_entry):
        """Evaluation metadata version differs from entry version → stale."""
        sample_entry["evaluation"]["metadata"]["rubric_version"] = "arteta_v0"
        current_versions = {
            "features_version": "v1",
            "weak_label_version": "v1.1",
            "rubric_version": "arteta_v1",
            "prompt_builder_version": "v1",
        }
        assert _is_stale_evaluation(sample_entry, current_versions) is True

    def test_not_stale_when_versions_match(self, sample_entry):
        """All versions match → not stale."""
        current_versions = {
            "features_version": "v1",
            "weak_label_version": "v1.1",
            "rubric_version": "arteta_v1",
            "prompt_builder_version": "v1",
        }
        assert _is_stale_evaluation(sample_entry, current_versions) is False

    def test_stale_when_no_metadata(self, sample_entry):
        """No evaluation metadata → stale."""
        sample_entry["evaluation"] = {"source": "llm"}
        current_versions = {
            "features_version": "v1",
            "weak_label_version": "v1.1",
            "rubric_version": "arteta_v1",
            "prompt_builder_version": "v1",
        }
        assert _is_stale_evaluation(sample_entry, current_versions) is True


# ── Filter entries ─────────────────────────────────────────────────


class TestFilterEntries:
    """Test _filter_entries."""

    def test_filters_missing_evaluation(self, sample_entry):
        """Entry without evaluator B evaluation is filtered in."""
        del sample_entry["evaluation"]
        entries = [sample_entry]
        result = _filter_entries(entries, "B", "missing-evaluation")
        assert len(result) == 1

    def test_excludes_entry_with_evaluation(self, sample_entry):
        """Entry with evaluator B evaluation is filtered out."""
        entries = [sample_entry]
        result = _filter_entries(entries, "B", "missing-evaluation")
        assert len(result) == 0

    def test_stale_evaluation_filter(self, sample_entry):
        """Entry with stale version is included in stale-evaluation filter."""
        sample_entry["evaluation"]["metadata"]["rubric_version"] = "arteta_v0"
        entries = [sample_entry]
        current_versions = {
            "features_version": "v1",
            "weak_label_version": "v1.1",
            "rubric_version": "arteta_v1",
            "prompt_builder_version": "v1",
        }
        result = _filter_entries(entries, "B", "stale-evaluation", current_versions=current_versions)
        assert len(result) == 1


# ── Experiment decision policy ─────────────────────────────────────


def _write_json(tmp_path: Path, name: str, data: dict) -> str:
    path = tmp_path / name
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _adj(compared: int = 94) -> dict:
    return {
        "summary": {
            "compared": compared,
            "overall_agreement_rate": 0.8,
            "dimension_agreement_rate": 0.5,
            "model_agreement_rate": 0.42,
            "wk_too_harsh": 13,
            "wk_too_generous": 6,
            "dimension_level_disagreement": 28,
            "model_level_disagreement": 7,
        },
        "rows": [],
    }


def _ingest(total: int = 102, applied: int = 94, errors: int = 8) -> dict:
    return {
        "summary": {
            "total_results": total,
            "applied": applied,
            "skipped": 0,
            "errors": errors,
            "dry_run": False,
        },
        "errors": [
            {"match_id": str(i), "error": {"code": "QUARANTINE", "message": "placeholder"}}
            for i in range(errors)
        ],
    }


def _run_decision(tmp_path: Path, comparison: dict, ingest: dict | None = None, candidate_compared: int = 94):
    baseline = _write_json(tmp_path, "baseline.json", _adj(102))
    candidate = _write_json(tmp_path, "candidate.json", _adj(candidate_compared))
    comp = _write_json(tmp_path, "comparison.json", comparison)
    ing = _write_json(tmp_path, "ingest.json", ingest or _ingest(errors=0))
    out = str(tmp_path / "decision.json")
    return run_decide_experiment(
        baseline_run_id="b-001",
        candidate_run_id="b-003",
        baseline_adjudication_path=baseline,
        candidate_adjudication_path=candidate,
        comparison_path=comp,
        ingest_report_path=ing,
        output_path=out,
    )


class TestExperimentDecisionPolicy:
    def test_promotes_b003_like_clean_subset(self, tmp_path):
        comparison = {
            "clean_subset": {
                "b001": {
                    "overall_agreement_rate": 0.6489,
                    "dimension_agreement_rate": 0.2766,
                    "model_agreement_rate": 0.1915,
                    "wk_too_harsh": 33,
                    "wk_too_generous": 0,
                    "dimension_level_disagreement": 35,
                    "model_level_disagreement": 8,
                    "compared": 94,
                },
                "b002": {
                    "overall_agreement_rate": 0.7979,
                    "dimension_agreement_rate": 0.5,
                    "model_agreement_rate": 0.4255,
                    "wk_too_harsh": 13,
                    "wk_too_generous": 6,
                    "dimension_level_disagreement": 28,
                    "model_level_disagreement": 7,
                    "compared": 94,
                },
                "delta": {
                    "overall_agreement_rate": 0.149,
                    "dimension_agreement_rate": 0.2234,
                    "model_agreement_rate": 0.234,
                    "wk_too_harsh": -20,
                    "wk_too_generous": 6,
                    "dimension_level_disagreement": -7,
                    "model_level_disagreement": -1,
                },
                "criteria_met": 5,
                "criteria_total": 5,
                "same_denominator": True,
                "effective": True,
            }
        }
        result = _run_decision(tmp_path, comparison, _ingest(errors=8))
        assert result["decision"] == "promote"
        assert result["effective"] is True
        assert result["cautions"]

    def test_rolls_back_b004_like_regression(self, tmp_path):
        comparison = {
            "clean_subset_vs_b003": {
                "b003": {
                    "overall_agreement_rate": 0.809,
                    "dimension_agreement_rate": 0.5169,
                    "model_agreement_rate": 0.4382,
                    "wk_too_harsh": 13,
                    "wk_too_generous": 4,
                    "dimension_level_disagreement": 28,
                    "model_level_disagreement": 7,
                    "compared": 93,
                },
                "delta": {
                    "overall_agreement_rate": -0.1316,
                    "dimension_agreement_rate": -0.0545,
                    "model_agreement_rate": -0.0404,
                    "wk_too_harsh": 7,
                    "wk_too_generous": 6,
                    "dimension_level_disagreement": -8,
                    "model_level_disagreement": -1,
                },
                "criteria_met": 1,
                "criteria_total": 5,
                "same_denominator": True,
                "effective": False,
            },
            "b003": {"compared": 94},
            "b004": {
                "overall_agreement_rate": 0.6774,
                "dimension_agreement_rate": 0.4624,
                "model_agreement_rate": 0.3978,
                "wk_too_harsh": 20,
                "wk_too_generous": 10,
                "dimension_level_disagreement": 20,
                "model_level_disagreement": 6,
                "compared": 93,
            },
        }
        result = run_decide_experiment(
            baseline_run_id="b-003",
            candidate_run_id="b-004",
            baseline_adjudication_path=_write_json(tmp_path, "baseline.json", _adj(94)),
            candidate_adjudication_path=_write_json(tmp_path, "candidate.json", _adj(93)),
            comparison_path=_write_json(tmp_path, "comparison.json", comparison),
            ingest_report_path=_write_json(tmp_path, "ingest.json", _ingest(errors=9, applied=93)),
            output_path=str(tmp_path / "decision.json"),
        )
        assert result["decision"] == "rollback"
        assert result["effective"] is False

    def test_rejects_quality_pollution_signature(self, tmp_path):
        comparison = {
            "b001": {"overall_agreement_rate": 0.6569, "dimension_agreement_rate": 0.2647, "model_agreement_rate": 0.1765, "wk_too_harsh": 34, "wk_too_generous": 1, "dimension_level_disagreement": 40, "model_level_disagreement": 9, "compared": 102},
            "b002": {"overall_agreement_rate": 0.5392, "dimension_agreement_rate": 0.1373, "model_agreement_rate": 0.0588, "wk_too_harsh": 12, "wk_too_generous": 35, "dimension_level_disagreement": 41, "model_level_disagreement": 8, "compared": 102},
            "delta": {"overall_agreement_rate": -0.1177, "dimension_agreement_rate": -0.1274, "model_agreement_rate": -0.1177, "wk_too_harsh": -22, "wk_too_generous": 34, "dimension_level_disagreement": 1, "model_level_disagreement": -1},
            "judgment": {"criteria_met": 1, "effective": False},
        }
        result = _run_decision(tmp_path, comparison, _ingest(errors=0), candidate_compared=102)
        assert result["decision"] == "reject_quality"

    def test_collects_more_data_when_sample_small(self, tmp_path):
        comparison = {
            "b001": {"overall_agreement_rate": 0.6, "dimension_agreement_rate": 0.3, "model_agreement_rate": 0.2, "wk_too_harsh": 10, "wk_too_generous": 1, "dimension_level_disagreement": 20, "model_level_disagreement": 5, "compared": 80},
            "b002": {"overall_agreement_rate": 0.7, "dimension_agreement_rate": 0.4, "model_agreement_rate": 0.3, "wk_too_harsh": 8, "wk_too_generous": 1, "dimension_level_disagreement": 15, "model_level_disagreement": 4, "compared": 80},
            "delta": {"overall_agreement_rate": 0.1, "dimension_agreement_rate": 0.1, "model_agreement_rate": 0.1, "wk_too_harsh": -2, "wk_too_generous": 0, "dimension_level_disagreement": -5, "model_level_disagreement": -1},
            "criteria_met": 5,
            "criteria_total": 5,
            "same_denominator": True,
            "effective": True,
        }
        result = _run_decision(tmp_path, comparison, _ingest(total=80, applied=80, errors=0), candidate_compared=80)
        assert result["decision"] == "collect_more_data"

    def test_requires_human_review_for_effective_generous_drift(self, tmp_path):
        comparison = {
            "b001": {"overall_agreement_rate": 0.6, "dimension_agreement_rate": 0.3, "model_agreement_rate": 0.2, "wk_too_harsh": 10, "wk_too_generous": 1, "dimension_level_disagreement": 20, "model_level_disagreement": 5, "compared": 100},
            "b002": {"overall_agreement_rate": 0.62, "dimension_agreement_rate": 0.4, "model_agreement_rate": 0.3, "wk_too_harsh": 8, "wk_too_generous": 8, "dimension_level_disagreement": 15, "model_level_disagreement": 4, "compared": 100},
            "delta": {"overall_agreement_rate": 0.02, "dimension_agreement_rate": 0.1, "model_agreement_rate": 0.1, "wk_too_harsh": -2, "wk_too_generous": 7, "dimension_level_disagreement": -5, "model_level_disagreement": -1},
            "criteria_met": 3,
            "criteria_total": 5,
            "same_denominator": True,
            "effective": True,
        }
        result = _run_decision(tmp_path, comparison, _ingest(errors=0), candidate_compared=100)
        assert result["decision"] == "human_review_required"
