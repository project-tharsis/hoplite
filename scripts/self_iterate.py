#!/usr/bin/env python3
"""Low-touch self-iteration pipeline.

Modes:
    make-jobs            Generate evaluation jobs for missing/stale evaluator B entries.
    ingest-results       Write evaluator B strict v2 results into KB.
    promote-blind-spots  Promote prompt_blind_spot candidates to rubric JSON.

Usage:
    python scripts/self_iterate.py make-jobs \\
        --kb data/knowledge.json \\
        --reports-root data/backfill/runs \\
        --only missing-evaluation \\
        --evaluator-id B \\
        --run-id b-001 \\
        --output data/self_iteration/runs/b-001

    python scripts/self_iterate.py ingest-results \\
        --kb data/knowledge.json \\
        --run data/self_iteration/runs/b-001 \\
        --input data/self_iteration/runs/b-001/llm_results.jsonl \\
        --write

    python scripts/self_iterate.py promote-blind-spots \\
        --candidates data/self_iteration/runs/b-001/rule_candidates.json \\
        --output rubrics/arteta_blind_spots.json \\
        --write
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.evaluation.llm_result import validate_llm_result


# ── Helpers ────────────────────────────────────────────────────────


def _load_kb(kb_path: str) -> list[dict]:
    with open(kb_path, encoding="utf-8") as f:
        return json.load(f)


def _build_kb_index(entries: list[dict]) -> dict[str, dict]:
    """Index KB entries by match_id."""
    idx: dict[str, dict] = {}
    for e in entries:
        mid = str(e.get("match_id", ""))
        idx[mid] = e
    return idx


def _atomic_write_kb(kb_path: str, entries: list[dict]) -> None:
    """Write KB atomically via temp file + rename."""
    p = Path(kb_path)
    fd, tmp_name = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
        Path(tmp_name).replace(p)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _prompt_hash(prompt: str) -> str:
    return "sha256:" + hashlib.sha256(prompt.encode()).hexdigest()


def _is_feature_backed(entry: dict) -> bool:
    """Entry has features and weak_labels."""
    return bool(entry.get("features")) and bool(entry.get("weak_labels"))


# ── Report lookup (§6.1.1) ─────────────────────────────────────────


def _find_report(
    entry: dict,
    reports_root: str,
) -> tuple[str | None, list[str]]:
    """Find report for an entry using priority-based lookup.

    Returns (report_path_or_None, list_of_all_candidates).
    """
    match_id = str(entry.get("match_id", ""))
    fixture_id = str(entry.get("backfill", {}).get("fixture_id", "") or match_id)
    backfill = entry.get("backfill", {})

    # Priority 1: entry.backfill.report_path
    bp = backfill.get("report_path", "")
    if bp and Path(bp).is_file():
        return bp, []

    # Priority 2: reports-root/<run_id>/reports/<fixture_id>.json then <match_id>.json
    run_id = backfill.get("run_id", "")
    if run_id:
        for name in (fixture_id, match_id):
            candidate = Path(reports_root) / run_id / "reports" / f"{name}.json"
            if candidate.is_file():
                return str(candidate), []

    # Priority 3: fallback broad search
    candidates: list[str] = []
    for name in (fixture_id, match_id):
        pattern = str(Path(reports_root) / "*" / "reports" / f"{name}.json")
        candidates.extend(sorted(glob.glob(pattern)))

    if candidates:
        # Priority 4: if multiple, sort by path and take last
        candidates = sorted(set(candidates))
        return candidates[-1], candidates

    return None, []


# ── Prompt source detection (§6.1.2) ──────────────────────────────


def _load_existing_self_iteration_job(output_dir: str, match_id: str) -> dict | None:
    """Check if output dir already has a job for this match_id."""
    jobs_path = Path(output_dir) / "llm_jobs.jsonl"
    if not jobs_path.is_file():
        return None
    with open(jobs_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if str(row.get("match_id", "")) == match_id:
                return row
    return None


def _find_prompt_from_backfill_job(
    run_dir: str,
    match_id: str,
    fixture_id: str,
) -> dict | None:
    """Find prompt in a run directory's llm_jobs.jsonl."""
    jobs_path = Path(run_dir) / "llm_jobs.jsonl"
    if not jobs_path.is_file():
        return None
    with open(jobs_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            mid = str(row.get("legacy_match_id", "") or row.get("match_id", ""))
            fid = str(row.get("fixture_id", ""))
            if mid == match_id or fid == fixture_id:
                return {"prompt": row.get("prompt", ""), "prompt_hash": _prompt_hash(row.get("prompt", ""))}
    return None


def _detect_wk_drift(stored_wk: dict, new_wk: dict) -> bool:
    """Detect if regenerated WK differs from stored WK.

    Currently checks overall_signal only (spec: if overall_signal differs → drift).
    """
    stored_overall = stored_wk.get("overall_signal", "")
    new_overall = new_wk.get("overall_signal", "")
    return stored_overall != new_overall


# ── Version / stale-evaluation logic ───────────────────────────────


_VERSION_FIELDS = (
    "features_version",
    "weak_label_version",
    "rubric_version",
    "prompt_builder_version",
    "blind_spots_version",
)


def _is_stale_evaluation(entry: dict, current_versions: dict) -> bool:
    """Check if evaluation metadata versions are stale relative to current."""
    eval_meta = entry.get("evaluation", {}).get("metadata", {})
    if not eval_meta:
        return True
    for field in _VERSION_FIELDS:
        if eval_meta.get(field) != current_versions.get(field):
            return True
    return False


def _has_evaluator_b(entry: dict, evaluator_id: str = "B") -> bool:
    """Check if entry has a strict v2 evaluation from the given evaluator."""
    evaluation = entry.get("evaluation", {})
    if not evaluation:
        return False
    if evaluation.get("source") != "llm":
        return False
    meta = evaluation.get("metadata", {})
    if meta.get("evaluator_id") == evaluator_id:
        # Check strict v2 fields present
        has_strict_v2 = all(
            evaluation.get(k) is not None
            for k in ("evidence", "confidence", "missing_or_weak_evidence", "weak_label_disagreements")
        )
        return has_strict_v2
    # If no metadata but evaluation exists with source=llm and strict v2 fields
    if not meta and evaluation.get("source") == "llm":
        has_strict_v2 = all(
            evaluation.get(k) is not None
            for k in ("evidence", "confidence", "missing_or_weak_evidence", "weak_label_disagreements")
        )
        return has_strict_v2
    return False


def _filter_entries(
    entries: list[dict],
    evaluator_id: str,
    only: str,
    current_versions: dict | None = None,
) -> list[dict]:
    """Filter entries based on --only mode."""
    result = []
    for entry in entries:
        if not _is_feature_backed(entry):
            continue
        if only in ("missing-evaluation", "missing-or-stale-evaluation"):
            if not _has_evaluator_b(entry, evaluator_id):
                result.append(entry)
                continue
        if only in ("stale-evaluation", "missing-or-stale-evaluation"):
            if _has_evaluator_b(entry, evaluator_id) and current_versions:
                if _is_stale_evaluation(entry, current_versions):
                    result.append(entry)
    return result


def _get_current_versions(entries: list[dict]) -> dict:
    """Derive current versions from KB entries + blind spots registry."""
    versions = {
        "features_version": "v1",
        "weak_label_version": "v1.1",
        "rubric_version": "arteta_v1",
        "prompt_builder_version": "v1",
        "blind_spots_version": "v1",
    }
    for entry in entries:
        if _is_feature_backed(entry):
            versions["features_version"] = entry.get("features_version", "v1")
            versions["weak_label_version"] = entry.get("weak_label_version", "v1.1")
            versions["rubric_version"] = entry.get("rubric_version", "arteta_v1")
            versions["prompt_builder_version"] = entry.get("prompt_builder_version", "v1")
            break
    # Read blind spots version from registry JSON
    registry_path = Path(__file__).resolve().parent.parent / "rubrics" / "arteta_blind_spots.json"
    try:
        if registry_path.exists():
            with open(registry_path, encoding="utf-8") as f:
                registry = json.load(f)
            versions["blind_spots_version"] = registry.get("version", "v1")
    except (OSError, json.JSONDecodeError):
        pass
    return versions


def _run_prepare_evaluation(report_json: dict) -> dict:
    """Run prepare_evaluation on a report dict. Returns result dict."""
    from src.tools.prepare_evaluation import prepare_evaluation
    result = prepare_evaluation(report_json, output_format="json")
    if isinstance(result, str):
        return {"ok": False, "error": {"code": "UNEXPECTED_STRING", "message": result}}
    return result


# ── Mode: make-jobs (§6.1) ─────────────────────────────────────────


def run_make_jobs(
    kb_path: str,
    reports_root: str,
    only: str,
    evaluator_id: str,
    run_id: str,
    output_dir: str,
) -> dict:
    """Generate evaluation jobs for missing/stale evaluator B entries.

    Non-mutation: never writes KB.
    """
    entries = _load_kb(kb_path)
    current_versions = _get_current_versions(entries)
    candidates = _filter_entries(entries, evaluator_id, only, current_versions)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    jobs: list[dict] = []
    per_match_details: list[dict] = []

    for entry in candidates:
        match_id = str(entry.get("match_id", ""))
        fixture_id = str(entry.get("backfill", {}).get("fixture_id", "") or match_id)

        # 1. Find report
        report_path, report_candidates = _find_report(entry, reports_root)
        if report_path is None:
            per_match_details.append({
                "match_id": match_id,
                "ok": False,
                "error": {
                    "code": "REPORT_NOT_FOUND",
                    "message": "No report found via backfill.report_path, backfill.run_id, or reports-root search.",
                },
            })
            continue

        # 2. Find prompt (priority order §6.1.2)
        # When stale, skip backfill prompt reuse — regenerate to pick up new blind spots
        prompt_data = None
        prompt_source = ""
        skip_backfill_prompts = "stale" in only

        # 2a. Existing self-iteration job in output dir
        existing_job = _load_existing_self_iteration_job(str(out), match_id)
        if existing_job and not skip_backfill_prompts:
            prompt_data = {
                "prompt": existing_job["prompt"],
                "prompt_hash": existing_job.get("prompt_hash", _prompt_hash(existing_job["prompt"])),
            }
            prompt_source = "self_iteration_existing"

        # 2b. Backfill llm_jobs.jsonl from entry.backfill.run_id (skip for stale)
        if not prompt_data and not skip_backfill_prompts:
            backfill_run_id = entry.get("backfill", {}).get("run_id", "")
            if backfill_run_id:
                backfill_dir = str(Path(reports_root) / backfill_run_id)
                prompt_data = _find_prompt_from_backfill_job(backfill_dir, match_id, fixture_id)
                if prompt_data:
                    prompt_source = "backfill_llm_job"

        # 2c. Report's run directory llm_jobs.jsonl (skip for stale)
        if not prompt_data and not skip_backfill_prompts:
            report_run_dir = str(Path(report_path).parent.parent)
            prompt_data = _find_prompt_from_backfill_job(report_run_dir, match_id, fixture_id)
            if prompt_data:
                prompt_source = "backfill_llm_job"

        # 2d. Run prepare_evaluation to regenerate
        wk_drift_detected = False
        if not prompt_data:
            report_json = json.loads(Path(report_path).read_text(encoding="utf-8"))
            try:
                prep_result = _run_prepare_evaluation(report_json)
            except Exception as exc:
                per_match_details.append({
                    "match_id": match_id,
                    "ok": False,
                    "error": {
                        "code": "PREPARE_FAILED",
                        "message": f"prepare_evaluation exception: {exc}",
                    },
                })
                continue

            if not prep_result.get("ok"):
                per_match_details.append({
                    "match_id": match_id,
                    "ok": False,
                    "error": prep_result.get("error", {"code": "PREPARE_FAILED", "message": "unknown"}),
                })
                continue

            prompt = prep_result.get("prompt", "")
            prompt_data = {
                "prompt": prompt,
                "prompt_hash": _prompt_hash(prompt),
            }
            prompt_source = "prepare_evaluation_regenerated"

            # WK drift detection
            new_wk = prep_result.get("weak_labels", {})
            stored_wk = entry.get("weak_labels", {})
            if _detect_wk_drift(stored_wk, new_wk):
                wk_drift_detected = True
                per_match_details.append({
                    "match_id": match_id,
                    "ok": True,
                    "wk_drift_detected": True,
                    "drift_details": {
                        "stored_overall": stored_wk.get("overall_signal", ""),
                        "new_overall": new_wk.get("overall_signal", ""),
                    },
                })

        # Build job row (§7.1)
        job_row = {
            "job_schema_version": "self_iteration_job_v1",
            "match_id": match_id,
            "fixture_id": fixture_id,
            "evaluator_id": evaluator_id,
            "run_id": run_id,
            "prompt_source": prompt_source,
            "prompt_hash": prompt_data["prompt_hash"],
            "prompt": prompt_data["prompt"],
            "features": entry.get("features", {}),
            "weak_labels": entry.get("weak_labels", {}),
            "report_path": report_path,
            "report_candidates": report_candidates,
            "versions": {
                "features_version": entry.get("features_version", "v1"),
                "weak_label_version": entry.get("weak_label_version", "v1.1"),
                "rubric_version": entry.get("rubric_version", "arteta_v1"),
                "prompt_builder_version": entry.get("prompt_builder_version", "v1"),
            },
            "expected_output_schema": "strict_v2_evaluation",
        }

        if wk_drift_detected:
            job_row["wk_drift_detected"] = True

        jobs.append(job_row)

        if not any(d.get("match_id") == match_id for d in per_match_details):
            per_match_details.append({
                "match_id": match_id,
                "ok": True,
                "prompt_source": prompt_source,
                "report_path": report_path,
            })

    # Write llm_jobs.jsonl
    jobs_path = out / "llm_jobs.jsonl"
    with open(jobs_path, "w", encoding="utf-8") as f:
        for row in jobs:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # Write make_jobs_report.json
    report = {
        "summary": {
            "total_candidates": len(candidates),
            "jobs_generated": len(jobs),
            "skipped": len(candidates) - len(jobs),
            "only_mode": only,
            "evaluator_id": evaluator_id,
            "run_id": run_id,
        },
        "per_match": per_match_details,
    }
    report_path = out / "make_jobs_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # Write manifest_snapshot.json
    manifest = {
        "kb_path": kb_path,
        "reports_root": reports_root,
        "only": only,
        "evaluator_id": evaluator_id,
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    manifest_path = out / "manifest_snapshot.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    return {
        "summary": report["summary"],
        "jobs_path": str(jobs_path),
        "report_path": str(report_path),
        "manifest_path": str(manifest_path),
    }


# ── Mode: ingest-results (§6.2) ────────────────────────────────────


def run_ingest_results(
    kb_path: str,
    run_dir: str,
    input_path: str,
    *,
    write: bool = False,
) -> dict:
    """Write evaluator B strict v2 results into KB.

    Requires --write for mutation. Writes before/after snapshots.
    Idempotent: re-running with same input skips already-ingested entries.
    """
    entries = _load_kb(kb_path)
    kb_index = _build_kb_index(entries)

    # Read input results
    results: list[dict] = []
    with open(input_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                results.append(json.loads(line))

    # Snapshot KB before
    run_path = Path(run_dir)
    run_path.mkdir(parents=True, exist_ok=True)

    applied: list[dict] = []
    skipped: list[dict] = []
    errors: list[dict] = []

    for row in results:
        match_id = str(row.get("match_id", ""))
        evaluation = row.get("evaluation", {})

        # Validate
        try:
            validate_llm_result(evaluation, strict=True)
        except ValueError as e:
            errors.append({
                "match_id": match_id,
                "error": {"code": "VALIDATION_FAILED", "message": str(e)},
            })
            continue

        # Look up KB entry
        entry = kb_index.get(match_id)
        if entry is None:
            errors.append({
                "match_id": match_id,
                "error": {"code": "KB_ENTRY_NOT_FOUND", "message": f"match_id '{match_id}' not in KB"},
            })
            continue

        # Idempotency: check if already ingested with same prompt_hash
        existing_eval = entry.get("evaluation", {})
        existing_meta = existing_eval.get("metadata", {})
        if (
            existing_meta.get("evaluator_id") == row.get("evaluator_id")
            and existing_meta.get("prompt_hash") == row.get("prompt_hash")
            and existing_eval.get("source") == "llm"
        ):
            skipped.append({
                "match_id": match_id,
                "reason": "already_ingested_with_same_prompt_hash",
            })
            continue

        # Build evaluation_metadata
        evaluation_metadata = {
            "evaluator_id": row.get("evaluator_id", ""),
            "run_id": row.get("run_id", ""),
            "model": row.get("model", ""),
            "prompt_hash": row.get("prompt_hash", ""),
            "created_at": row.get("created_at", ""),
            "features_version": entry.get("features_version", "v1"),
            "weak_label_version": entry.get("weak_label_version", "v1.1"),
            "rubric_version": entry.get("rubric_version", "arteta_v1"),
            "prompt_builder_version": entry.get("prompt_builder_version", "v1"),
            "blind_spots_version": _get_current_versions([entry]).get("blind_spots_version", "v1"),
            "job_schema_version": row.get("job_schema_version", ""),
        }

        # Build evaluation dict for KB
        eval_dict: dict = {
            "source": "llm",
            "confidence": evaluation.get("confidence"),
            "model_signals": evaluation.get("model_signals", {}),
            "dimension_signals": evaluation.get("dimension_signals", {}),
            "overall_signal": evaluation.get("overall_signal", ""),
            "narrative": evaluation.get("narrative", ""),
            "evidence": evaluation.get("evidence", {}),
            "missing_or_weak_evidence": evaluation.get("missing_or_weak_evidence", []),
            "weak_label_disagreements": evaluation.get("weak_label_disagreements", []),
            "metadata": evaluation_metadata,
        }

        applied.append({
            "match_id": match_id,
            "evaluator_id": row.get("evaluator_id", ""),
            "model": row.get("model", ""),
        })

        # Only mutate if --write
        if write:
            entry["evaluation"] = eval_dict

    # Write snapshots and report
    if write:
        # Write before snapshot (from original entries)
        original_entries = _load_kb(kb_path)
        before_path = run_path / "knowledge.before.json"
        with open(before_path, "w", encoding="utf-8") as f:
            json.dump(original_entries, f, ensure_ascii=False, indent=2)

        # Write KB
        _atomic_write_kb(kb_path, entries)

        # Write after snapshot
        after_path = run_path / "knowledge.after.json"
        with open(after_path, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)

    # Write ingest_report.json
    report = {
        "summary": {
            "total_results": len(results),
            "applied": len(applied),
            "skipped": len(skipped),
            "errors": len(errors),
            "dry_run": not write,
        },
        "applied": applied,
        "skipped": skipped,
        "errors": errors,
    }
    report_path = run_path / "ingest_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    return {
        "summary": report["summary"],
        "report_path": str(report_path),
    }


# ── Mode: promote-blind-spots (§6.5) ──────────────────────────────


def run_promote_blind_spots(
    candidates_path: str,
    output_path: str,
    *,
    write: bool = False,
) -> dict:
    """Promote prompt_blind_spot candidates to rubric JSON.

    Requires --write for mutation. Idempotent.
    Only promotes proposed_action="prompt_blind_spot".
    """
    # Read candidates
    with open(candidates_path, encoding="utf-8") as f:
        candidates_data = json.load(f)

    prompt_candidates = [
        c for c in candidates_data.get("candidates", [])
        if c.get("proposed_action") == "prompt_blind_spot"
    ]

    # Read existing blind spots
    output_p = Path(output_path)
    if output_p.exists():
        with open(output_p, encoding="utf-8") as f:
            blind_spots_data = json.load(f)
    else:
        blind_spots_data = {"version": "v1", "blind_spots": []}

    existing_ids = {s["id"] for s in blind_spots_data.get("blind_spots", [])}

    added: list[dict] = []
    skipped: list[dict] = []

    for candidate in prompt_candidates:
        cid = candidate.get("id", "")
        if cid in existing_ids:
            skipped.append({"id": cid, "reason": "already_exists"})
            continue

        # Build new blind spot entry
        new_spot = {
            "id": cid,
            "description": candidate.get("rationale", ""),
            "guardrail": candidate.get("rationale", ""),
            "source": "rule_mining",
            "weak_label_version": "v1.1",
            "status": "active",
        }

        added.append(new_spot)
        existing_ids.add(cid)

    # Version bump if any added
    if added:
        current_version = blind_spots_data.get("version", "v1")
        # Simple version bump: v1 → v2, v2 → v3, etc.
        try:
            v_num = int(current_version.lstrip("v"))
            blind_spots_data["version"] = f"v{v_num + 1}"
        except ValueError:
            blind_spots_data["version"] = "v2"

        blind_spots_data["blind_spots"].extend(added)

    # Write output
    if write:
        output_p.parent.mkdir(parents=True, exist_ok=True)
        with open(output_p, "w", encoding="utf-8") as f:
            json.dump(blind_spots_data, f, ensure_ascii=False, indent=2)

    # Write promote_report.json
    report = {
        "summary": {
            "total_candidates": len(prompt_candidates),
            "added_count": len(added),
            "skipped_count": len(skipped),
            "dry_run": not write,
        },
        "added": [a["id"] for a in added],
        "skipped": skipped,
    }

    report_dir = output_p.parent
    report_path = report_dir / "promote_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    return {
        "summary": report["summary"],
        "report_path": str(report_path),
    }


# ── CLI ────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Low-touch self-iteration pipeline"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ── make-jobs ───────────────────────────────────────────────────
    mj = subparsers.add_parser("make-jobs", help="Generate evaluation jobs")
    mj.add_argument("--kb", required=True, help="Path to knowledge.json")
    mj.add_argument("--reports-root", required=True, help="Root directory for backfill runs")
    mj.add_argument("--only", default="missing-evaluation",
                     choices=["missing-evaluation", "stale-evaluation", "missing-or-stale-evaluation"],
                     help="Filter mode")
    mj.add_argument("--evaluator-id", default="B", help="Evaluator ID")
    mj.add_argument("--run-id", required=True, help="Run ID for output jobs")
    mj.add_argument("--output", required=True, help="Output directory")

    # ── ingest-results ──────────────────────────────────────────────
    ir = subparsers.add_parser("ingest-results", help="Write evaluator B results to KB")
    ir.add_argument("--kb", required=True, help="Path to knowledge.json")
    ir.add_argument("--run", required=True, help="Run directory")
    ir.add_argument("--input", required=True, help="Path to llm_results.jsonl")
    ir.add_argument("--write", action="store_true", help="Allow KB mutation")

    # ── promote-blind-spots ─────────────────────────────────────────
    pb = subparsers.add_parser("promote-blind-spots", help="Promote blind spot candidates")
    pb.add_argument("--candidates", required=True, help="Path to rule_candidates.json")
    pb.add_argument("--output", required=True, help="Path to arteta_blind_spots.json")
    pb.add_argument("--write", action="store_true", help="Allow mutation")

    # ── adjudicate ──────────────────────────────────────────────────
    adj = subparsers.add_parser("adjudicate", help="Compare WK v1.1 vs Evaluator B")
    adj.add_argument("--kb", required=True, help="Path to knowledge.json")
    adj.add_argument("--run-id", required=True, help="Run ID")
    adj.add_argument("--output", required=True, help="Path to adjudication_report.json")

    # ── mine-rules ──────────────────────────────────────────────────
    mr = subparsers.add_parser("mine-rules", help="Extract candidate rules from disagreements")
    mr.add_argument("--adjudication", required=True, help="Path to adjudication_report.json")
    mr.add_argument("--output", required=True, help="Path to rule_candidates.json")

    args = parser.parse_args()

    if args.command == "make-jobs":
        if not Path(args.kb).exists():
            print(json.dumps({"error": f"KB file not found: {args.kb}"}), file=sys.stderr)
            sys.exit(1)
        result = run_make_jobs(
            kb_path=args.kb,
            reports_root=args.reports_root,
            only=args.only,
            evaluator_id=args.evaluator_id,
            run_id=args.run_id,
            output_dir=args.output,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.command == "ingest-results":
        if not Path(args.kb).exists():
            print(json.dumps({"error": f"KB file not found: {args.kb}"}), file=sys.stderr)
            sys.exit(1)
        if not Path(args.input).exists():
            print(json.dumps({"error": f"Input file not found: {args.input}"}), file=sys.stderr)
            sys.exit(1)
        result = run_ingest_results(
            kb_path=args.kb,
            run_dir=args.run,
            input_path=args.input,
            write=args.write,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.command == "promote-blind-spots":
        if not Path(args.candidates).exists():
            print(json.dumps({"error": f"Candidates file not found: {args.candidates}"}), file=sys.stderr)
            sys.exit(1)
        result = run_promote_blind_spots(
            candidates_path=args.candidates,
            output_path=args.output,
            write=args.write,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.command == "adjudicate":
        if not Path(args.kb).exists():
            print(json.dumps({"error": f"KB file not found: {args.kb}"}), file=sys.stderr)
            sys.exit(1)
        from src.evaluation.adjudication import run_adjudication
        result = run_adjudication(args.kb, args.run_id, args.output)
        print(json.dumps({"ok": True, "output": args.output, "summary": result["summary"]}, indent=2, ensure_ascii=False))

    elif args.command == "mine-rules":
        if not Path(args.adjudication).exists():
            print(json.dumps({"error": f"Adjudication file not found: {args.adjudication}"}), file=sys.stderr)
            sys.exit(1)
        from src.evaluation.rule_mining import run_rule_mining
        result = run_rule_mining(args.adjudication, args.output)
        print(json.dumps({"ok": True, "output": args.output, "summary": result["summary"]}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
