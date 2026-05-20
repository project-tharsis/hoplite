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

# Signal helpers (mirrored from adjudication.py for use in distill/replay)
SIGNAL_ORDER = {"🔴": 0, "🟡": 1, "🟢": 2}


def _signal_rank(sig: str) -> int:
    return SIGNAL_ORDER.get(sig, -1)


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
        if only == "all-feature-backed":
            result.append(entry)
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


def _is_quarantine_result(evaluation: dict) -> tuple[bool, str]:
    """Detect low-quality / placeholder evaluator output.

    Returns (is_quarantine, reason).
    """
    narrative = evaluation.get("narrative", "")
    overall = evaluation.get("overall_signal", "")
    model_signals = evaluation.get("model_signals", {})
    dimension_signals = evaluation.get("dimension_signals", {})

    # Default placeholder narrative
    if narrative in ("", "阿森纳本场表现🟡。数据驱动六模型评估。"):
        return True, "placeholder_narrative"

    # All model signals are 🟡 (placeholder)
    if model_signals and all(v == "🟡" for v in model_signals.values()):
        return True, "all_model_signals_placeholder"

    # All dimension signals are 🟡
    if dimension_signals and all(v == "🟡" for v in dimension_signals.values()):
        return True, "all_dimension_signals_placeholder"

    # Overall is 🟡 but no meaningful evidence
    evidence = evaluation.get("evidence", {})
    if overall == "🟡" and not any(evidence.values()):
        return True, "yellow_overall_no_evidence"

    return False, ""


def _flatten_nested_evaluation(row: dict) -> dict:
    """Flatten nested evaluation dict if row.evaluation.evaluation exists.

    Handles the case where evaluation contains a nested 'evaluation' key
    with a separate evaluation dict. Promotes the nested one if the parent
    has no overall_signal.

    Note: this does NOT handle row-level strict v2 promotion (where real
    fields are at row top-level and row.evaluation is a placeholder).
    That case is handled by the quality gate quarantine.

    Returns the repaired evaluation dict.
    """
    evaluation = row.get("evaluation", {})
    nested = evaluation.get("evaluation")
    if isinstance(nested, dict) and nested.get("overall_signal"):
        top_overall = evaluation.get("overall_signal", "")
        nested_overall = nested.get("overall_signal", "")
        if top_overall and top_overall != nested_overall:
            pass  # Top-level has real values, keep it
        elif not top_overall and nested_overall:
            evaluation = {**evaluation, **nested}
    return evaluation


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

        # Schema repair: flatten nested evaluation dict if present
        evaluation = _flatten_nested_evaluation(row)

        # Quality gate: quarantine placeholder results
        is_quarantine, quarantine_reason = _is_quarantine_result(evaluation)
        if is_quarantine:
            errors.append({
                "match_id": match_id,
                "error": {"code": "QUARANTINE", "message": f"Low-quality result: {quarantine_reason}"},
            })
            continue

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
                     choices=["missing-evaluation", "stale-evaluation", "missing-or-stale-evaluation", "all-feature-backed"],
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
    adj.add_argument("--evaluator-run-id", default=None, help="Only compare evaluations from this run_id")
    adj.add_argument("--output", required=True, help="Path to adjudication_report.json")

    # ── mine-rules ──────────────────────────────────────────────────
    mr = subparsers.add_parser("mine-rules", help="Extract candidate rules from disagreements")
    mr.add_argument("--adjudication", required=True, help="Path to adjudication_report.json")
    mr.add_argument("--output", required=True, help="Path to rule_candidates.json")

    # ── compare-runs ────────────────────────────────────────────────
    cr = subparsers.add_parser("compare-runs", help="Compare two adjudication reports")
    cr.add_argument("--b001", required=True, help="Path to b-001 adjudication_report.json")
    cr.add_argument("--b002", required=True, help="Path to b-002 adjudication_report.json")
    cr.add_argument("--output", required=True, help="Path to comparison_report.json")

    # ── summarize-validation (Phase 1) ─────────────────────────────
    sv = subparsers.add_parser("summarize-validation", help="Solidify b-003 validation summary")
    sv.add_argument("--comparison", required=True, help="Path to comparison_report.json")
    sv.add_argument("--adjudication", required=True, help="Path to adjudication_report.json")
    sv.add_argument("--output", required=True, help="Path to validation_summary.json")

    # ── distill-wk-rules (Phase 2) ─────────────────────────────────
    dw = subparsers.add_parser("distill-wk-rules", help="Distill WK v1.2 rule candidates")
    dw.add_argument("--kb", required=True, help="Path to knowledge.json")
    dw.add_argument("--baseline-adjudication", required=True, help="Path to b-001 adjudication_report.json")
    dw.add_argument("--current-adjudication", required=True, help="Path to b-003 adjudication_report.json")
    dw.add_argument("--comparison", required=True, help="Path to comparison_report.json")
    dw.add_argument("--output", required=True, help="Path to wk_rule_candidates.json")

    # ── replay-wk-candidates (Phase 3) ─────────────────────────────
    rp = subparsers.add_parser("replay-wk-candidates", help="Dry-run replay of WK candidate rules")
    rp.add_argument("--kb", required=True, help="Path to knowledge.json")
    rp.add_argument("--adjudication", required=True, help="Path to b-003 adjudication_report.json")
    rp.add_argument("--candidates", required=True, help="Path to wk_rule_candidates.json")
    rp.add_argument("--output", required=True, help="Path to wk_candidate_replay.json")

    # ── propose-wk-patch-spec (Phase 5) ────────────────────────────
    pp = subparsers.add_parser("propose-wk-patch-spec", help="Generate WK v1.2 implementation spec")
    pp.add_argument("--candidates", required=True, help="Path to wk_rule_candidates.json")
    pp.add_argument("--replay", required=True, help="Path to wk_candidate_replay.json")
    pp.add_argument("--regression-manifest", required=True, help="Path to regression_manifest.json")
    pp.add_argument("--output", required=True, help="Path to implementation spec .md")

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
        result = run_adjudication(args.kb, args.run_id, args.output, evaluator_run_id=args.evaluator_run_id)
        print(json.dumps({"ok": True, "output": args.output, "summary": result["summary"]}, indent=2, ensure_ascii=False))

    elif args.command == "mine-rules":
        if not Path(args.adjudication).exists():
            print(json.dumps({"error": f"Adjudication file not found: {args.adjudication}"}), file=sys.stderr)
            sys.exit(1)
        from src.evaluation.rule_mining import run_rule_mining
        result = run_rule_mining(args.adjudication, args.output)
        print(json.dumps({"ok": True, "output": args.output, "summary": result["summary"]}, indent=2, ensure_ascii=False))

    elif args.command == "compare-runs":
        result = run_compare_runs(args.b001, args.b002, args.output)
        print(json.dumps({"ok": True, "output": args.output, "summary": result["summary"]}, indent=2, ensure_ascii=False))

    elif args.command == "summarize-validation":
        result = run_summarize_validation(args.comparison, args.adjudication, args.output)
        print(json.dumps({"ok": True, "output": args.output}, indent=2, ensure_ascii=False))

    elif args.command == "distill-wk-rules":
        result = run_distill_wk_rules(args.kb, args.baseline_adjudication, args.current_adjudication, args.comparison, args.output)
        print(json.dumps({"ok": True, "output": args.output, "summary": result["summary"]}, indent=2, ensure_ascii=False))

    elif args.command == "replay-wk-candidates":
        result = run_replay_wk_candidates(args.kb, args.adjudication, args.candidates, args.output)
        print(json.dumps({"ok": True, "output": args.output, "summary": result["summary"]}, indent=2, ensure_ascii=False))

    elif args.command == "propose-wk-patch-spec":
        result = run_propose_wk_patch_spec(args.candidates, args.replay, args.regression_manifest, args.output)
        print(json.dumps({"ok": True, "output": args.output, "generated": result["generated"]}, indent=2, ensure_ascii=False))


def run_compare_runs(b001_path: str, b002_path: str, output_path: str) -> dict:
    """Compare two adjudication reports and emit delta metrics.

    When denominators differ, computes a clean-subset comparison by filtering
    the larger report to only match_ids present in the smaller report.
    """
    with open(b001_path, encoding="utf-8") as f:
        b001 = json.load(f)
    with open(b002_path, encoding="utf-8") as f:
        b002 = json.load(f)

    def _extract(report: dict) -> dict:
        s = report.get("summary", {})
        total = s.get("compared", 0)
        return {
            "overall_agreement_rate": s.get("overall_agreement_rate", 0.0),
            "dimension_agreement_rate": s.get("dimension_agreement_rate", 0.0),
            "model_agreement_rate": s.get("model_agreement_rate", 0.0),
            "wk_too_harsh": s.get("wk_too_harsh", 0),
            "wk_too_generous": s.get("wk_too_generous", 0),
            "dimension_level_disagreement": s.get("dimension_level_disagreement", 0),
            "model_level_disagreement": s.get("model_level_disagreement", 0),
            "compared": total,
        }

    def _compute_from_rows(rows: list[dict]) -> dict:
        """Recompute summary metrics from a filtered rows list."""
        from collections import Counter
        compared_rows = [r for r in rows if r["status"] not in ("missing_evaluator_b", "invalid_evaluator_b")]
        n = len(compared_rows)
        if n == 0:
            return {k: 0 for k in [
                "overall_agreement_rate", "dimension_agreement_rate", "model_agreement_rate",
                "wk_too_harsh", "wk_too_generous", "dimension_level_disagreement",
                "model_level_disagreement", "compared",
            ]}

        status_counts = Counter(r["status"] for r in compared_rows)
        overall_agree = sum(1 for r in compared_rows if not r["differences"] or "overall" not in r["differences"])
        dim_agree = sum(1 for r in compared_rows if r["status"] in ("agreement_high_confidence", "agreement_low_confidence", "model_level_disagreement"))
        model_agree = sum(1 for r in compared_rows if r["status"] in ("agreement_high_confidence", "agreement_low_confidence"))

        return {
            "overall_agreement_rate": round(overall_agree / n, 4),
            "dimension_agreement_rate": round(dim_agree / n, 4),
            "model_agreement_rate": round(model_agree / n, 4),
            "wk_too_harsh": status_counts.get("wk_too_harsh", 0),
            "wk_too_generous": status_counts.get("wk_too_generous", 0),
            "dimension_level_disagreement": status_counts.get("dimension_level_disagreement", 0),
            "model_level_disagreement": status_counts.get("model_level_disagreement", 0),
            "compared": n,
        }

    def _check_criteria(r1: dict, r2: dict) -> int:
        met = 0
        if r2["overall_agreement_rate"] > r1["overall_agreement_rate"]:
            met += 1
        if r2["dimension_agreement_rate"] > r1["dimension_agreement_rate"]:
            met += 1
        if r2["model_agreement_rate"] > r1["model_agreement_rate"]:
            met += 1
        if r1["wk_too_harsh"] > 0 and (r1["wk_too_harsh"] - r2["wk_too_harsh"]) / r1["wk_too_harsh"] >= 0.20:
            met += 1
        if r2["dimension_level_disagreement"] < r1["dimension_level_disagreement"]:
            met += 1
        return met

    r1 = _extract(b001)
    r2 = _extract(b002)

    delta = {
        "overall_agreement_rate": round(r2["overall_agreement_rate"] - r1["overall_agreement_rate"], 4),
        "dimension_agreement_rate": round(r2["dimension_agreement_rate"] - r1["dimension_agreement_rate"], 4),
        "model_agreement_rate": round(r2["model_agreement_rate"] - r1["model_agreement_rate"], 4),
        "wk_too_harsh": r2["wk_too_harsh"] - r1["wk_too_harsh"],
        "wk_too_generous": r2["wk_too_generous"] - r1["wk_too_generous"],
        "dimension_level_disagreement": r2["dimension_level_disagreement"] - r1["dimension_level_disagreement"],
        "model_level_disagreement": r2["model_level_disagreement"] - r1["model_level_disagreement"],
    }

    criteria_met = _check_criteria(r1, r2)
    same_denom = r1["compared"] == r2["compared"]

    # Clean-subset comparison: filter both reports to common compared match_ids
    clean_subset = None
    if not same_denom:
        b001_rows = b001.get("rows", [])
        b002_rows = b002.get("rows", [])

        # Use compared match_ids from the smaller-denominator report as the subset
        smaller_rows = b001_rows if r1["compared"] <= r2["compared"] else b002_rows
        # compared = not missing/invalid
        subset_ids = {r["match_id"] for r in smaller_rows if r["status"] not in ("missing_evaluator_b", "invalid_evaluator_b")}

        if subset_ids:
            b001_filtered = [r for r in b001_rows if r["match_id"] in subset_ids]
            b002_filtered = [r for r in b002_rows if r["match_id"] in subset_ids]
            cs_r1 = _compute_from_rows(b001_filtered)
            cs_r2 = _compute_from_rows(b002_filtered)
            cs_delta = {
                "overall_agreement_rate": round(cs_r2["overall_agreement_rate"] - cs_r1["overall_agreement_rate"], 4),
                "dimension_agreement_rate": round(cs_r2["dimension_agreement_rate"] - cs_r1["dimension_agreement_rate"], 4),
                "model_agreement_rate": round(cs_r2["model_agreement_rate"] - cs_r1["model_agreement_rate"], 4),
                "wk_too_harsh": cs_r2["wk_too_harsh"] - cs_r1["wk_too_harsh"],
                "wk_too_generous": cs_r2["wk_too_generous"] - cs_r1["wk_too_generous"],
                "dimension_level_disagreement": cs_r2["dimension_level_disagreement"] - cs_r1["dimension_level_disagreement"],
                "model_level_disagreement": cs_r2["model_level_disagreement"] - cs_r1["model_level_disagreement"],
            }
            cs_criteria = _check_criteria(cs_r1, cs_r2)
            clean_subset = {
                "b001": cs_r1,
                "b002": cs_r2,
                "delta": cs_delta,
                "criteria_met": cs_criteria,
                "criteria_total": 5,
                "same_denominator": cs_r1["compared"] == cs_r2["compared"],
                "effective": cs_criteria >= 3 and cs_r1["compared"] == cs_r2["compared"],
                "common_match_ids": len(subset_ids),
            }

    report = {
        "b001": r1,
        "b002": r2,
        "delta": delta,
        "criteria_met": criteria_met,
        "criteria_total": 5,
        "same_denominator": same_denom,
        "effective": criteria_met >= 3 and same_denom,
    }
    if clean_subset is not None:
        report["clean_subset"] = clean_subset

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    summary = {
        "criteria_met": criteria_met,
        "criteria_total": 5,
        "same_denominator": same_denom,
        "effective": criteria_met >= 3 and same_denom,
    }
    if clean_subset is not None:
        summary["clean_subset_criteria_met"] = clean_subset["criteria_met"]
        summary["clean_subset_effective"] = clean_subset["effective"]
    return {"summary": summary}


# ── Phase 1: summarize-validation ────────────────────────────────────


def run_summarize_validation(comparison_path: str, adjudication_path: str, output_path: str) -> dict:
    """Solidify b-003 validation summary from comparison + adjudication reports."""
    with open(comparison_path, encoding="utf-8") as f:
        comparison = json.load(f)
    with open(adjudication_path, encoding="utf-8") as f:
        adjudication = json.load(f)

    cs = comparison.get("clean_subset", {})
    excluded_count = adjudication["summary"].get("missing_evaluator_b", 0)

    summary = {
        "source_run": "b-003",
        "prompt_blind_spots_validated": cs.get("effective", False),
        "primary_basis": "clean_subset",
        "clean_subset": {
            "common_match_ids": cs.get("common_match_ids", 0),
            "criteria_met": cs.get("criteria_met", 0),
            "criteria_total": cs.get("criteria_total", 5),
            "effective": cs.get("effective", False),
            "overall_delta": cs.get("delta", {}).get("overall_agreement_rate", 0.0),
            "dimension_delta": cs.get("delta", {}).get("dimension_agreement_rate", 0.0),
            "model_delta": cs.get("delta", {}).get("model_agreement_rate", 0.0),
            "wk_too_harsh_delta": cs.get("delta", {}).get("wk_too_harsh", 0),
        },
        "excluded": {
            "quarantined_or_missing": excluded_count,
            "reason": "quality_gate",
        },
    }

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    return {"summary": summary}


# ── Phase 2: distill-wk-rules ────────────────────────────────────────


def _derive_feature_view(entry: dict) -> dict:
    """Derive deterministic feature predicates from KB entry features."""
    features = entry.get("features", {})
    result = features.get("result", "")
    score_margin = features.get("score_margin", 0)
    goals_conceded = features.get("goals_conceded", None)
    shots_delta = features.get("shots_delta", features.get("shot_delta", None))
    possession_delta = features.get("possession_delta", None)
    corner_delta = features.get("corner_delta", None)
    xg_delta = features.get("xg_delta", None)
    xg_against = features.get("xg_against", None)
    opponent_shots_on_target = features.get("opponent_shots_on_target", None)

    missing = []
    for f in ["goals_conceded", "shots_delta", "possession_delta", "corner_delta", "xg_delta", "xg_against", "opponent_shots_on_target"]:
        if features.get(f) is None:
            missing.append(f)

    clean_sheet = goals_conceded == 0 if goals_conceded is not None else False
    if goals_conceded is None:
        clean_sheet = False

    dom_conds = 0
    if shots_delta is not None and shots_delta >= 5:
        dom_conds += 1
    if possession_delta is not None and possession_delta >= 8:
        dom_conds += 1
    if corner_delta is not None and corner_delta >= 4:
        dom_conds += 1
    dominant_control = dom_conds >= 2

    dominant_chance_quality = xg_delta is not None and xg_delta >= 0.75

    risk_conds = 0
    if goals_conceded is not None and goals_conceded == 0:
        risk_conds += 1
    if opponent_shots_on_target is not None and opponent_shots_on_target <= 3:
        risk_conds += 1
    if xg_against is not None and xg_against <= 1.0:
        risk_conds += 1
    low_defensive_risk = risk_conds >= 2

    narrow_win = result == "W" and score_margin == 1
    loss_despite_dominance = result == "L" and (dominant_control or dominant_chance_quality)

    return {
        "match_id": entry.get("match_id", ""),
        "result": result,
        "opponent_quality": features.get("opponent_quality", "unknown"),
        "venue": features.get("venue", "unknown"),
        "competition_stage": features.get("competition_stage", "unknown"),
        "score_margin": score_margin,
        "clean_sheet": clean_sheet if goals_conceded is not None else False,
        "dominant_control": dominant_control,
        "dominant_chance_quality": dominant_chance_quality,
        "low_defensive_risk": low_defensive_risk,
        "narrow_win": narrow_win,
        "loss_despite_dominance": loss_despite_dominance,
        "xg_present": xg_delta is not None,
        "missing_features": missing,
    }


def run_distill_wk_rules(
    kb_path: str,
    baseline_adj_path: str,
    current_adj_path: str,
    comparison_path: str,
    output_path: str,
) -> dict:
    """Distill WK v1.2 rule candidates from b-003 disagreements."""
    entries = _load_kb(kb_path)
    kb_index = _build_kb_index(entries)

    with open(current_adj_path, encoding="utf-8") as f:
        current_adj = json.load(f)
    with open(comparison_path, encoding="utf-8") as f:
        comparison = json.load(f)

    # Get clean subset match_ids
    cs = comparison.get("clean_subset", {})
    cs_b003 = cs.get("b002", cs.get("b001", {}))
    # Build from rows: compared rows from current adjudication
    clean_ids = set()
    for row in current_adj.get("rows", []):
        if row["status"] not in ("missing_evaluator_b", "invalid_evaluator_b"):
            clean_ids.add(row["match_id"])

    # Disagreement statuses to distill
    distill_statuses = {"wk_too_harsh", "wk_too_generous", "dimension_level_disagreement", "model_level_disagreement"}

    candidates = []
    rejected = []

    # Group disagreements by (status, target, direction)
    disagreement_groups: dict[tuple, list[dict]] = {}
    for row in current_adj.get("rows", []):
        if row["match_id"] not in clean_ids:
            continue
        if row["status"] not in distill_statuses:
            continue

        entry = kb_index.get(row["match_id"])
        if entry is None:
            continue

        fv = _derive_feature_view(entry)

        # Determine target and direction based on status
        current_signal = ""
        target = ""
        target_signal = ""
        direction = ""
        if row["status"] == "wk_too_harsh":
            # WK is harsher than B — B wants upgrade
            target = "overall_signal"
            direction = "upgrade"
            current_signal = row["wk"]["overall_signal"]
            target_signal = row["b"]["overall_signal"]
        elif row["status"] == "wk_too_generous":
            target = "overall_signal"
            direction = "downgrade"
            current_signal = row["wk"]["overall_signal"]
            target_signal = row["b"]["overall_signal"]
        elif row["status"] == "dimension_level_disagreement":
            # Find the first differing dimension
            dim_diffs = [d for d in row["differences"] if d in ("execution", "adjustment", "satisfaction")]
            if not dim_diffs:
                continue
            target = f"dimension_signals.{dim_diffs[0]}"
            direction = "upgrade" if _signal_rank(row["b"]["dimension_signals"].get(dim_diffs[0], "")) > _signal_rank(row["wk"]["dimension_signals"].get(dim_diffs[0], "")) else "downgrade"
            current_signal = row["wk"]["dimension_signals"].get(dim_diffs[0], "")
            target_signal = row["b"]["dimension_signals"].get(dim_diffs[0], "")
        elif row["status"] == "model_level_disagreement":
            model_diffs = [d for d in row["differences"] if d in ("1", "2", "3", "4", "5", "6")]
            if not model_diffs:
                continue
            target = f"model_signals.{model_diffs[0]}"
            direction = "upgrade" if _signal_rank(row["b"]["model_signals"].get(model_diffs[0], "")) > _signal_rank(row["wk"]["model_signals"].get(model_diffs[0], "")) else "downgrade"
            current_signal = row["wk"]["model_signals"].get(model_diffs[0], "")
            target_signal = row["b"]["model_signals"].get(model_diffs[0], "")
        else:
            continue

        key = (row["status"], target, direction, target_signal)
        disagreement_groups.setdefault(key, []).append({
            "match_id": row["match_id"],
            "fv": fv,
            "current_signal": current_signal,
            "target_signal": target_signal,
        })

    # Build candidates from groups
    for (status, target, direction, target_signal), items in disagreement_groups.items():
        # Extract predicate from feature views
        predicates = {}
        for fv in items:
            for key in ["result", "opponent_quality", "venue", "competition_stage"]:
                val = fv.get(key)
                if val and val != "unknown":
                    predicates.setdefault(key, set()).add(val)
            for key in ["clean_sheet", "dominant_control", "dominant_chance_quality", "low_defensive_risk", "narrow_win", "loss_despite_dominance"]:
                if fv.get(key):
                    predicates.setdefault(key, set()).add(True)

        # Build predicate dict
        pred = {}
        for key, vals in predicates.items():
            if len(vals) == 1:
                pred[key] = list(vals)[0]
            elif key in ("result", "venue"):
                pred[key] = list(vals)[0] if len(vals) == 1 else list(vals)

        # Support count
        support = len(items)
        examples = [it["match_id"] for it in items[:5]]

        # Precision: how many of the predicate-matching rows agree with target_signal
        # For now, precision = support / (support + false_positives)
        # False positives = rows where predicate matches but WK already has target_signal
        false_positives = 0
        for row in current_adj.get("rows", []):
            if row["match_id"] in clean_ids and row["match_id"] not in {it["match_id"] for it in items}:
                entry = kb_index.get(row["match_id"])
                if entry:
                    fv = _derive_feature_view(entry)
                    if _predicate_matches(pred, fv):
                        # Check if WK already has target_signal here (would be a false positive)
                        wk_sig = row["wk"].get("overall_signal", "")
                        if target == "overall_signal" and wk_sig == target_signal:
                            false_positives += 1

        precision = support / (support + false_positives) if (support + false_positives) > 0 else 0.0

        # Build counterexamples (rows where predicate matches but disagreement goes other way)
        counterexamples = []
        regression_must_not = []
        for row in current_adj.get("rows", []):
            if row["match_id"] in clean_ids and row["match_id"] not in {it["match_id"] for it in items}:
                entry = kb_index.get(row["match_id"])
                if entry:
                    fv = _derive_feature_view(entry)
                    if _predicate_matches(pred, fv):
                        if row["status"] in ("wk_too_generous",) and direction == "upgrade":
                            counterexamples.append(row["match_id"])

        # Regression: known failures
        for row in current_adj.get("rows", []):
            if row.get("features", {}).get("result") == "L":
                entry = kb_index.get(row["match_id"])
                if entry:
                    fv = _derive_feature_view(entry)
                    if _predicate_matches(pred, fv):
                        regression_must_not.append(row["match_id"])

        candidate = {
            "candidate_schema_version": "wk_rule_candidate_v1",
            "id": f"wk_v1_2_{status}_{target.replace('.', '_')}_{direction}",
            "source_runs": ["b-001", "b-003"],
            "primary_run": "b-003",
            "target": target,
            "predicate": pred,
            "current_wk_signal": current_signal,
            "target_signal": target_signal,
            "direction": direction,
            "support": support,
            "precision_vs_b": round(precision, 4),
            "false_positive_count": false_positives,
            "examples": examples,
            "counterexamples": counterexamples[:5],
            "regression_must_not_change": regression_must_not[:5],
            "risk": "medium" if status == "wk_too_generous" else "low",
            "rationale": f"评估器B在{_predicate_description(pred)}时稳定给{'更高' if direction == 'upgrade' else '更低'}信号",
            "implementation_hint": "",
        }

        # Must have a non-empty deterministic predicate (spec §8.3)
        if not pred:
            candidate["rejection_reason"] = "empty predicate: no deterministic feature predicate found"
            rejected.append(candidate)
            continue

        # Check thresholds
        is_generous = status == "wk_too_generous"
        if is_generous:
            if support >= 7 and precision >= 0.90 and false_positives == 0:
                candidates.append(candidate)
            else:
                candidate["rejection_reason"] = f"wk_too_generous stricter gate: support={support}<7 or precision={precision:.2f}<0.90 or fp={false_positives}>0"
                rejected.append(candidate)
        else:
            if support >= 5 and precision >= 0.80 and false_positives <= 1:
                candidates.append(candidate)
            else:
                candidate["rejection_reason"] = f"gate: support={support}<5 or precision={precision:.2f}<0.80 or fp={false_positives}>1"
                rejected.append(candidate)

    # Write outputs
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(candidates, f, ensure_ascii=False, indent=2)

    rejected_path = Path(output_path).parent / "rejected_candidates.json"
    with open(rejected_path, "w", encoding="utf-8") as f:
        json.dump(rejected, f, ensure_ascii=False, indent=2)

    return {
        "summary": {
            "candidates": len(candidates),
            "rejected": len(rejected),
            "total_disagreements": sum(len(v) for v in disagreement_groups.values()),
        }
    }


def _predicate_matches(pred: dict, fv: dict) -> bool:
    """Check if a feature view matches a predicate."""
    for key, val in pred.items():
        if isinstance(val, list):
            if fv.get(key) not in val:
                return False
        elif isinstance(val, bool):
            if fv.get(key) != val:
                return False
        else:
            if fv.get(key) != val:
                return False
    return True


def _predicate_description(pred: dict) -> str:
    """Human-readable description of a predicate."""
    parts = []
    if "result" in pred:
        parts.append(f"result={pred['result']}")
    if "opponent_quality" in pred:
        parts.append(f"vs {pred['opponent_quality']}")
    if "dominant_chance_quality" in pred and pred["dominant_chance_quality"]:
        parts.append("机会质量占优")
    if "low_defensive_risk" in pred and pred["low_defensive_risk"]:
        parts.append("防守风险低")
    if "clean_sheet" in pred and pred["clean_sheet"]:
        parts.append("零封")
    return "、".join(parts) if parts else "特定条件"


# ── Phase 3: replay-wk-candidates ────────────────────────────────────


def run_replay_wk_candidates(
    kb_path: str,
    adjudication_path: str,
    candidates_path: str,
    output_path: str,
) -> dict:
    """Dry-run replay: simulate applying candidate rules to WK signals."""
    entries = _load_kb(kb_path)
    kb_index = _build_kb_index(entries)

    with open(adjudication_path, encoding="utf-8") as f:
        adjudication = json.load(f)
    with open(candidates_path, encoding="utf-8") as f:
        candidates = json.load(f)

    # Get clean subset rows
    clean_rows = [r for r in adjudication.get("rows", []) if r["status"] not in ("missing_evaluator_b", "invalid_evaluator_b")]

    # Simulate applying candidates
    def apply_candidates(wk: dict, fv: dict) -> dict:
        """Apply candidate rules to a WK signal dict (in-memory)."""
        result = {
            "overall_signal": wk.get("overall_signal", ""),
            "dimension_signals": dict(wk.get("dimension_signals", {})),
            "model_signals": dict(wk.get("model_signals", {})),
        }
        for cand in candidates:
            if _predicate_matches(cand["predicate"], fv):
                target = cand["target"]
                target_signal = cand["target_signal"]
                if target == "overall_signal":
                    result["overall_signal"] = target_signal
                elif target.startswith("dimension_signals."):
                    dim = target.split(".")[1]
                    if dim in result["dimension_signals"]:
                        result["dimension_signals"][dim] = target_signal
                elif target.startswith("model_signals."):
                    model = target.split(".")[1]
                    if model in result["model_signals"]:
                        result["model_signals"][model] = target_signal
        return result

    # Compute before/after metrics
    before_overall_agree = 0
    after_overall_agree = 0
    before_dim_agree = 0
    after_dim_agree = 0
    before_model_agree = 0
    after_model_agree = 0
    before_wk_too_harsh = 0
    after_wk_too_harsh = 0
    before_wk_too_generous = 0
    after_wk_too_generous = 0
    candidate_impacts = []
    regression_results = []

    for row in clean_rows:
        entry = kb_index.get(row["match_id"])
        if not entry:
            continue

        fv = _derive_feature_view(entry)
        wk = row["wk"]
        b = row["b"]
        new_wk = apply_candidates(wk, fv)

        # Before metrics
        if row["status"] not in ("missing_evaluator_b", "invalid_evaluator_b"):
            if "overall" not in row["differences"] or not row["differences"]:
                before_overall_agree += 1
            if row["status"] in ("agreement_high_confidence", "agreement_low_confidence", "model_level_disagreement"):
                before_dim_agree += 1
            if row["status"] in ("agreement_high_confidence", "agreement_low_confidence"):
                before_model_agree += 1
            if row["status"] == "wk_too_harsh":
                before_wk_too_harsh += 1
            if row["status"] == "wk_too_generous":
                before_wk_too_generous += 1

        # After: compare new_wk vs B
        new_diffs = []
        if new_wk["overall_signal"] != b["overall_signal"]:
            new_diffs.append("overall")
        for dim in ("execution", "adjustment", "satisfaction"):
            if new_wk["dimension_signals"].get(dim) != b["dimension_signals"].get(dim):
                new_diffs.append(dim)
        for mk in ("1", "2", "3", "4", "5", "6"):
            if new_wk["model_signals"].get(mk) != b["model_signals"].get(mk):
                new_diffs.append(mk)

        if not new_diffs:
            after_overall_agree += 1
            after_dim_agree += 1
            after_model_agree += 1
        elif "overall" not in new_diffs:
            after_overall_agree += 1
            dim_diffs_new = [d for d in new_diffs if d in ("execution", "adjustment", "satisfaction")]
            if not dim_diffs_new:
                after_dim_agree += 1
                after_model_agree += 1
            else:
                model_diffs_new = [d for d in new_diffs if d in ("1", "2", "3", "4", "5", "6")]
                if not model_diffs_new:
                    after_model_agree += 1
        else:
            # Overall mismatch
            wk_rank = _signal_rank(new_wk["overall_signal"])
            b_rank = _signal_rank(b["overall_signal"])
            if wk_rank < b_rank:
                after_wk_too_harsh += 1
            elif wk_rank > b_rank:
                after_wk_too_generous += 1

        # Track per-match changes
        if new_wk != wk:
            candidate_impacts.append({
                "match_id": row["match_id"],
                "before": wk,
                "after": new_wk,
                "b_signals": b,
            })

        # Regression check: 1531572 must not become overall 🟢
        if row["match_id"] == "1531572" and new_wk["overall_signal"] == "🟢":
            regression_results.append({"match_id": "1531572", "passed": False, "reason": "became overall 🟢"})
        elif row["match_id"] == "1531572":
            regression_results.append({"match_id": "1531572", "passed": True})

        # Lower/mid_table loss guard
        if (fv.get("result") == "L" and fv.get("opponent_quality") in ("lower", "mid_table", "unknown")
                and new_wk["overall_signal"] == "🟢"):
            regression_results.append({"match_id": row["match_id"], "passed": False, "reason": "loss to lower/mid_table became overall 🟢"})

    n = len(clean_rows)
    report = {
        "dry_run": True,
        "weak_label_from": "v1.1",
        "weak_label_candidate": "v1.2",
        "basis": "b-003 clean subset",
        "compared": n,
        "before": {
            "overall_agreement_rate": round(before_overall_agree / n, 4) if n else 0,
            "dimension_agreement_rate": round(before_dim_agree / n, 4) if n else 0,
            "model_agreement_rate": round(before_model_agree / n, 4) if n else 0,
            "wk_too_harsh": before_wk_too_harsh,
            "wk_too_generous": before_wk_too_generous,
        },
        "after": {
            "overall_agreement_rate": round(after_overall_agree / n, 4) if n else 0,
            "dimension_agreement_rate": round(after_dim_agree / n, 4) if n else 0,
            "model_agreement_rate": round(after_model_agree / n, 4) if n else 0,
            "wk_too_harsh": after_wk_too_harsh,
            "wk_too_generous": after_wk_too_generous,
        },
        "candidate_impacts": candidate_impacts,
        "regression_results": regression_results,
    }

    # Generate regression manifest
    manifest = _build_regression_manifest(clean_rows, kb_index)
    manifest_path = Path(output_path).parent / "regression_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # Check if replay passes
    b = report["before"]
    a = report["after"]
    all_regressions_pass = all(r["passed"] for r in regression_results) if regression_results else True
    harsh_rel_decrease = (b["wk_too_harsh"] - a["wk_too_harsh"]) / b["wk_too_harsh"] if b["wk_too_harsh"] > 0 else 1.0
    generous_abs_increase = a["wk_too_generous"] - b["wk_too_generous"]

    passes = (
        n >= 90
        and a["overall_agreement_rate"] >= b["overall_agreement_rate"]
        and a["dimension_agreement_rate"] >= b["dimension_agreement_rate"]
        and a["model_agreement_rate"] >= b["model_agreement_rate"]
        and harsh_rel_decrease >= 0.20
        and generous_abs_increase <= 2
        and all_regressions_pass
    )

    return {
        "summary": {
            "compared": n,
            "before": b,
            "after": a,
            "passes": passes,
            "regressions_passed": all_regressions_pass,
            "candidate_impacts": len(candidate_impacts),
        }
    }


def _build_regression_manifest(clean_rows: list[dict], kb_index: dict) -> dict:
    """Build regression manifest from clean subset rows."""
    must_not_green = [{"match_id": "1531572", "reason": "dominant stats + loss to lower opposition must not become green"}]

    win_regression = {"top6": [], "european_elite": [], "mid_table_away": [], "lower_home": []}
    for row in clean_rows:
        entry = kb_index.get(row["match_id"])
        if not entry:
            continue
        fv = _derive_feature_view(entry)
        if fv.get("result") != "W":
            continue
        opp = fv.get("opponent_quality", "unknown")
        venue = fv.get("venue", "unknown")
        if opp == "top6" and len(win_regression["top6"]) < 2:
            win_regression["top6"].append(row["match_id"])
        elif opp == "european_elite" and len(win_regression["european_elite"]) < 2:
            win_regression["european_elite"].append(row["match_id"])
        elif opp == "mid_table" and venue == "away" and len(win_regression["mid_table_away"]) < 2:
            win_regression["mid_table_away"].append(row["match_id"])
        elif opp == "lower" and venue == "home" and len(win_regression["lower_home"]) < 2:
            win_regression["lower_home"].append(row["match_id"])

    win_regression_set = []
    for category, ids in win_regression.items():
        for mid in ids:
            win_regression_set.append({"match_id": mid, "category": category})

    # Add loss guards to must_not
    for row in clean_rows:
        entry = kb_index.get(row["match_id"])
        if not entry:
            continue
        fv = _derive_feature_view(entry)
        if fv.get("result") == "L" and fv.get("opponent_quality") in ("lower", "mid_table"):
            must_not_green.append({
                "match_id": row["match_id"],
                "reason": f"loss to {fv.get('opponent_quality')} opposition must not become overall green due to dominance metrics",
            })

    return {
        "must_not_become_green_overall": must_not_green,
        "loss_guard": {"rule": "loss to lower/mid_table opposition cannot become overall green because of dominance metrics"},
        "win_regression_set": win_regression_set,
        "quarantined_excluded": ["1208103", "1208118", "1208215", "1208233", "1208326", "1379169", "1379251", "1518728"],
    }


# ── Phase 5: propose-wk-patch-spec ───────────────────────────────────


def run_propose_wk_patch_spec(
    candidates_path: str,
    replay_path: str,
    regression_manifest_path: str,
    output_path: str,
) -> dict:
    """Generate WK v1.2 implementation spec if replay passes."""
    with open(replay_path, encoding="utf-8") as f:
        replay = json.load(f)
    with open(candidates_path, encoding="utf-8") as f:
        candidates = json.load(f)
    with open(regression_manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    # Check if replay passes
    b = replay.get("before", {})
    a = replay.get("after", {})
    n = replay.get("compared", 0)
    all_regressions = all(r.get("passed", True) for r in replay.get("regression_results", []))
    harsh_rel = (b.get("wk_too_harsh", 0) - a.get("wk_too_harsh", 0)) / b.get("wk_too_harsh", 1) if b.get("wk_too_harsh", 0) > 0 else 1.0
    generous_abs = a.get("wk_too_generous", 0) - b.get("wk_too_generous", 0)

    passes = (
        n >= 90
        and a.get("overall_agreement_rate", 0) >= b.get("overall_agreement_rate", 0)
        and a.get("dimension_agreement_rate", 0) >= b.get("dimension_agreement_rate", 0)
        and a.get("model_agreement_rate", 0) >= b.get("model_agreement_rate", 0)
        and harsh_rel >= 0.20
        and generous_abs <= 2
        and all_regressions
    )

    if not passes:
        # Write rejected
        rejected_path = Path(output_path).parent / "rejected_candidates.json"
        if rejected_path.exists():
            pass  # Already written by distill
        return {"generated": False, "reason": "replay did not pass criteria"}

    # Generate spec
    candidate_ids = [c["id"] for c in candidates]
    regression_ids = [r["match_id"] for r in manifest.get("must_not_become_green_overall", [])]

    spec = f"""# WK v1.2 Implementation Spec

Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
Status: 待实现
Source: wk-v1.2 rule distillation pipeline

## Background

b-003 clean-subset validation passed (5/5 criteria, 94 match_ids).
{len(candidates)} rule candidates passed distillation gates.
Dry-run replay passed all criteria.

## Candidates

"""
    for c in candidates:
        spec += f"### {c['id']}\n\n"
        spec += f"- Target: `{c['target']}`\n"
        spec += f"- Direction: {c['direction']}\n"
        spec += f"- Predicate: `{json.dumps(c['predicate'], ensure_ascii=False)}`\n"
        spec += f"- Current: {c['current_wk_signal']} → Target: {c['target_signal']}\n"
        spec += f"- Support: {c['support']}, Precision: {c['precision_vs_b']}, FP: {c['false_positive_count']}\n"
        spec += f"- Examples: {', '.join(c['examples'])}\n"
        spec += f"- Risk: {c['risk']}\n"
        spec += f"- Rationale: {c['rationale']}\n\n"

    spec += """## Regression Guards

Must NOT become overall 🟢:
"""
    for r in manifest.get("must_not_become_green_overall", [])[:10]:
        spec += f"- `{r['match_id']}`: {r['reason']}\n"

    spec += f"""
## Dry-Run Results

- Compared: {n}
- Overall agreement: {b.get('overall_agreement_rate', 0):.1%} → {a.get('overall_agreement_rate', 0):.1%}
- Dimension agreement: {b.get('dimension_agreement_rate', 0):.1%} → {a.get('dimension_agreement_rate', 0):.1%}
- Model agreement: {b.get('model_agreement_rate', 0):.1%} → {a.get('model_agreement_rate', 0):.1%}
- wk_too_harsh: {b.get('wk_too_harsh', 0)} → {a.get('wk_too_harsh', 0)}
- wk_too_generous: {b.get('wk_too_generous', 0)} → {a.get('wk_too_generous', 0)}

## Version Bump

weak_label_version: v1.1 → v1.2

## Non-Goals

- Do NOT modify evaluator B prompts
- Do NOT re-run evaluations
- Do NOT write to knowledge.json until implementation is reviewed
"""

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(spec)

    return {"generated": True, "candidates": len(candidate_ids)}

if __name__ == "__main__":
    main()
