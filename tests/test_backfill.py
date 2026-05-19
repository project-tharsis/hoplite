"""Tests for backfill_history.py — inventory, prepare-seed, apply-features, validate-rest modes."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.backfill_history import run_inventory, run_prepare_seed, run_apply_features, run_validate_rest


# ── Fixtures ────────────────────────────────────────────────────────


def _raw_match_json(fixture_id: int = 123456) -> dict:
    """Minimal raw match JSON accepted by prepare_evaluation."""
    return {
        "fixture_id": fixture_id,
        "date": "2025-05-01T15:00:00",
        "competition": "Premier League",
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "home_score": 3,
        "away_score": 1,
        "home_stats": {
            "Ball Possession": "60%",
            "Total Shots": 15,
            "Shots on Goal": 6,
            "Passes %": "85%",
            "Corner Kicks": 7,
            "Fouls": 8,
        },
        "away_stats": {
            "Ball Possession": "40%",
            "Total Shots": 8,
            "Shots on Goal": 3,
            "Passes %": "78%",
            "Corner Kicks": 2,
            "Fouls": 12,
        },
        "events": [
            {"minute": 20, "type": "Goal", "team": "home", "player": "Saka", "detail": "Normal Goal"},
            {"minute": 55, "type": "Goal", "team": "home", "player": "Havertz", "detail": "Normal Goal"},
            {"minute": 70, "type": "Goal", "team": "away", "player": "Palmer", "detail": "Normal Goal"},
            {"minute": 85, "type": "Goal", "team": "home", "player": "Rice", "detail": "Normal Goal"},
        ],
    }


def _report_json(fixture_id: int = 654321) -> dict:
    """Analyze report JSON accepted by prepare_evaluation."""
    return {
        "ok": True,
        "report": {
            "match": {
                "fixture_id": fixture_id,
                "date": "2025-03-15T15:00:00",
                "competition": "Premier League",
                "home_team": "Arsenal",
                "away_team": "Man United",
                "home_score": 2,
                "away_score": 0,
                "arsenal_score": 2,
                "opponent_score": 0,
                "result": "W",
            },
            "predicted_plan": {},
            "context": {
                "opponent": "Man United",
                "opponent_quality": "top6",
                "venue": "home",
                "competition_stage": "league_late",
            },
            "stats": {
                "score": {"arsenal": 2, "opponent": 0},
                "xg": {"arsenal": None, "opponent": None},
                "possession": {"arsenal": "55%", "opponent": "45%"},
                "shots": {"arsenal": 12, "opponent": 6},
                "shots_on_target": {"arsenal": 5, "opponent": 2},
                "passes": {"arsenal": {"total": None, "accuracy": "86%"}, "opponent": {"total": None, "accuracy": "80%"}},
                "fouls": {"arsenal": 10, "opponent": 13},
                "corners": {"arsenal": 6, "opponent": 3},
                "goals": {"arsenal": {"total": 2}, "opponent": {"total": 0}},
                "cards": {"arsenal": {"yellow": 1, "red": 0}, "opponent": {"yellow": 2, "red": 0}},
            },
            "key_events": [
                {"minute": 30, "type": "goal", "raw_type": "Goal", "team": "Arsenal", "player": "Saka", "detail": "Normal Goal", "is_arsenal": True},
                {"minute": 78, "type": "goal", "raw_type": "Goal", "team": "Arsenal", "player": "Havertz", "detail": "Normal Goal", "is_arsenal": True},
            ],
            "set_pieces": {"arsenal": 0, "opponent": 0, "details": []},
            "sub_impact": [],
            "one_line_summary": "Arsenal 2-0 Man United (Premier League)",
        },
        "search_queries": [],
    }


def _legacy_entry(match_id: str, opponent: str = "Chelsea") -> dict:
    """Minimal legacy KB entry."""
    return {
        "match_id": match_id,
        "timestamp": "2025-05-01T00:00:00",
        "opponent": opponent,
        "score": "3-1",
        "result": "W",
        "competition": "Premier League",
        "pre_match_context": {},
        "predicted_plan": {},
        "evaluation": {
            "execution_signal": "🟡",
            "adjustment_signal": "🟡",
            "satisfaction_signal": "🟡",
            "model_signals": {},
        },
    }


def _feature_backed_entry(match_id: str, opponent: str = "Bournemouth") -> dict:
    """KB entry that already has features and weak_labels."""
    return {
        **_legacy_entry(match_id, opponent),
        "features": {"result": "W", "score_margin": 1, "arsenal_goals": 3, "opponent_goals": 2},
        "weak_labels": {"overall_signal": "🟢", "model_signals": {}, "dimension_signals": {}},
    }


def _write_kb(path: Path, entries: list[dict]) -> str:
    """Write KB entries to a temp file, return path string."""
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def _write_manifest(path: Path, seed_set: list[dict], validation_set: list[dict] | None = None) -> str:
    """Write manifest to a temp file, return path string."""
    data = {
        "version": "v1",
        "seed_set": seed_set,
        "validation_set": validation_set or [],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


# ── Test 1: Inventory reports current KB counts correctly ───────────


class TestInventoryCounts:

    def test_counts_legacy_and_feature_backed(self, tmp_path):
        """Inventory correctly counts total, features, weak_labels, legacy-only."""
        entries = [
            _legacy_entry("1"),
            _legacy_entry("2"),
            _feature_backed_entry("3"),
        ]
        kb_path = _write_kb(tmp_path / "kb.json", entries)
        manifest_path = _write_manifest(tmp_path / "manifest.json", [], [])

        report = run_inventory(kb_path, manifest_path)

        assert report["kb"]["total_entries"] == 3
        assert report["kb"]["entries_with_features"] == 1
        assert report["kb"]["entries_with_weak_labels"] == 1
        assert report["kb"]["legacy_only_entries"] == 2

    def test_counts_manifest_sets(self, tmp_path):
        """Inventory counts seed_set and validation_set separately."""
        entries = [_legacy_entry("1"), _legacy_entry("2")]
        kb_path = _write_kb(tmp_path / "kb.json", entries)
        manifest_path = _write_manifest(
            tmp_path / "manifest.json",
            seed_set=[{"legacy_match_id": "1", "fixture_id": 111, "raw_match_path": "/tmp/x.json"}],
            validation_set=[{"legacy_match_id": "2", "fixture_id": 222}],
        )

        report = run_inventory(kb_path, manifest_path)

        assert report["manifest"]["seed_set_count"] == 1
        assert report["manifest"]["validation_set_count"] == 1


# ── Test 2: Inventory flags manifest IDs missing from KB ────────────


class TestInventoryMissingIDs:

    def test_flags_ids_not_in_kb(self, tmp_path):
        """Manifest IDs not present in KB are flagged."""
        entries = [_legacy_entry("1")]
        kb_path = _write_kb(tmp_path / "kb.json", entries)
        manifest_path = _write_manifest(
            tmp_path / "manifest.json",
            seed_set=[{"legacy_match_id": "1", "fixture_id": 111, "raw_match_path": "/tmp/x.json"}],
            validation_set=[{"legacy_match_id": "999", "fixture_id": 999}],
        )

        report = run_inventory(kb_path, manifest_path)

        assert "999" in report["issues"]["manifest_ids_not_in_kb"]
        assert "1" not in report["issues"]["manifest_ids_not_in_kb"]

    def test_empty_manifest_clean(self, tmp_path):
        """Empty manifest → no issues."""
        entries = [_legacy_entry("1")]
        kb_path = _write_kb(tmp_path / "kb.json", entries)
        manifest_path = _write_manifest(tmp_path / "manifest.json", [], [])

        report = run_inventory(kb_path, manifest_path)

        assert report["issues"]["manifest_ids_not_in_kb"] == []


# ── Test 3: Inventory flags seed rows without input ─────────────────


class TestInventoryMissingInput:

    def test_flags_seed_without_raw_or_report(self, tmp_path):
        """Seed row with only fixture_id (no raw/report path) flagged as missing input."""
        entries = [_legacy_entry("1")]
        kb_path = _write_kb(tmp_path / "kb.json", entries)
        manifest_path = _write_manifest(
            tmp_path / "manifest.json",
            seed_set=[{"legacy_match_id": "1", "fixture_id": 111}],
        )

        report = run_inventory(kb_path, manifest_path)

        assert len(report["issues"]["seed_entries_missing_input"]) == 1
        assert report["issues"]["seed_entries_missing_input"][0]["error_code"] == "MISSING_RAW_INPUT"

    def test_seed_with_raw_path_not_flagged(self, tmp_path):
        """Seed row with raw_match_path is not flagged."""
        entries = [_legacy_entry("1")]
        kb_path = _write_kb(tmp_path / "kb.json", entries)
        manifest_path = _write_manifest(
            tmp_path / "manifest.json",
            seed_set=[{"legacy_match_id": "1", "fixture_id": 111, "raw_match_path": "/tmp/raw.json"}],
        )

        report = run_inventory(kb_path, manifest_path)

        assert report["issues"]["seed_entries_missing_input"] == []

    def test_seed_with_report_path_not_flagged(self, tmp_path):
        """Seed row with report_path is not flagged."""
        entries = [_legacy_entry("1")]
        kb_path = _write_kb(tmp_path / "kb.json", entries)
        manifest_path = _write_manifest(
            tmp_path / "manifest.json",
            seed_set=[{"legacy_match_id": "1", "fixture_id": 111, "report_path": "/tmp/report.json"}],
        )

        report = run_inventory(kb_path, manifest_path)

        assert report["issues"]["seed_entries_missing_input"] == []


# ── Test 4: prepare-seed processes local raw match JSON ─────────────


class TestPrepareSeedRawMatch:

    def test_processes_raw_match(self, tmp_path):
        """prepare-seed processes a local raw match JSON file."""
        raw_path = tmp_path / "raw" / "123456.json"
        raw_path.parent.mkdir(parents=True)
        raw_path.write_text(json.dumps(_raw_match_json()), encoding="utf-8")

        entries = [_legacy_entry("1")]
        kb_path = _write_kb(tmp_path / "kb.json", entries)
        manifest_path = _write_manifest(
            tmp_path / "manifest.json",
            seed_set=[{
                "legacy_match_id": "1",
                "fixture_id": 123456,
                "opponent": "Chelsea",
                "date": "2025-05-01",
                "raw_match_path": str(raw_path),
            }],
        )
        output_dir = tmp_path / "run"

        result = run_prepare_seed(kb_path, manifest_path, str(output_dir))

        assert result["summary"]["ok"] == 1
        assert result["summary"]["errors"] == 0

        # Check prepare_results.jsonl
        prepare_path = Path(result["prepare_results_path"])
        assert prepare_path.exists()
        with open(prepare_path, encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        assert len(rows) == 1
        assert rows[0]["ok"] is True
        assert rows[0]["input_type"] == "raw_match"
        assert "features" in rows[0]
        assert "weak_labels" in rows[0]
        assert rows[0]["features"]["result"] == "W"


# ── Test 5: prepare-seed processes local analyze report JSON ────────


class TestPrepareSeedReport:

    def test_processes_report_json(self, tmp_path):
        """prepare-seed processes a local analyze report JSON file."""
        report_path = tmp_path / "reports" / "654321.json"
        report_path.parent.mkdir(parents=True)
        report_path.write_text(json.dumps(_report_json()), encoding="utf-8")

        entries = [_legacy_entry("1")]
        kb_path = _write_kb(tmp_path / "kb.json", entries)
        manifest_path = _write_manifest(
            tmp_path / "manifest.json",
            seed_set=[{
                "legacy_match_id": "1",
                "fixture_id": 654321,
                "opponent": "Chelsea",
                "date": "2025-05-01",
                "report_path": str(report_path),
            }],
        )
        output_dir = tmp_path / "run"

        result = run_prepare_seed(kb_path, manifest_path, str(output_dir))

        assert result["summary"]["ok"] == 1
        assert result["summary"]["errors"] == 0

        # Check output
        prepare_path = Path(result["prepare_results_path"])
        with open(prepare_path, encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        assert rows[0]["ok"] is True
        assert rows[0]["input_type"] == "report"
        assert rows[0]["features"]["result"] == "W"


# ── Test 6: prepare-seed writes llm_jobs.jsonl ──────────────────────


class TestLlmJobs:

    def test_writes_llm_jobs(self, tmp_path):
        """prepare-seed writes llm_jobs.jsonl with prompt, features, weak_labels."""
        raw_path = tmp_path / "raw" / "123456.json"
        raw_path.parent.mkdir(parents=True)
        raw_path.write_text(json.dumps(_raw_match_json()), encoding="utf-8")

        entries = [_legacy_entry("1")]
        kb_path = _write_kb(tmp_path / "kb.json", entries)
        manifest_path = _write_manifest(
            tmp_path / "manifest.json",
            seed_set=[{
                "legacy_match_id": "1",
                "fixture_id": 123456,
                "opponent": "Chelsea",
                "date": "2025-05-01",
                "raw_match_path": str(raw_path),
            }],
        )
        output_dir = tmp_path / "run"

        result = run_prepare_seed(kb_path, manifest_path, str(output_dir))

        llm_path = Path(result["llm_jobs_path"])
        assert llm_path.exists()
        with open(llm_path, encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        assert len(rows) == 1
        job = rows[0]
        assert job["legacy_match_id"] == "1"
        assert job["fixture_id"] == "123456"
        assert job["opponent"] == "Chelsea"
        assert job["date"] == "2025-05-01"
        assert "prompt" in job and len(job["prompt"]) > 0
        assert "features" in job and job["features"]["result"] == "W"
        assert "weak_labels" in job
        assert job["expected_output_schema"] == "strict_v2_evaluation"


# ── Test 7: Dry-run modes do not mutate knowledge.json ──────────────


class TestDryRunSafety:

    def test_inventory_does_not_mutate_kb(self, tmp_path):
        """inventory mode does not modify knowledge.json."""
        entries = [_legacy_entry("1"), _legacy_entry("2")]
        kb_path = _write_kb(tmp_path / "kb.json", entries)
        before = (tmp_path / "kb.json").read_text(encoding="utf-8")
        manifest_path = _write_manifest(
            tmp_path / "manifest.json",
            seed_set=[{"legacy_match_id": "1", "fixture_id": 111, "raw_match_path": "/tmp/x.json"}],
        )

        run_inventory(kb_path, manifest_path)

        after = (tmp_path / "kb.json").read_text(encoding="utf-8")
        assert before == after

    def test_prepare_seed_does_not_mutate_kb(self, tmp_path):
        """prepare-seed mode (dry-run) does not modify knowledge.json."""
        raw_path = tmp_path / "raw" / "123456.json"
        raw_path.parent.mkdir(parents=True)
        raw_path.write_text(json.dumps(_raw_match_json()), encoding="utf-8")

        entries = [_legacy_entry("1")]
        kb_path = _write_kb(tmp_path / "kb.json", entries)
        before = (tmp_path / "kb.json").read_text(encoding="utf-8")
        manifest_path = _write_manifest(
            tmp_path / "manifest.json",
            seed_set=[{
                "legacy_match_id": "1",
                "fixture_id": 123456,
                "opponent": "Chelsea",
                "date": "2025-05-01",
                "raw_match_path": str(raw_path),
            }],
        )
        output_dir = tmp_path / "run"

        run_prepare_seed(kb_path, manifest_path, str(output_dir), dry_run=True)

        after = (tmp_path / "kb.json").read_text(encoding="utf-8")
        assert before == after


# ── Test 8: Missing raw/report file creates structured error ────────


class TestMissingFileErrors:

    def test_missing_raw_file(self, tmp_path):
        """Non-existent raw_match_path → RAW_FILE_NOT_FOUND error row."""
        entries = [_legacy_entry("1")]
        kb_path = _write_kb(tmp_path / "kb.json", entries)
        manifest_path = _write_manifest(
            tmp_path / "manifest.json",
            seed_set=[{
                "legacy_match_id": "1",
                "fixture_id": 123456,
                "raw_match_path": "/nonexistent/raw.json",
            }],
        )
        output_dir = tmp_path / "run"

        result = run_prepare_seed(kb_path, manifest_path, str(output_dir))

        assert result["summary"]["errors"] == 1
        prepare_path = Path(result["prepare_results_path"])
        with open(prepare_path, encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        assert rows[0]["ok"] is False
        assert rows[0]["error"]["code"] == "RAW_FILE_NOT_FOUND"

    def test_missing_report_file(self, tmp_path):
        """Non-existent report_path → REPORT_FILE_NOT_FOUND error row."""
        entries = [_legacy_entry("1")]
        kb_path = _write_kb(tmp_path / "kb.json", entries)
        manifest_path = _write_manifest(
            tmp_path / "manifest.json",
            seed_set=[{
                "legacy_match_id": "1",
                "fixture_id": 654321,
                "report_path": "/nonexistent/report.json",
            }],
        )
        output_dir = tmp_path / "run"

        result = run_prepare_seed(kb_path, manifest_path, str(output_dir))

        assert result["summary"]["errors"] == 1
        prepare_path = Path(result["prepare_results_path"])
        with open(prepare_path, encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        assert rows[0]["ok"] is False
        assert rows[0]["error"]["code"] == "REPORT_FILE_NOT_FOUND"

    def test_no_input_at_all(self, tmp_path):
        """Seed row with no raw/report → MISSING_RAW_INPUT error row."""
        entries = [_legacy_entry("1")]
        kb_path = _write_kb(tmp_path / "kb.json", entries)
        manifest_path = _write_manifest(
            tmp_path / "manifest.json",
            seed_set=[{"legacy_match_id": "1", "fixture_id": 111}],
        )
        output_dir = tmp_path / "run"

        result = run_prepare_seed(kb_path, manifest_path, str(output_dir))

        assert result["summary"]["errors"] == 1
        prepare_path = Path(result["prepare_results_path"])
        with open(prepare_path, encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        assert rows[0]["ok"] is False
        assert rows[0]["error"]["code"] == "MISSING_RAW_INPUT"

    def test_legacy_id_not_in_kb(self, tmp_path):
        """Seed row referencing non-existent KB entry → LEGACY_ENTRY_NOT_FOUND."""
        entries = [_legacy_entry("1")]
        kb_path = _write_kb(tmp_path / "kb.json", entries)
        manifest_path = _write_manifest(
            tmp_path / "manifest.json",
            seed_set=[{"legacy_match_id": "999", "fixture_id": 111, "raw_match_path": "/tmp/x.json"}],
        )
        output_dir = tmp_path / "run"

        result = run_prepare_seed(kb_path, manifest_path, str(output_dir))

        assert result["summary"]["errors"] == 1
        prepare_path = Path(result["prepare_results_path"])
        with open(prepare_path, encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        assert rows[0]["ok"] is False
        assert rows[0]["error"]["code"] == "LEGACY_ENTRY_NOT_FOUND"


# ── Apply-features helpers ─────────────────────────────────────────


def _sample_features() -> dict:
    """Sample features dict as returned by prepare_evaluation."""
    return {
        "result": "W",
        "score_margin": 2,
        "arsenal_goals": 3,
        "opponent_goals": 1,
        "opponent_name": "Chelsea",
        "venue": "home",
        "opponent_quality": "top6",
        "possession_pct": 60,
        "shots_total": 15,
        "shots_on_target": 6,
        "xg_arsenal": None,
        "xg_opponent": None,
        "corners": 7,
        "cards_yellow_arsenal": 1,
        "cards_yellow_opponent": 2,
        "cards_red_arsenal": 0,
        "cards_red_opponent": 0,
        "sub_impact_score": 0,
    }


def _sample_weak_labels() -> dict:
    """Sample weak_labels dict as returned by prepare_evaluation."""
    return {
        "model_signals": {"M1": "🟢", "M2": "🟡", "M3": "🟢"},
        "dimension_signals": {"execution": "🟢", "adjustment": "🟡", "satisfaction": "🟢"},
        "overall_signal": "🟢",
        "confidence": 0.8,
        "evidence_refs": [],
        "missing_data_penalty": 0,
        "weak_label_version": "v1",
    }


def _write_prepare_results(run_dir: Path, rows: list[dict]) -> Path:
    """Write prepare_results.jsonl to a run directory."""
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "prepare_results.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def _successful_prepare_row(legacy_match_id: str = "1", fixture_id: str = "123456") -> dict:
    """A successful prepare_results.jsonl row."""
    return {
        "legacy_match_id": legacy_match_id,
        "fixture_id": fixture_id,
        "ok": True,
        "input_type": "raw_match",
        "features": _sample_features(),
        "weak_labels": _sample_weak_labels(),
        "rubric_version": "arteta_v1",
        "prompt": "test prompt",
        "raw_match_path": f"data/backfill/raw/{fixture_id}.json",
        "report_path": "",
    }


def _legacy_entry_with_extra(match_id: str) -> dict:
    """Legacy KB entry with an extra unknown field."""
    entry = _legacy_entry(match_id)
    entry["custom_tag"] = "seed_v1"
    entry["notes"] = "top6 home win seed case"
    return entry


# ── Test 9: apply-features --write adds features, weak_labels, versions, backfill ──


class TestApplyFeaturesAddsFields:

    def test_apply_features_write(self, tmp_path):
        """apply-features --write adds features, weak_labels, versions, and backfill metadata."""
        entries = [_legacy_entry("1")]
        kb_path = _write_kb(tmp_path / "kb.json", entries)
        manifest_path = _write_manifest(
            tmp_path / "manifest.json",
            seed_set=[{
                "legacy_match_id": "1",
                "fixture_id": 123456,
                "opponent": "Chelsea",
                "date": "2025-05-01",
                "raw_match_path": "/tmp/raw.json",
            }],
        )
        run_dir = tmp_path / "run"
        _write_prepare_results(run_dir, [_successful_prepare_row("1", "123456")])

        result = run_apply_features(
            kb_path, manifest_path, str(run_dir),
            force=False, dry_run=False,
        )

        assert result["report"]["summary"]["applied"] == 1
        assert result["report"]["summary"]["skipped"] == 0
        assert result["dry_run"] is False

        # Read mutated KB
        with open(kb_path, encoding="utf-8") as f:
            kb = json.load(f)
        entry = kb[0]
        assert entry["features"] == _sample_features()
        assert entry["weak_labels"] == _sample_weak_labels()
        assert entry["features_version"] == "v1"
        assert entry["weak_label_version"] == "v1"
        assert entry["rubric_version"] == "arteta_v1"
        assert entry["prompt_builder_version"] == "v1"
        assert entry["backfill"]["status"] == "feature_backfilled"
        assert entry["backfill"]["run_id"] == run_dir.name
        assert entry["backfill"]["legacy_match_id"] == "1"
        assert entry["backfill"]["fixture_id"] == "123456"
        assert entry["backfill"]["needs_v2_evaluation"] is True

        # Verify snapshot files
        assert (run_dir / "knowledge.before.json").exists()
        assert (run_dir / "knowledge.after.json").exists()
        assert (run_dir / "apply_report.json").exists()


# ── Test 10: apply-features preserves unknown legacy fields ────────


class TestApplyFeaturesPreservesFields:

    def test_preserves_unknown_fields(self, tmp_path):
        """apply-features --write preserves unknown legacy fields."""
        entries = [_legacy_entry_with_extra("1")]
        kb_path = _write_kb(tmp_path / "kb.json", entries)
        manifest_path = _write_manifest(
            tmp_path / "manifest.json",
            seed_set=[{
                "legacy_match_id": "1",
                "fixture_id": 123456,
                "raw_match_path": "/tmp/raw.json",
            }],
        )
        run_dir = tmp_path / "run"
        _write_prepare_results(run_dir, [_successful_prepare_row("1", "123456")])

        run_apply_features(kb_path, manifest_path, str(run_dir), dry_run=False)

        with open(kb_path, encoding="utf-8") as f:
            kb = json.load(f)
        entry = kb[0]
        assert entry["custom_tag"] == "seed_v1"
        assert entry["notes"] == "top6 home win seed case"
        assert entry["pre_match_context"] == {}
        assert entry["predicted_plan"] == {}


# ── Test 11: apply-features copies original evaluation into legacy_evaluation ──


class TestApplyFeaturesLegacyEvaluation:

    def test_copies_original_to_legacy_evaluation(self, tmp_path):
        """apply-features --write copies original evaluation into legacy_evaluation before normalizing."""
        entry = _legacy_entry("1")
        entries = [entry]
        kb_path = _write_kb(tmp_path / "kb.json", entries)
        manifest_path = _write_manifest(
            tmp_path / "manifest.json",
            seed_set=[{
                "legacy_match_id": "1",
                "fixture_id": 123456,
                "raw_match_path": "/tmp/raw.json",
            }],
        )
        run_dir = tmp_path / "run"
        _write_prepare_results(run_dir, [_successful_prepare_row("1", "123456")])

        run_apply_features(kb_path, manifest_path, str(run_dir), dry_run=False)

        with open(kb_path, encoding="utf-8") as f:
            kb = json.load(f)
        e = kb[0]
        # legacy_evaluation should have original fields
        assert "legacy_evaluation" in e
        assert e["legacy_evaluation"]["execution_signal"] == "🟡"
        assert e["legacy_evaluation"]["adjustment_signal"] == "🟡"
        assert e["legacy_evaluation"]["satisfaction_signal"] == "🟡"
        assert e["legacy_evaluation"]["model_signals"] == {}


# ── Test 12: apply-features normalizes legacy dimension signals ─────


class TestApplyFeaturesNormalizesEvaluation:

    def test_normalizes_dimension_signals(self, tmp_path):
        """apply-features --write normalizes legacy dimension signals."""
        entry = _legacy_entry("1")
        entry["evaluation"]["execution_signal"] = "🟢"
        entry["evaluation"]["adjustment_signal"] = "🟢"
        entry["evaluation"]["satisfaction_signal"] = "🔴"
        entries = [entry]
        kb_path = _write_kb(tmp_path / "kb.json", entries)
        manifest_path = _write_manifest(
            tmp_path / "manifest.json",
            seed_set=[{
                "legacy_match_id": "1",
                "fixture_id": 123456,
                "raw_match_path": "/tmp/raw.json",
            }],
        )
        run_dir = tmp_path / "run"
        _write_prepare_results(run_dir, [_successful_prepare_row("1", "123456")])

        run_apply_features(kb_path, manifest_path, str(run_dir), dry_run=False)

        with open(kb_path, encoding="utf-8") as f:
            kb = json.load(f)
        e = kb[0]
        assert e["evaluation"]["source"] == "legacy"
        assert e["evaluation"]["dimension_signals"] == {
            "execution": "🟢",
            "adjustment": "🟢",
            "satisfaction": "🔴",
        }
        # 2 green → overall green
        assert e["evaluation"]["overall_signal"] == "🟢"
        assert e["evaluation"]["narrative"] == ""

    def test_all_red_overall_red(self, tmp_path):
        """3 red dimension signals → overall 🔴."""
        entry = _legacy_entry("1")
        entry["evaluation"]["execution_signal"] = "🔴"
        entry["evaluation"]["adjustment_signal"] = "🔴"
        entry["evaluation"]["satisfaction_signal"] = "🟡"
        entries = [entry]
        kb_path = _write_kb(tmp_path / "kb.json", entries)
        manifest_path = _write_manifest(
            tmp_path / "manifest.json",
            seed_set=[{
                "legacy_match_id": "1",
                "fixture_id": 123456,
                "raw_match_path": "/tmp/raw.json",
            }],
        )
        run_dir = tmp_path / "run"
        _write_prepare_results(run_dir, [_successful_prepare_row("1", "123456")])

        run_apply_features(kb_path, manifest_path, str(run_dir), dry_run=False)

        with open(kb_path, encoding="utf-8") as f:
            kb = json.load(f)
        assert kb[0]["evaluation"]["overall_signal"] == "🔴"


# ── Test 13: Re-running apply-features is idempotent ────────────────


class TestApplyFeaturesIdempotent:

    def test_idempotent(self, tmp_path):
        """Re-running apply-features --write is idempotent."""
        entries = [_legacy_entry("1")]
        kb_path = _write_kb(tmp_path / "kb.json", entries)
        manifest_path = _write_manifest(
            tmp_path / "manifest.json",
            seed_set=[{
                "legacy_match_id": "1",
                "fixture_id": 123456,
                "raw_match_path": "/tmp/raw.json",
            }],
        )
        run_dir = tmp_path / "run"
        _write_prepare_results(run_dir, [_successful_prepare_row("1", "123456")])

        # First run
        run_apply_features(kb_path, manifest_path, str(run_dir), dry_run=False)
        with open(kb_path, encoding="utf-8") as f:
            first = json.load(f)

        # Second run — should skip
        result2 = run_apply_features(kb_path, manifest_path, str(run_dir), dry_run=False)
        assert result2["report"]["summary"]["applied"] == 0
        assert result2["report"]["summary"]["skipped"] == 1

        with open(kb_path, encoding="utf-8") as f:
            second = json.load(f)
        assert first == second


# ── Test 14: validate-rest writes report, does not mutate KB ────────


class TestValidateRest:

    def test_validate_rest_no_mutation(self, tmp_path):
        """validate-rest writes a report and does not mutate KB."""
        raw_path = tmp_path / "raw" / "999999.json"
        raw_path.parent.mkdir(parents=True)
        raw_path.write_text(json.dumps(_raw_match_json(999999)), encoding="utf-8")

        entries = [_legacy_entry("31")]
        kb_path = _write_kb(tmp_path / "kb.json", entries)
        before = (tmp_path / "kb.json").read_text(encoding="utf-8")
        manifest_path = _write_manifest(
            tmp_path / "manifest.json",
            seed_set=[],
            validation_set=[{
                "legacy_match_id": "31",
                "fixture_id": 999999,
                "raw_match_path": str(raw_path),
            }],
        )
        output_dir = tmp_path / "validate_run"

        result = run_validate_rest(kb_path, manifest_path, str(output_dir))

        # KB not mutated
        after = (tmp_path / "kb.json").read_text(encoding="utf-8")
        assert before == after

        # Report written
        assert (output_dir / "validation_report.json").exists()
        report = result["report"]
        assert report["summary"]["total"] == 1
        assert report["summary"]["compared"] + report["summary"]["skipped"] == 1

    def test_validate_rest_skips_missing_input(self, tmp_path):
        """validate-rest skips validation entries with no raw/report."""
        entries = [_legacy_entry("31")]
        kb_path = _write_kb(tmp_path / "kb.json", entries)
        manifest_path = _write_manifest(
            tmp_path / "manifest.json",
            seed_set=[],
            validation_set=[{"legacy_match_id": "31", "fixture_id": 789}],
        )
        output_dir = tmp_path / "validate_run"

        result = run_validate_rest(kb_path, manifest_path, str(output_dir))

        assert result["report"]["summary"]["compared"] == 0
        assert result["report"]["summary"]["skipped"] == 1
        assert result["report"]["skipped"][0]["reason"] == "MISSING_RAW_INPUT"


# ── Test 15: --force allows replacing existing backfilled features ──


class TestForceReplace:

    def test_force_replaces_backfilled_features(self, tmp_path):
        """--force allows replacing existing backfilled features."""
        # Create entry that already has features/weak_labels
        entry = _feature_backed_entry("1")
        entries = [entry]
        kb_path = _write_kb(tmp_path / "kb.json", entries)
        manifest_path = _write_manifest(
            tmp_path / "manifest.json",
            seed_set=[{
                "legacy_match_id": "1",
                "fixture_id": 123456,
                "raw_match_path": "/tmp/raw.json",
            }],
        )
        run_dir = tmp_path / "run"
        _write_prepare_results(run_dir, [_successful_prepare_row("1", "123456")])

        # Without force — should skip
        result_no_force = run_apply_features(
            kb_path, manifest_path, str(run_dir), force=False, dry_run=False,
        )
        assert result_no_force["report"]["summary"]["skipped"] == 1
        assert result_no_force["report"]["summary"]["applied"] == 0

        # With force — should replace
        result_force = run_apply_features(
            kb_path, manifest_path, str(run_dir), force=True, dry_run=False,
        )
        assert result_force["report"]["summary"]["applied"] == 1
        assert result_force["report"]["summary"]["skipped"] == 0

        with open(kb_path, encoding="utf-8") as f:
            kb = json.load(f)
        assert kb[0]["features"] == _sample_features()
        assert kb[0]["backfill"]["status"] == "feature_backfilled"


# ── Test 16: Manifest row with only fixture_id fails MISSING_RAW_INPUT ──


class TestFixtureIdOnlyRow:

    def test_prepare_seed_fixture_id_only_fails(self, tmp_path):
        """Manifest row with only fixture_id (no raw/report) fails with MISSING_RAW_INPUT."""
        entries = [_legacy_entry("1")]
        kb_path = _write_kb(tmp_path / "kb.json", entries)
        manifest_path = _write_manifest(
            tmp_path / "manifest.json",
            seed_set=[{"legacy_match_id": "1", "fixture_id": 123456}],
        )
        output_dir = tmp_path / "run"

        result = run_prepare_seed(kb_path, manifest_path, str(output_dir))

        assert result["summary"]["errors"] == 1
        assert result["summary"]["ok"] == 0
        prepare_path = Path(result["prepare_results_path"])
        with open(prepare_path, encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        assert rows[0]["ok"] is False
        assert rows[0]["error"]["code"] == "MISSING_RAW_INPUT"
