"""E2E tests for scripts/self_iterate.py.

Tests: make-jobs, ingest-results, promote-blind-spots, .gitignore.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


# ── Helpers ────────────────────────────────────────────────────────


def _run_self_iterate(args: list[str], cwd: str | None = None) -> tuple[int, str, str]:
    """Run self_iterate.py as a subprocess, return (returncode, stdout, stderr)."""
    import subprocess

    cmd = [sys.executable, str(Path(__file__).resolve().parent.parent.parent / "scripts" / "self_iterate.py")] + args
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    return result.returncode, result.stdout, result.stderr


def _make_kb_entry(
    match_id: str,
    *,
    has_features: bool = True,
    has_evaluation: bool = False,
    evaluator_id: str = "B",
    backfill_run_id: str = "seed-002",
    backfill_report_path: str = "",
) -> dict:
    """Build a minimal KB entry for testing."""
    entry: dict = {
        "match_id": match_id,
        "opponent": "Chelsea",
        "result": "W",
        "score": "2-1",
        "timestamp": "2026-01-15",
        "competition": "Premier League",
    }
    if has_features:
        entry["features"] = {
            "result": "W",
            "opponent_name": "Chelsea",
            "arsenal_goals": 2,
            "opponent_goals": 1,
            "venue": "home",
            "opponent_quality": "top6",
            "competition_stage": "league_early",
        }
        entry["weak_labels"] = {
            "overall_signal": "🟢",
            "model_signals": {"1": "🟢", "2": "🟢", "3": "🟢", "4": "🟡", "5": "🟡", "6": "🟡"},
            "dimension_signals": {"execution": "🟢", "adjustment": "🟡", "satisfaction": "🟢"},
            "confidence": {},
            "evidence_refs": {},
            "missing_data_penalty": 0,
            "weak_label_version": "v1.1",
        }
        entry["features_version"] = "v1"
        entry["weak_label_version"] = "v1.1"
        entry["rubric_version"] = "arteta_v1"
        entry["prompt_builder_version"] = "v1"
        entry["backfill"] = {
            "status": "feature_backfilled",
            "run_id": backfill_run_id,
            "fixture_id": match_id,
            "report_path": backfill_report_path,
        }

    if has_evaluation:
        entry["evaluation"] = {
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
                "evaluator_id": evaluator_id,
                "features_version": "v1",
                "weak_label_version": "v1.1",
                "rubric_version": "arteta_v1",
                "prompt_builder_version": "v1",
            },
        }
    return entry


def _make_report(fixture_id: str) -> dict:
    """Build a minimal report JSON."""
    return {
        "match": {
            "fixture_id": fixture_id,
            "date": "2026-01-15",
            "competition": "Premier League",
            "home_team": "Arsenal",
            "away_team": "Chelsea",
            "arsenal_score": 2,
            "opponent_score": 1,
            "result": "W",
        },
        "context": {
            "opponent": "Chelsea",
            "opponent_quality": "top6",
            "venue": "home",
            "competition_stage": "league_early",
        },
        "stats": {
            "possession": {"home": 55, "away": 45},
            "shots": {"home": 15, "away": 8},
            "shots_on_target": {"home": 6, "away": 3},
            "xg": {"home": 1.8, "away": 0.9},
            "corners": {"home": 7, "away": 3},
        },
        "key_events": [],
        "predicted_plan": {},
    }


# ── Test: make-jobs only outputs rows missing evaluator B ──────────


class TestMakeJobsMissingEvaluation:
    """make-jobs should only output rows that are feature-backed and missing evaluator B."""

    def test_only_missing_evaluations(self, tmp_path):
        """Entries with existing evaluator B are excluded."""
        # Setup KB
        kb_entries = [
            _make_kb_entry("1001", has_evaluation=False),  # should be included
            _make_kb_entry("1002", has_evaluation=True),   # should be excluded
            _make_kb_entry("1003", has_evaluation=False),  # should be included
        ]
        kb_path = tmp_path / "knowledge.json"
        kb_path.write_text(json.dumps(kb_entries))

        # Setup reports
        reports_root = tmp_path / "backfill" / "runs"
        for mid in ("1001", "1002", "1003"):
            reports_dir = reports_root / "seed-002" / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)
            (reports_dir / f"{mid}.json").write_text(json.dumps(_make_report(mid)))

        output_dir = tmp_path / "self_iteration" / "runs" / "b-001"

        rc, stdout, stderr = _run_self_iterate([
            "make-jobs",
            "--kb", str(kb_path),
            "--reports-root", str(reports_root),
            "--only", "missing-evaluation",
            "--evaluator-id", "B",
            "--run-id", "b-001",
            "--output", str(output_dir),
        ])

        assert rc == 0, f"stdout: {stdout}\nstderr: {stderr}"
        jobs_path = output_dir / "llm_jobs.jsonl"
        assert jobs_path.exists()
        jobs = [json.loads(line) for line in jobs_path.read_text().splitlines() if line.strip()]
        match_ids = {j["match_id"] for j in jobs}
        assert "1001" in match_ids
        assert "1003" in match_ids
        assert "1002" not in match_ids


# ── Test: make-jobs prioritizes entry.backfill.report_path ─────────


class TestMakeJobsReportPriority:
    """make-jobs should prefer entry.backfill.report_path when file exists."""

    def test_prefers_backfill_report_path(self, tmp_path):
        """When entry.backfill.report_path points to existing file, use it."""
        kb_entries = [_make_kb_entry("2001", has_evaluation=False)]
        kb_path = tmp_path / "knowledge.json"
        kb_path.write_text(json.dumps(kb_entries))

        # Create report at specific path
        specific_report_dir = tmp_path / "custom" / "reports"
        specific_report_dir.mkdir(parents=True)
        specific_report = specific_report_dir / "2001.json"
        specific_report.write_text(json.dumps(_make_report("2001")))

        # Update entry's report_path
        kb_entries[0]["backfill"]["report_path"] = str(specific_report)
        kb_path.write_text(json.dumps(kb_entries))

        # Also create report at default location to verify it's not used
        reports_root = tmp_path / "backfill" / "runs"
        default_dir = reports_root / "seed-002" / "reports"
        default_dir.mkdir(parents=True, exist_ok=True)
        (default_dir / "2001.json").write_text(json.dumps({"wrong": "report"}))

        output_dir = tmp_path / "self_iteration" / "runs" / "b-001"

        rc, stdout, stderr = _run_self_iterate([
            "make-jobs",
            "--kb", str(kb_path),
            "--reports-root", str(reports_root),
            "--only", "missing-evaluation",
            "--evaluator-id", "B",
            "--run-id", "b-001",
            "--output", str(output_dir),
        ])

        assert rc == 0, f"stdout: {stdout}\nstderr: {stderr}"
        jobs_path = output_dir / "llm_jobs.jsonl"
        jobs = [json.loads(line) for line in jobs_path.read_text().splitlines() if line.strip()]
        assert len(jobs) == 1
        assert jobs[0]["report_path"] == str(specific_report)


# ── Test: make-jobs reuses prompt from backfill llm_jobs.jsonl ─────


class TestMakeJobsPromptReuse:
    """make-jobs should reuse prompt from backfill llm_jobs.jsonl."""

    def test_reuses_backfill_prompt(self, tmp_path):
        """Prompt from backfill job is reused with prompt_source=backfill_llm_job."""
        kb_entries = [_make_kb_entry("3001", has_evaluation=False)]
        kb_path = tmp_path / "knowledge.json"
        kb_path.write_text(json.dumps(kb_entries))

        # Create backfill run with llm_jobs.jsonl
        backfill_dir = tmp_path / "backfill" / "runs" / "seed-002"
        backfill_dir.mkdir(parents=True)
        (backfill_dir / "reports").mkdir()
        (backfill_dir / "reports" / "3001.json").write_text(json.dumps(_make_report("3001")))

        backfill_job = {
            "legacy_match_id": "3001",
            "fixture_id": "3001",
            "prompt": "original backfill prompt text",
            "features": kb_entries[0]["features"],
            "weak_labels": kb_entries[0]["weak_labels"],
        }
        (backfill_dir / "llm_jobs.jsonl").write_text(json.dumps(backfill_job) + "\n")

        reports_root = tmp_path / "backfill" / "runs"
        output_dir = tmp_path / "self_iteration" / "runs" / "b-001"

        rc, stdout, stderr = _run_self_iterate([
            "make-jobs",
            "--kb", str(kb_path),
            "--reports-root", str(reports_root),
            "--only", "missing-evaluation",
            "--evaluator-id", "B",
            "--run-id", "b-001",
            "--output", str(output_dir),
        ])

        assert rc == 0, f"stdout: {stdout}\nstderr: {stderr}"
        jobs = [json.loads(line) for line in (output_dir / "llm_jobs.jsonl").read_text().splitlines() if line.strip()]
        assert len(jobs) == 1
        assert jobs[0]["prompt"] == "original backfill prompt text"
        assert jobs[0]["prompt_source"] == "backfill_llm_job"


# ── Test: make-jobs skips row with REPORT_NOT_FOUND ────────────────


class TestMakeJobsReportNotFound:
    """make-jobs should skip entries where no report is found."""

    def test_skips_missing_report(self, tmp_path):
        """Entry with no report found → skipped, REPORT_NOT_FOUND in report."""
        kb_entries = [_make_kb_entry("4001", has_evaluation=False, backfill_report_path="")]
        kb_path = tmp_path / "knowledge.json"
        kb_path.write_text(json.dumps(kb_entries))

        # No reports directory at all
        reports_root = tmp_path / "nonexistent"
        output_dir = tmp_path / "self_iteration" / "runs" / "b-001"

        rc, stdout, stderr = _run_self_iterate([
            "make-jobs",
            "--kb", str(kb_path),
            "--reports-root", str(reports_root),
            "--only", "missing-evaluation",
            "--evaluator-id", "B",
            "--run-id", "b-001",
            "--output", str(output_dir),
        ])

        assert rc == 0, f"stdout: {stdout}\nstderr: {stderr}"
        # No jobs should be generated
        jobs_path = output_dir / "llm_jobs.jsonl"
        if jobs_path.exists():
            jobs = [line for line in jobs_path.read_text().splitlines() if line.strip()]
            assert len(jobs) == 0

        # Report should contain REPORT_NOT_FOUND
        report_path = output_dir / "make_jobs_report.json"
        assert report_path.exists()
        report = json.loads(report_path.read_text())
        found_error = any(
            d.get("error", {}).get("code") == "REPORT_NOT_FOUND"
            for d in report.get("per_match", [])
        )
        assert found_error


# ── Test: make-jobs outputs correct job_schema_version ─────────────


class TestMakeJobsSchemaVersion:
    """make-jobs output must have job_schema_version=self_iteration_job_v1."""

    def test_job_schema_version(self, tmp_path):
        """Each job row has the correct schema version."""
        kb_entries = [_make_kb_entry("5001", has_evaluation=False)]
        kb_path = tmp_path / "knowledge.json"
        kb_path.write_text(json.dumps(kb_entries))

        reports_root = tmp_path / "backfill" / "runs"
        reports_dir = reports_root / "seed-002" / "reports"
        reports_dir.mkdir(parents=True)
        (reports_dir / "5001.json").write_text(json.dumps(_make_report("5001")))

        output_dir = tmp_path / "self_iteration" / "runs" / "b-001"

        rc, stdout, stderr = _run_self_iterate([
            "make-jobs",
            "--kb", str(kb_path),
            "--reports-root", str(reports_root),
            "--only", "missing-evaluation",
            "--evaluator-id", "B",
            "--run-id", "b-001",
            "--output", str(output_dir),
        ])

        assert rc == 0
        jobs = [json.loads(line) for line in (output_dir / "llm_jobs.jsonl").read_text().splitlines() if line.strip()]
        assert len(jobs) == 1
        assert jobs[0]["job_schema_version"] == "self_iteration_job_v1"


# ── Test: ingest-results dry-run does NOT modify KB ────────────────


class TestIngestResultsDryRun:
    """ingest-results without --write must not modify KB."""

    def test_dry_run_no_kb_mutation(self, tmp_path):
        """Dry-run should not change the KB file."""
        kb_entries = [_make_kb_entry("6001", has_evaluation=False)]
        kb_path = tmp_path / "knowledge.json"
        kb_path.write_text(json.dumps(kb_entries))
        original_kb = kb_path.read_text()

        run_dir = tmp_path / "self_iteration" / "runs" / "b-001"
        run_dir.mkdir(parents=True)

        # Create llm_results.jsonl
        result_row = {
            "job_schema_version": "self_iteration_job_v1",
            "match_id": "6001",
            "evaluator_id": "B",
            "run_id": "b-001",
            "prompt_hash": "sha256:abc",
            "model": "test-model",
            "created_at": "2026-05-20T00:00:00Z",
            "evaluation": {
                "overall_signal": "🟢",
                "model_signals": {"1": "🟢", "2": "🟢", "3": "🟢", "4": "🟡", "5": "🟡", "6": "🟡"},
                "dimension_signals": {"execution": "🟢", "adjustment": "🟡", "satisfaction": "🟢"},
                "evidence": {"1": ["e1"], "2": ["e2"], "3": ["e3"], "4": ["e4"], "5": ["e5"], "6": ["e6"]},
                "confidence": {"1": "high", "2": "high", "3": "high", "4": "medium", "5": "medium", "6": "medium"},
                "missing_or_weak_evidence": [],
                "weak_label_disagreements": [],
                "narrative": "Test narrative for dry run.",
            },
        }
        (run_dir / "llm_results.jsonl").write_text(json.dumps(result_row) + "\n")

        rc, stdout, stderr = _run_self_iterate([
            "ingest-results",
            "--kb", str(kb_path),
            "--run", str(run_dir),
            "--input", str(run_dir / "llm_results.jsonl"),
        ])

        assert rc == 0, f"stdout: {stdout}\nstderr: {stderr}"
        assert kb_path.read_text() == original_kb, "KB should not be modified in dry-run"


# ── Test: ingest-results --write DOES modify KB ────────────────────


class TestIngestResultsWrite:
    """ingest-results --write should modify KB and write snapshots."""

    def test_write_modifies_kb(self, tmp_path):
        """--write should update KB with evaluation and write snapshots."""
        kb_entries = [_make_kb_entry("7001", has_evaluation=False)]
        kb_path = tmp_path / "knowledge.json"
        kb_path.write_text(json.dumps(kb_entries))

        run_dir = tmp_path / "self_iteration" / "runs" / "b-001"
        run_dir.mkdir(parents=True)

        result_row = {
            "job_schema_version": "self_iteration_job_v1",
            "match_id": "7001",
            "evaluator_id": "B",
            "run_id": "b-001",
            "prompt_hash": "sha256:abc",
            "model": "test-model",
            "created_at": "2026-05-20T00:00:00Z",
            "evaluation": {
                "overall_signal": "🟢",
                "model_signals": {"1": "🟢", "2": "🟢", "3": "🟢", "4": "🟡", "5": "🟡", "6": "🟡"},
                "dimension_signals": {"execution": "🟢", "adjustment": "🟡", "satisfaction": "🟢"},
                "evidence": {"1": ["e1"], "2": ["e2"], "3": ["e3"], "4": ["e4"], "5": ["e5"], "6": ["e6"]},
                "confidence": {"1": "high", "2": "high", "3": "high", "4": "medium", "5": "medium", "6": "medium"},
                "missing_or_weak_evidence": [],
                "weak_label_disagreements": [],
                "narrative": "Test narrative for write mode.",
            },
        }
        (run_dir / "llm_results.jsonl").write_text(json.dumps(result_row) + "\n")

        rc, stdout, stderr = _run_self_iterate([
            "ingest-results",
            "--kb", str(kb_path),
            "--run", str(run_dir),
            "--input", str(run_dir / "llm_results.jsonl"),
            "--write",
        ])

        assert rc == 0, f"stdout: {stdout}\nstderr: {stderr}"

        # KB should be updated
        updated_kb = json.loads(kb_path.read_text())
        entry = next(e for e in updated_kb if e["match_id"] == "7001")
        assert entry["evaluation"]["source"] == "llm"
        assert entry["evaluation"]["metadata"]["evaluator_id"] == "B"

        # Snapshots should exist
        assert (run_dir / "knowledge.before.json").exists()
        assert (run_dir / "knowledge.after.json").exists()
        assert (run_dir / "ingest_report.json").exists()


# ── Test: promote-blind-spots --write ──────────────────────────────


class TestPromoteBlindSpots:
    """promote-blind-spots --write should update blind spots JSON."""

    def test_promotes_blind_spot(self, tmp_path):
        """Valid prompt_blind_spot candidates should be added."""
        candidates = {
            "candidates": [
                {
                    "id": "top6_home_win_dominant_control",
                    "target": "overall_signal",
                    "predicate": {"result": "W", "opponent_quality": ["top6"]},
                    "wk_pattern": "🟡",
                    "b_pattern": "🟢",
                    "direction": "upgrade",
                    "support": 4,
                    "precision_vs_b": 0.8,
                    "false_positive_count": 1,
                    "examples": ["1208154"],
                    "counterexamples": [],
                    "proposed_action": "prompt_blind_spot",
                    "risk": "medium",
                    "rationale": "评估器B多次升级强队胜利。",
                },
            ],
            "rejected_candidates": [],
        }
        candidates_path = tmp_path / "rule_candidates.json"
        candidates_path.write_text(json.dumps(candidates))

        blind_spots = {
            "version": "v1",
            "blind_spots": [
                {
                    "id": "dominant_stats_loss",
                    "description": "WK can overrate matches where Arsenal dominates shots/xG/possession but loses.",
                    "guardrail": "Do not let shot/xG/possession dominance override result satisfaction.",
                    "source": "human_review",
                    "weak_label_version": "v1.1",
                    "status": "active",
                },
            ],
        }
        bs_path = tmp_path / "arteta_blind_spots.json"
        bs_path.write_text(json.dumps(blind_spots))

        rc, stdout, stderr = _run_self_iterate([
            "promote-blind-spots",
            "--candidates", str(candidates_path),
            "--output", str(bs_path),
            "--write",
        ])

        assert rc == 0, f"stdout: {stdout}\nstderr: {stderr}"
        updated = json.loads(bs_path.read_text())
        ids = [s["id"] for s in updated["blind_spots"]]
        assert "top6_home_win_dominant_control" in ids
        assert updated["version"] == "v2"


# ── Test: promote-blind-spots idempotency ──────────────────────────


class TestPromoteBlindSpotsIdempotent:
    """Re-running promote-blind-spots should not duplicate blind spots."""

    def test_idempotent(self, tmp_path):
        """Second run with same candidates should not add duplicates."""
        candidates = {
            "candidates": [
                {
                    "id": "top6_home_win_dominant_control",
                    "target": "overall_signal",
                    "predicate": {"result": "W", "opponent_quality": ["top6"]},
                    "wk_pattern": "🟡",
                    "b_pattern": "🟢",
                    "direction": "upgrade",
                    "support": 4,
                    "precision_vs_b": 0.8,
                    "false_positive_count": 1,
                    "examples": ["1208154"],
                    "counterexamples": [],
                    "proposed_action": "prompt_blind_spot",
                    "risk": "medium",
                    "rationale": "评估器B多次升级强队胜利。",
                },
            ],
            "rejected_candidates": [],
        }
        candidates_path = tmp_path / "rule_candidates.json"
        candidates_path.write_text(json.dumps(candidates))

        blind_spots = {
            "version": "v1",
            "blind_spots": [
                {
                    "id": "dominant_stats_loss",
                    "description": "WK can overrate matches where Arsenal dominates shots/xG/possession but loses.",
                    "guardrail": "Do not let shot/xG/possession dominance override result satisfaction.",
                    "source": "human_review",
                    "weak_label_version": "v1.1",
                    "status": "active",
                },
            ],
        }
        bs_path = tmp_path / "arteta_blind_spots.json"
        bs_path.write_text(json.dumps(blind_spots))

        # First run
        rc1, _, _ = _run_self_iterate([
            "promote-blind-spots",
            "--candidates", str(candidates_path),
            "--output", str(bs_path),
            "--write",
        ])
        assert rc1 == 0

        # Second run
        rc2, _, _ = _run_self_iterate([
            "promote-blind-spots",
            "--candidates", str(candidates_path),
            "--output", str(bs_path),
            "--write",
        ])
        assert rc2 == 0

        updated = json.loads(bs_path.read_text())
        count = sum(1 for s in updated["blind_spots"] if s["id"] == "top6_home_win_dominant_control")
        assert count == 1, "Should not duplicate blind spots"


# ── Test: .gitignore allows self_iteration but excludes KB snapshots ──


class TestGitignore:
    """Verify .gitignore allows self_iteration artifacts but excludes KB snapshots."""

    def test_gitignore_rules(self):
        """Check .gitignore contains the right rules."""
        gitignore_path = Path(__file__).resolve().parent.parent.parent / ".gitignore"
        content = gitignore_path.read_text()

        # Should allow self_iteration
        assert "!data/self_iteration" in content
        assert "!data/self_iteration/**" in content

        # Should exclude KB snapshots
        assert "data/self_iteration/**/knowledge.before.json" in content
        assert "data/self_iteration/**/knowledge.after.json" in content


# ── Test: CLI subcommands adjudicate and mine-rules work end-to-end ──


class TestCliAdjudicate:
    """adjudicate CLI subcommand produces valid summary output."""

    def test_adjudicate_cli_produces_summary(self, tmp_path):
        """python scripts/self_iterate.py adjudicate ... → ok + summary."""
        kb_entries = [
            _make_kb_entry("5001", has_evaluation=True),
        ]
        kb_path = tmp_path / "knowledge.json"
        kb_path.write_text(json.dumps(kb_entries))
        output_json = tmp_path / "adj_report.json"

        rc, stdout, stderr = _run_self_iterate([
            "adjudicate",
            "--kb", str(kb_path),
            "--run-id", "test-001",
            "--output", str(output_json),
        ])
        assert rc == 0, f"stderr: {stderr}"
        result = json.loads(stdout)
        assert result["ok"] is True
        assert "summary" in result
        assert result["summary"]["total_entries"] == 1


class TestCliMineRules:
    """mine-rules CLI subcommand produces valid summary output."""

    def test_mine_rules_cli_produces_summary(self, tmp_path):
        """python scripts/self_iterate.py mine-rules ... → ok + summary."""
        adj_report = {
            "run_id": "test-001",
            "summary": {},
            "rows": [
                {
                    "match_id": "5001",
                    "status": "wk_too_harsh",
                    "context": {"opponent_quality": "top6", "venue": "home", "competition_stage": "league_early", "result": "W", "xg_present": True},
                    "features": {"result": "W", "opponent_quality": "top6", "opponent_name": "Chelsea", "competition": "Premier League"},
                    "differences": ["overall"],
                    "wk": {"overall_signal": "🟡", "dimension_signals": {}, "model_signals": {}},
                    "b": {"overall_signal": "🟢", "dimension_signals": {}, "model_signals": {}},
                },
                # Second row — same pattern for diversity gate
                {
                    "match_id": "5002",
                    "status": "wk_too_harsh",
                    "context": {"opponent_quality": "top6", "venue": "away", "competition_stage": "league_early", "result": "W", "xg_present": True},
                    "features": {"result": "W", "opponent_quality": "top6", "opponent_name": "Liverpool", "competition": "Premier League"},
                    "differences": ["overall"],
                    "wk": {"overall_signal": "🟡", "dimension_signals": {}, "model_signals": {}},
                    "b": {"overall_signal": "🟢", "dimension_signals": {}, "model_signals": {}},
                },
            ],
        }
        adj_path = tmp_path / "adj_report.json"
        adj_path.write_text(json.dumps(adj_report))
        output_json = tmp_path / "rule_candidates.json"

        rc, stdout, stderr = _run_self_iterate([
            "mine-rules",
            "--adjudication", str(adj_path),
            "--output", str(output_json),
        ])
        assert rc == 0, f"stderr: {stderr}"
        result = json.loads(stdout)
        assert result["ok"] is True
        assert "summary" in result
        assert result["summary"]["disagreement_rows"] == 2


class TestCliDecideExperiment:
    """decide-experiment CLI writes a decision artifact."""

    def test_decide_experiment_cli_writes_decision(self, tmp_path):
        baseline_adj = tmp_path / "baseline_adjudication.json"
        candidate_adj = tmp_path / "candidate_adjudication.json"
        comparison = tmp_path / "comparison.json"
        ingest = tmp_path / "ingest.json"
        output = tmp_path / "experiment_decision.json"

        baseline_adj.write_text(json.dumps({"summary": {"compared": 94}, "rows": []}))
        candidate_adj.write_text(json.dumps({"summary": {"compared": 94}, "rows": []}))
        comparison.write_text(json.dumps({
            "clean_subset": {
                "b001": {
                    "overall_agreement_rate": 0.6,
                    "dimension_agreement_rate": 0.3,
                    "model_agreement_rate": 0.2,
                    "wk_too_harsh": 20,
                    "wk_too_generous": 1,
                    "dimension_level_disagreement": 30,
                    "model_level_disagreement": 10,
                    "compared": 94,
                },
                "b002": {
                    "overall_agreement_rate": 0.7,
                    "dimension_agreement_rate": 0.4,
                    "model_agreement_rate": 0.3,
                    "wk_too_harsh": 10,
                    "wk_too_generous": 2,
                    "dimension_level_disagreement": 20,
                    "model_level_disagreement": 8,
                    "compared": 94,
                },
                "delta": {
                    "overall_agreement_rate": 0.1,
                    "dimension_agreement_rate": 0.1,
                    "model_agreement_rate": 0.1,
                    "wk_too_harsh": -10,
                    "wk_too_generous": 1,
                    "dimension_level_disagreement": -10,
                    "model_level_disagreement": -2,
                },
                "criteria_met": 5,
                "criteria_total": 5,
                "same_denominator": True,
                "effective": True,
            }
        }))
        ingest.write_text(json.dumps({
            "summary": {"total_results": 94, "applied": 94, "skipped": 0, "errors": 0}
        }))

        rc, stdout, stderr = _run_self_iterate([
            "decide-experiment",
            "--baseline-run-id", "b-001",
            "--candidate-run-id", "b-003",
            "--baseline-adjudication", str(baseline_adj),
            "--candidate-adjudication", str(candidate_adj),
            "--comparison", str(comparison),
            "--ingest-report", str(ingest),
            "--output", str(output),
        ])

        assert rc == 0, f"stderr: {stderr}"
        result = json.loads(stdout)
        assert result["ok"] is True
        assert result["decision"] == "promote"
        artifact = json.loads(output.read_text())
        assert artifact["decision"] == "promote"
