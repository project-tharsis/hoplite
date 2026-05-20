#!/usr/bin/env python3
"""Historical backfill seed-set pipeline.

Modes:
    inventory        Read KB + manifest, print JSON report. No writes.
    prepare-seed     Load raw/report JSON, run prepare_evaluation, write JSONL artifacts.
    apply-features   Apply prepared features/weak_labels to KB entries. Requires --run, --write.
    validate-rest    Dry-run prepare for validation-set entries. No KB mutation.

Usage:
    python scripts/backfill_history.py \
        --kb data/knowledge.json \
        --manifest data/backfill/backfill_manifest.json \
        --mode inventory

    python scripts/backfill_history.py \
        --kb data/knowledge.json \
        --manifest data/backfill/backfill_manifest.json \
        --mode prepare-seed \
        --output data/backfill/runs/20260519-seed

    python scripts/backfill_history.py \
        --kb data/knowledge.json \
        --manifest data/backfill/backfill_manifest.json \
        --mode apply-features \
        --run data/backfill/runs/20260519-seed \
        --write

    python scripts/backfill_history.py \
        --kb data/knowledge.json \
        --manifest data/backfill/backfill_manifest.json \
        --mode validate-rest \
        --output data/backfill/runs/20260519-validate
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ── Error codes ────────────────────────────────────────────────────

ERROR_CODES = {
    "LEGACY_ENTRY_NOT_FOUND",
    "MISSING_RAW_INPUT",
    "RAW_FILE_NOT_FOUND",
    "REPORT_FILE_NOT_FOUND",
    "FETCH_NOT_IMPLEMENTED",
    "FETCH_FAILED",
    "ANALYZE_FAILED",
    "PREPARE_FAILED",
    "FEATURES_EMPTY",
    "DUPLICATE_FIXTURE_ID",
    "WRITE_REQUIRES_FLAG",
}


# ── Helpers ────────────────────────────────────────────────────────


def _load_kb(kb_path: str) -> list[dict]:
    with open(kb_path, encoding="utf-8") as f:
        return json.load(f)


def _load_manifest(manifest_path: str) -> dict:
    with open(manifest_path, encoding="utf-8") as f:
        return json.load(f)


def _build_kb_index(entries: list[dict]) -> dict[str, dict]:
    """Index KB entries by match_id."""
    idx: dict[str, dict] = {}
    for e in entries:
        mid = str(e.get("match_id", ""))
        idx[mid] = e
    return idx


def _detect_missing_input(seed_row: dict) -> str | None:
    """Return error code if seed row lacks raw/report path, else None.

    fixture_id alone is not sufficient — raw_match_path or report_path required.
    """
    has_raw = bool(seed_row.get("raw_match_path"))
    has_report = bool(seed_row.get("report_path"))
    if not has_raw and not has_report:
        return "MISSING_RAW_INPUT"
    return None


# ── Inventory mode ─────────────────────────────────────────────────


def run_inventory(kb_path: str, manifest_path: str) -> dict:
    """Read KB and manifest, produce inventory report. No writes."""
    entries = _load_kb(kb_path)
    manifest = _load_manifest(manifest_path)
    kb_index = _build_kb_index(entries)

    total = len(entries)
    with_features = sum(1 for e in entries if e.get("features"))
    with_weak_labels = sum(1 for e in entries if e.get("weak_labels"))
    legacy_only = total - with_features

    seed_set = manifest.get("seed_set", [])
    validation_set = manifest.get("validation_set", [])

    # Seed entries missing raw/report input
    seed_missing_input: list[dict] = []
    for row in seed_set:
        err = _detect_missing_input(row)
        if err:
            seed_missing_input.append({
                "legacy_match_id": row.get("legacy_match_id"),
                "error_code": err,
            })

    # Legacy IDs in manifest not found in KB
    manifest_ids_not_in_kb: list[str] = []
    all_manifest_rows = seed_set + validation_set
    for row in all_manifest_rows:
        mid = str(row.get("legacy_match_id", ""))
        if mid and mid not in kb_index:
            manifest_ids_not_in_kb.append(mid)

    # Duplicate fixture IDs
    fixture_ids = [row.get("fixture_id") for row in all_manifest_rows if row.get("fixture_id") is not None]
    fixture_counts = Counter(fixture_ids)
    duplicate_fixture_ids = [fid for fid, cnt in fixture_counts.items() if cnt > 1]

    return {
        "kb": {
            "total_entries": total,
            "entries_with_features": with_features,
            "entries_with_weak_labels": with_weak_labels,
            "legacy_only_entries": legacy_only,
        },
        "manifest": {
            "seed_set_count": len(seed_set),
            "validation_set_count": len(validation_set),
        },
        "issues": {
            "seed_entries_missing_input": seed_missing_input,
            "manifest_ids_not_in_kb": manifest_ids_not_in_kb,
            "duplicate_fixture_ids": duplicate_fixture_ids,
        },
    }


# ── Prepare-seed mode ──────────────────────────────────────────────


def run_prepare_seed(
    kb_path: str,
    manifest_path: str,
    output_dir: str,
    *,
    dry_run: bool = True,
) -> dict:
    """Load raw/report JSON for seed-set entries, run prepare_evaluation, write JSONL."""
    from src.tools.prepare_evaluation import prepare_evaluation
    from src.tools.analyze import analyze_match

    entries = _load_kb(kb_path)
    manifest = _load_manifest(manifest_path)
    kb_index = _build_kb_index(entries)
    seed_set = manifest.get("seed_set", [])

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    prepare_results_path = out / "prepare_results.jsonl"
    llm_jobs_path = out / "llm_jobs.jsonl"

    prepare_rows: list[dict] = []
    llm_job_rows: list[dict] = []
    summary = {"total": len(seed_set), "ok": 0, "errors": 0}

    for row in seed_set:
        legacy_id = str(row.get("legacy_match_id", ""))
        fixture_id = row.get("fixture_id")
        fixture_id_str = str(fixture_id) if fixture_id is not None else ""
        raw_path = row.get("raw_match_path")
        report_path = row.get("report_path")
        opponent = row.get("opponent", "")
        date = row.get("date", "")

        # Check KB entry exists
        if legacy_id not in kb_index:
            prepare_rows.append({
                "legacy_match_id": legacy_id,
                "fixture_id": fixture_id_str,
                "ok": False,
                "error": {
                    "code": "LEGACY_ENTRY_NOT_FOUND",
                    "message": f"Legacy match_id '{legacy_id}' not found in KB",
                },
            })
            summary["errors"] += 1
            continue

        # Check for input
        has_raw = bool(raw_path)
        has_report = bool(report_path)

        if not has_raw and not has_report:
            prepare_rows.append({
                "legacy_match_id": legacy_id,
                "fixture_id": fixture_id_str,
                "ok": False,
                "error": {
                    "code": "MISSING_RAW_INPUT",
                    "message": "No raw_match_path or report_path provided",
                },
            })
            summary["errors"] += 1
            continue

        # Load input data
        input_data = None
        input_type = None

        if has_report:
            rp = Path(report_path)
            if not rp.exists():
                prepare_rows.append({
                    "legacy_match_id": legacy_id,
                    "fixture_id": fixture_id_str,
                    "ok": False,
                    "error": {
                        "code": "REPORT_FILE_NOT_FOUND",
                        "message": f"Report file not found: {report_path}",
                    },
                })
                summary["errors"] += 1
                continue
            with open(rp, encoding="utf-8") as f:
                input_data = json.load(f)
            input_type = "report"

        if input_data is None and has_raw:
            rp = Path(raw_path)
            if not rp.exists():
                prepare_rows.append({
                    "legacy_match_id": legacy_id,
                    "fixture_id": fixture_id_str,
                    "ok": False,
                    "error": {
                        "code": "RAW_FILE_NOT_FOUND",
                        "message": f"Raw match file not found: {raw_path}",
                    },
                })
                summary["errors"] += 1
                continue
            with open(rp, encoding="utf-8") as f:
                input_data = json.load(f)
            input_type = "raw_match"

        # If only raw match, run analyze_match to get report
        report_json = None
        if input_type == "raw_match":
            try:
                analyze_result = analyze_match(input_data)
                if analyze_result.get("ok"):
                    report_json = analyze_result.get("report")
                    # Merge KB pre_match_context into report context as ground truth
                    # (extract_context may misclassify opponent_quality from raw team names)
                    kb_entry = kb_index.get(legacy_id, {})
                    kb_context = kb_entry.get("pre_match_context", {})
                    if report_json and kb_context:
                        report_context = report_json.get("context", {})
                        for key in ("opponent_quality", "venue", "competition_stage", "opponent"):
                            if kb_context.get(key) and kb_context[key] != "unknown":
                                report_context[key] = kb_context[key]
                        report_json["context"] = report_context
                    # Merge KB predicted_plan if available
                    kb_plan = kb_entry.get("predicted_plan")
                    if report_json and kb_plan:
                        report_json["predicted_plan"] = kb_plan
                    # Save report snapshot for reproducibility
                    if report_json and fixture_id_str:
                        reports_dir = Path(output_dir) / "reports"
                        reports_dir.mkdir(parents=True, exist_ok=True)
                        report_snapshot_path = str(reports_dir / f"{fixture_id_str}.json")
                        with open(report_snapshot_path, "w", encoding="utf-8") as rf:
                            json.dump(report_json, rf, indent=2, ensure_ascii=False)
                        report_path = report_snapshot_path  # update to point at saved snapshot
                else:
                    prepare_rows.append({
                        "legacy_match_id": legacy_id,
                        "fixture_id": fixture_id_str,
                        "ok": False,
                        "error": {
                        "code": "ANALYZE_FAILED",
                        "message": f"analyze_match failed: {analyze_result.get('error', {}).get('message', 'unknown')}",
                        },
                    })
                    summary["errors"] += 1
                    continue
            except Exception as e:
                prepare_rows.append({
                    "legacy_match_id": legacy_id,
                    "fixture_id": fixture_id_str,
                    "ok": False,
                    "error": {
                        "code": "ANALYZE_FAILED",
                        "message": f"analyze_match exception: {e}",
                    },
                })
                summary["errors"] += 1
                continue
            # Use report (with merged KB context) for prepare_evaluation
            eval_input = report_json if report_json else input_data
        else:
            # Report input — use as-is for prepare_evaluation
            eval_input = input_data

        # Run prepare_evaluation
        try:
            result = prepare_evaluation(eval_input, output_format="json")
        except Exception as e:
            prepare_rows.append({
                "legacy_match_id": legacy_id,
                "fixture_id": fixture_id_str,
                "ok": False,
                "error": {
                    "code": "PREPARE_FAILED",
                    "message": f"prepare_evaluation exception: {e}",
                },
            })
            summary["errors"] += 1
            continue

        if not result.get("ok"):
            prepare_rows.append({
                "legacy_match_id": legacy_id,
                "fixture_id": fixture_id_str,
                "ok": False,
                "error": result.get("error", {"code": "PREPARE_FAILED", "message": "unknown"}),
            })
            summary["errors"] += 1
            continue

        features = result.get("features", {})
        weak_labels = result.get("weak_labels", {})
        rubric_version = result.get("rubric_version", "arteta_v1")
        prompt = result.get("prompt", "")

        if not features:
            prepare_rows.append({
                "legacy_match_id": legacy_id,
                "fixture_id": fixture_id_str,
                "ok": False,
                "error": {
                    "code": "FEATURES_EMPTY",
                    "message": "prepare_evaluation returned empty features",
                },
            })
            summary["errors"] += 1
            continue

        # Success row
        prepare_rows.append({
            "legacy_match_id": legacy_id,
            "fixture_id": fixture_id_str,
            "ok": True,
            "input_type": input_type,
            "features": features,
            "weak_labels": weak_labels,
            "rubric_version": rubric_version,
            "features_version": "v2",
            "prompt": prompt,
            "raw_match_path": raw_path or "",
            "report_path": report_path or "",
        })
        summary["ok"] += 1

        # LLM job row
        llm_job_rows.append({
            "legacy_match_id": legacy_id,
            "fixture_id": fixture_id_str,
            "opponent": opponent,
            "date": date,
            "prompt": prompt,
            "features": features,
            "weak_labels": weak_labels,
            "report_path": report_path or "",
            "expected_output_schema": "strict_v2_evaluation",
        })

    # Write JSONL files
    with open(prepare_results_path, "w", encoding="utf-8") as f:
        for row in prepare_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    with open(llm_jobs_path, "w", encoding="utf-8") as f:
        for row in llm_job_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    return {
        "summary": summary,
        "prepare_results_path": str(prepare_results_path),
        "llm_jobs_path": str(llm_jobs_path),
        "dry_run": dry_run,
    }


# ── Apply-features mode ─────────────────────────────────────────────


def _majority_vote(dimension_signals: dict) -> str:
    """Compute overall_signal by majority vote of dimension signals."""
    counts: Counter = Counter()
    for v in dimension_signals.values():
        if v in ("🟢", "🟡", "🔴"):
            counts[v] += 1
    if counts.get("🟢", 0) >= 2:
        return "🟢"
    if counts.get("🔴", 0) >= 2:
        return "🔴"
    return "🟡"


_LEGACY_SIGNAL_MAP = {
    "green": "🟢",
    "yellow": "🟡",
    "neutral": "🟡",
    "red": "🔴",
}


def _normalize_signal_emoji(value: str | None) -> str | None:
    """Convert legacy text signals (green/yellow/red/neutral) to emoji."""
    if value is None:
        return None
    lower = value.lower().strip()
    return _LEGACY_SIGNAL_MAP.get(lower, value)  # pass through if already emoji


def _needs_eval_normalization(evaluation: dict) -> bool:
    """Return True if evaluation uses legacy dimension fields and lacks dimension_signals."""
    has_legacy = any(
        evaluation.get(k) for k in ("execution_signal", "adjustment_signal", "satisfaction_signal")
    )
    has_new = bool(evaluation.get("dimension_signals"))
    return has_legacy and not has_new


def _hydrate_top_level_metadata(
    entry: dict,
    features: dict,
    report_path: str | None = None,
) -> list[str]:
    """Hydrate KB top-level metadata from features and report snapshot.

    Feature-backed entries may have empty top-level fields (opponent, result,
    score, competition, pre_match_context) even though the features dict is
    complete.  PatternComputer reads these top-level fields — not the nested
    features — for filtering (_filter_by_context) and aggregation
    (_compute_aggregate_stats).  Missing metadata silently breaks calibration.

    Returns list of field names that were hydrated.
    """
    hydrated: list[str] = []

    # ── opponent ──────────────────────────────────────────────────────
    if not entry.get("opponent"):
        opponent = features.get("opponent_name", "")
        if opponent:
            entry["opponent"] = opponent
            hydrated.append("opponent")

    # ── result ────────────────────────────────────────────────────────
    if not entry.get("result"):
        result = features.get("result", "")
        if result:
            entry["result"] = result
            hydrated.append("result")

    # ── score ─────────────────────────────────────────────────────────
    score = entry.get("score", "")
    if not score or score == "?-?":
        ag = features.get("arsenal_goals")
        og = features.get("opponent_goals")
        if ag is not None and og is not None:
            entry["score"] = f"{ag}-{og}"
            hydrated.append("score")

    # ── competition ───────────────────────────────────────────────────
    if not entry.get("competition"):
        competition = _read_report_field(report_path, ("match", "competition"))
        if competition:
            entry["competition"] = competition
            hydrated.append("competition")

    # ── timestamp / date ──────────────────────────────────────────────
    if not entry.get("timestamp"):
        ts = _read_report_field(report_path, ("match", "date"))
        if ts:
            entry["timestamp"] = ts
            hydrated.append("timestamp")

    # ── pre_match_context ─────────────────────────────────────────────
    pmc = entry.get("pre_match_context")
    if not pmc:
        pmc = {}
        entry["pre_match_context"] = pmc

    pmc_fields = {
        "opponent_quality": features.get("opponent_quality", ""),
        "venue": features.get("venue", ""),
        "competition_stage": features.get("competition_stage", ""),
    }
    for key, value in pmc_fields.items():
        if not pmc.get(key) and value:
            pmc[key] = value
            hydrated.append(f"pre_match_context.{key}")

    # Also hydrate opponent in pre_match_context if present in features
    if not pmc.get("opponent"):
        opponent_name = features.get("opponent_name", "")
        if opponent_name:
            pmc["opponent"] = opponent_name
            hydrated.append("pre_match_context.opponent")

    return hydrated


def _read_report_field(report_path: str | None, keys: tuple[str, ...]) -> str | None:
    """Read a nested field from a report JSON snapshot.

    Returns None if the file doesn't exist or the path is absent.
    """
    if not report_path:
        return None
    try:
        p = Path(report_path)
        if not p.exists():
            return None
        with open(p, encoding="utf-8") as f:
            report = json.load(f)
        node = report
        for key in keys:
            node = node.get(key, {}) if isinstance(node, dict) else {}
        return node if isinstance(node, str) and node else None
    except (OSError, json.JSONDecodeError, TypeError, KeyError):
        return None


def run_apply_features(
    kb_path: str,
    manifest_path: str,
    run_dir: str,
    *,
    force: bool = False,
    dry_run: bool = True,
) -> dict:
    """Apply prepared features/weak_labels to KB entries listed in seed set.

    Reads prepare_results.jsonl from *run_dir*.
    Writes knowledge.before.json, knowledge.after.json, apply_report.json into *run_dir*.
    Mutates kb_path only when *dry_run* is False.
    """
    entries = _load_kb(kb_path)
    manifest = _load_manifest(manifest_path)
    kb_index = _build_kb_index(entries)
    seed_set = manifest.get("seed_set", [])

    # Build set of seed-set legacy_match_ids for safety
    seed_ids = {str(row.get("legacy_match_id", "")) for row in seed_set}

    run_path = Path(run_dir)
    prepare_results_path = run_path / "prepare_results.jsonl"
    if not prepare_results_path.exists():
        return {"error": f"prepare_results.jsonl not found in {run_dir}"}

    # Read prepare results
    prepare_rows: list[dict] = []
    with open(prepare_results_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                prepare_rows.append(json.loads(line))

    # Build lookup: legacy_match_id → prepare result (successful only)
    prepare_by_id: dict[str, dict] = {}
    for row in prepare_rows:
        if row.get("ok"):
            prepare_by_id[str(row["legacy_match_id"])] = row

    # Snapshot KB before
    run_path.mkdir(parents=True, exist_ok=True)
    before_path = run_path / "knowledge.before.json"
    with open(before_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)

    now_iso = datetime.now().isoformat(timespec="seconds")
    run_id = run_path.name

    applied: list[dict] = []
    skipped: list[dict] = []
    errors: list[dict] = []

    for entry in entries:
        mid = str(entry.get("match_id", ""))
        if mid not in seed_ids:
            continue  # Never touch entries not in seed set
        if mid not in prepare_by_id:
            continue  # No successful prepare result

        prep = prepare_by_id[mid]

        # Idempotency: skip features/weak_labels write if already populated unless --force
        already_backfilled = (
            not force and entry.get("features") and entry.get("weak_labels")
        )
        if already_backfilled:
            # Still hydrate metadata even for already-backfilled entries
            report_path = prep.get("report_path", "")
            hydrated_fields = _hydrate_top_level_metadata(
                entry, prep.get("features", {}), report_path or None
            )
            if hydrated_fields:
                applied.append({
                    "legacy_match_id": mid,
                    "hydrated_fields": hydrated_fields,
                })
            else:
                skipped.append({"legacy_match_id": mid, "reason": "already_backfilled_no_missing_metadata"})
            continue

        # Apply features and weak_labels
        entry["features"] = prep["features"]
        entry["weak_labels"] = prep["weak_labels"]

        # Hydrate top-level metadata from features + report snapshot
        report_path = prep.get("report_path", "")
        hydrated_fields = _hydrate_top_level_metadata(
            entry, prep["features"], report_path or None
        )

        # Version fields
        entry["features_version"] = prep.get("features_version", "v1")
        entry["weak_label_version"] = prep.get("weak_labels", {}).get("weak_label_version", "v1.1")
        entry["rubric_version"] = prep.get("rubric_version", "arteta_v1")
        entry["prompt_builder_version"] = "v1"

        # Backfill metadata
        manifest_row = None
        for row in seed_set:
            if str(row.get("legacy_match_id", "")) == mid:
                manifest_row = row
                break

        entry["backfill"] = {
            "status": "feature_backfilled",
            "run_id": run_id,
            "legacy_match_id": mid,
            "fixture_id": str(manifest_row.get("fixture_id", "")) if manifest_row else prep.get("fixture_id", ""),
            "raw_match_path": prep.get("raw_match_path", ""),
            "report_path": prep.get("report_path", ""),
            "prepared_at": now_iso,
            "needs_v2_evaluation": True,
        }

        # Normalize legacy evaluation if needed
        evaluation = entry.get("evaluation", {})
        if _needs_eval_normalization(evaluation):
            # Copy original into legacy_evaluation
            entry["legacy_evaluation"] = dict(evaluation)
            # Build normalized evaluation
            dim_signals = {
                "execution": _normalize_signal_emoji(evaluation.get("execution_signal")),
                "adjustment": _normalize_signal_emoji(evaluation.get("adjustment_signal")),
                "satisfaction": _normalize_signal_emoji(evaluation.get("satisfaction_signal")),
            }
            # Normalize model_signals to emoji
            raw_model_signals = evaluation.get("model_signals", {})
            normalized_model_signals = {
                k: _normalize_signal_emoji(v) for k, v in raw_model_signals.items()
            }
            new_eval = {
                "source": "legacy",
                "model_signals": normalized_model_signals,
                "dimension_signals": dim_signals,
                "overall_signal": _majority_vote(dim_signals),
                "narrative": evaluation.get("narrative", ""),
            }
            entry["evaluation"] = new_eval
        else:
            # Even if not legacy-shape, normalize any remaining text signals
            # in model_signals, dimension_signals, and overall_signal
            changed = False
            model_signals = evaluation.get("model_signals", {})
            if model_signals:
                new_ms = {}
                for k, v in model_signals.items():
                    nv = _normalize_signal_emoji(v)
                    if nv != v:
                        changed = True
                    new_ms[k] = nv
                if changed:
                    entry["evaluation"]["model_signals"] = new_ms

            dim_signals = evaluation.get("dimension_signals", {})
            if dim_signals:
                new_ds = {}
                for k, v in dim_signals.items():
                    nv = _normalize_signal_emoji(v)
                    if nv != v:
                        changed = True
                    new_ds[k] = nv
                if changed:
                    entry["evaluation"]["dimension_signals"] = new_ds

            overall = evaluation.get("overall_signal")
            if overall:
                nv = _normalize_signal_emoji(overall)
                if nv != overall:
                    entry["evaluation"]["overall_signal"] = nv

        applied.append({
            "legacy_match_id": mid,
            "hydrated_fields": hydrated_fields,
        })

    # Write knowledge.after.json
    after_path = run_path / "knowledge.after.json"
    with open(after_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)

    # Write apply_report.json
    report = {
        "summary": {
            "total": len(prepare_rows),
            "applied": len(applied),
            "skipped": len(skipped),
            "errors": len(errors),
            "metadata_hydrated": sum(
                1 for a in applied if a.get("hydrated_fields")
            ),
            "total_fields_hydrated": sum(
                len(a.get("hydrated_fields", [])) for a in applied
            ),
        },
        "applied": applied,
        "skipped": skipped,
        "errors": errors,
    }
    report_path = run_path / "apply_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # Mutate KB only when not dry-run
    if not dry_run:
        _atomic_write_kb(kb_path, entries)

    return {
        "report": report,
        "knowledge_before_path": str(before_path),
        "knowledge_after_path": str(after_path),
        "apply_report_path": str(report_path),
        "dry_run": dry_run,
    }


def _atomic_write_kb(kb_path: str, entries: list[dict]) -> None:
    """Write KB atomically via temp file + rename."""
    import tempfile
    p = Path(kb_path)
    fd, tmp_name = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
        Path(tmp_name).replace(p)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise


# ── Refresh-features mode ────────────────────────────────────────────


def run_refresh_features(
    kb_path: str,
    output_dir: str,
    *,
    dry_run: bool = True,
) -> dict:
    """Re-extract v2 features for all feature-backed KB entries.

    Reads KB entries with features, finds raw JSON or report, re-extracts
    features using v2 extractor.  Writes updated features back to KB
    when --write is set.

    Outputs knowledge.before.json, knowledge.after.json, feature_diff_report.json
    into output_dir.  Skips legacy-only entries (no raw/report available).
    """
    from src.features.extractor import FeatureExtractor

    entries = _load_kb(kb_path)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Snapshot before
    before_path = out / "knowledge.before.json"
    with open(before_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)

    refreshed: list[dict] = []
    skipped: list[dict] = []
    errors: list[dict] = []
    diffs: list[dict] = []

    for entry in entries:
        mid = str(entry.get("match_id", ""))

        # Skip legacy-only entries
        if not entry.get("features"):
            skipped.append({"match_id": mid, "reason": "legacy_only_no_features"})
            continue

        # Skip human_override entries
        if entry.get("human_override"):
            skipped.append({"match_id": mid, "reason": "has_human_override"})
            continue

        # Find report or raw JSON
        backfill = entry.get("backfill", {})
        report_path = backfill.get("report_path", "")
        fixture_id = str(backfill.get("fixture_id", "") or mid)

        # Try report_path from backfill
        report_json = None
        if report_path and Path(report_path).is_file():
            try:
                with open(report_path, encoding="utf-8") as f:
                    report_json = json.load(f)
            except (OSError, json.JSONDecodeError):
                pass

        # Try common report locations if not found
        if report_json is None:
            # Look in data/backfill/runs/*/reports/<fixture_id>.json
            import glob
            patterns = [
                f"data/backfill/runs/*/reports/{fixture_id}.json",
                f"data/backfill/runs/*/reports/{mid}.json",
            ]
            for pattern in patterns:
                candidates = sorted(glob.glob(pattern))
                if candidates:
                    try:
                        with open(candidates[-1], encoding="utf-8") as f:
                            report_json = json.load(f)
                        break
                    except (OSError, json.JSONDecodeError):
                        continue

        if report_json is None:
            skipped.append({"match_id": mid, "reason": "no_raw_or_report_found"})
            continue

        # Re-extract features
        try:
            new_features = FeatureExtractor.extract_from_report(report_json)
            new_features_dict = new_features.to_dict()
        except Exception as e:
            errors.append({"match_id": mid, "error": str(e)})
            continue

        # Compute diff
        old_features = entry.get("features", {})
        diff = _compute_feature_diff(old_features, new_features_dict)
        if diff:
            diffs.append({"match_id": mid, "diff": diff})

        refreshed.append({
            "match_id": mid,
            "old_keys": sorted(old_features.keys()),
            "new_keys": sorted(new_features_dict.keys()),
            "has_diff": bool(diff),
        })

        # Update entry if not dry run
        if not dry_run:
            entry["features"] = new_features_dict
            entry["features_version"] = "v2"

    # Write after snapshot
    after_path = out / "knowledge.after.json"
    with open(after_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)

    # Write diff report
    diff_report = {
        "summary": {
            "total_entries": len(entries),
            "refreshed": len(refreshed),
            "skipped": len(skipped),
            "errors": len(errors),
            "entries_with_diff": len(diffs),
            "dry_run": dry_run,
        },
        "refreshed": refreshed,
        "skipped": skipped,
        "errors": errors,
        "diffs": diffs,
    }
    diff_report_path = out / "feature_diff_report.json"
    with open(diff_report_path, "w", encoding="utf-8") as f:
        json.dump(diff_report, f, ensure_ascii=False, indent=2)

    # Write KB if not dry run
    if not dry_run:
        _atomic_write_kb(kb_path, entries)

    return {
        "summary": diff_report["summary"],
        "knowledge_before_path": str(before_path),
        "knowledge_after_path": str(after_path),
        "feature_diff_report_path": str(diff_report_path),
        "dry_run": dry_run,
    }


def _compute_feature_diff(old: dict, new: dict) -> dict:
    """Compute diff between old and new feature dicts.

    Returns dict of changed keys with old/new values.
    """
    diff = {}
    all_keys = set(old.keys()) | set(new.keys())
    for key in sorted(all_keys):
        old_val = old.get(key)
        new_val = new.get(key)
        if old_val != new_val:
            diff[key] = {"old": old_val, "new": new_val}
    return diff


# ── Validate-rest mode ─────────────────────────────────────────────


def run_validate_rest(
    kb_path: str,
    manifest_path: str,
    output_dir: str,
) -> dict:
    """Dry-run prepare for validation-set entries and compare with legacy signals.

    Does NOT mutate KB.
    """
    from src.tools.prepare_evaluation import prepare_evaluation
    from src.tools.analyze import analyze_match

    entries = _load_kb(kb_path)
    manifest = _load_manifest(manifest_path)
    kb_index = _build_kb_index(entries)
    validation_set = manifest.get("validation_set", [])

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    comparisons: list[dict] = []
    skipped: list[dict] = []
    total = len(validation_set)

    for row in validation_set:
        legacy_id = str(row.get("legacy_match_id", ""))
        raw_path = row.get("raw_match_path")
        report_path = row.get("report_path")

        kb_entry = kb_index.get(legacy_id)
        if kb_entry is None:
            skipped.append({"legacy_match_id": legacy_id, "reason": "LEGACY_ENTRY_NOT_FOUND"})
            continue

        # Check for input
        has_raw = bool(raw_path)
        has_report = bool(report_path)
        if not has_raw and not has_report:
            skipped.append({"legacy_match_id": legacy_id, "reason": "MISSING_RAW_INPUT"})
            continue

        # Load input data
        input_data = None
        input_type = None

        if has_report:
            rp = Path(report_path)
            if not rp.exists():
                skipped.append({"legacy_match_id": legacy_id, "reason": "REPORT_FILE_NOT_FOUND"})
                continue
            with open(rp, encoding="utf-8") as f:
                input_data = json.load(f)
            input_type = "report"

        if input_data is None and has_raw:
            rp = Path(raw_path)
            if not rp.exists():
                skipped.append({"legacy_match_id": legacy_id, "reason": "RAW_FILE_NOT_FOUND"})
                continue
            with open(rp, encoding="utf-8") as f:
                input_data = json.load(f)
            input_type = "raw_match"

        # If only raw match, run analyze_match to get report
        if input_type == "raw_match":
            try:
                analyze_result = analyze_match(input_data)
                if analyze_result.get("ok"):
                    eval_input = input_data
                else:
                    skipped.append({"legacy_match_id": legacy_id, "reason": "ANALYZE_FAILED"})
                    continue
            except Exception as e:
                skipped.append({"legacy_match_id": legacy_id, "reason": f"ANALYZE_EXCEPTION: {e}"})
                continue
        else:
            eval_input = input_data

        # Run prepare_evaluation
        try:
            result = prepare_evaluation(eval_input, output_format="json")
        except Exception as e:
            skipped.append({"legacy_match_id": legacy_id, "reason": f"PREPARE_EXCEPTION: {e}"})
            continue

        if not result.get("ok"):
            skipped.append({"legacy_match_id": legacy_id, "reason": f"PREPARE_FAILED: {result.get('error', {}).get('code', 'unknown')}"})
            continue

        weak_labels = result.get("weak_labels", {})
        weak_label_signal = weak_labels.get("overall_signal", "🟡")

        # Get legacy signal
        evaluation = kb_entry.get("evaluation", {})
        legacy_signal = _extract_legacy_overall_signal(evaluation)

        # Model-level comparison
        weak_model_signals = weak_labels.get("model_signals", {})
        legacy_model_signals = evaluation.get("model_signals", {})
        all_model_keys = set(weak_model_signals.keys()) | set(legacy_model_signals.keys())
        model_differences: dict[str, dict] = {}
        for mk in sorted(all_model_keys):
            wl = weak_model_signals.get(mk)
            ll = legacy_model_signals.get(mk)
            if wl != ll:
                model_differences[mk] = {"weak_label": wl, "legacy": ll}

        comparisons.append({
            "legacy_match_id": legacy_id,
            "weak_label_signal": weak_label_signal,
            "legacy_signal": legacy_signal,
            "match": weak_label_signal == legacy_signal,
            "model_differences": model_differences,
        })

    report = {
        "summary": {
            "total": total,
            "compared": len(comparisons),
            "skipped": len(skipped),
        },
        "comparisons": comparisons,
        "skipped": skipped,
    }

    report_path = out / "validation_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    return {
        "report": report,
        "validation_report_path": str(report_path),
    }


def _extract_legacy_overall_signal(evaluation: dict) -> str:
    """Extract overall signal from evaluation, computing from dimension signals if needed."""
    # If overall_signal already exists, use it
    if evaluation.get("overall_signal"):
        return evaluation["overall_signal"]
    # Compute from dimension signals (new format)
    dim = evaluation.get("dimension_signals", {})
    if dim:
        return _majority_vote(dim)
    # Compute from legacy dimension fields
    legacy_dim = {
        "execution": evaluation.get("execution_signal"),
        "adjustment": evaluation.get("adjustment_signal"),
        "satisfaction": evaluation.get("satisfaction_signal"),
    }
    if any(legacy_dim.values()):
        return _majority_vote(legacy_dim)
    return "🟡"


# ── CLI ────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Historical backfill seed-set pipeline")
    parser.add_argument("--kb", required=True, help="Path to knowledge.json")
    parser.add_argument("--manifest", required=True, help="Path to backfill manifest")
    parser.add_argument("--mode", required=True,
                        choices=["inventory", "prepare-seed", "apply-features", "validate-rest", "refresh-features"],
                        help="Backfill mode")
    parser.add_argument("--output", help="Run directory for output files")
    parser.add_argument("--run", help="Existing run directory to read artifacts from (for apply-features)")
    parser.add_argument("--write", action="store_true",
                        help="Allow KB mutation (required for apply-features)")
    parser.add_argument("--force", action="store_true",
                        help="Allow replacing existing backfilled features")
    args = parser.parse_args()

    kb_path = args.kb
    manifest_path = args.manifest

    if not Path(kb_path).exists():
        print(json.dumps({"error": f"KB file not found: {kb_path}"}), file=sys.stderr)
        sys.exit(1)
    if not Path(manifest_path).exists():
        print(json.dumps({"error": f"Manifest file not found: {manifest_path}"}), file=sys.stderr)
        sys.exit(1)

    if args.mode == "inventory":
        report = run_inventory(kb_path, manifest_path)
        if args.output:
            od = Path(args.output)
            od.mkdir(parents=True, exist_ok=True)
            # Load manifest for snapshot
            manifest = _load_manifest(manifest_path)
            # Write manifest_snapshot.json
            with open(str(od / "manifest_snapshot.json"), "w", encoding="utf-8") as mf:
                json.dump(manifest, mf, indent=2, ensure_ascii=False)
            # Write inventory_report.json
            with open(str(od / "inventory_report.json"), "w", encoding="utf-8") as rf:
                json.dump(report, rf, indent=2, ensure_ascii=False)
        print(json.dumps(report, indent=2, ensure_ascii=False))

    elif args.mode == "prepare-seed":
        if not args.output:
            print(json.dumps({"error": "--output is required for prepare-seed mode"}), file=sys.stderr)
            sys.exit(1)
        result = run_prepare_seed(kb_path, manifest_path, args.output, dry_run=not args.write)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.mode == "apply-features":
        if not args.run:
            print(json.dumps({"error": "--run is required for apply-features mode"}), file=sys.stderr)
            sys.exit(1)
        result = run_apply_features(
            kb_path, manifest_path, args.run,
            force=args.force, dry_run=not args.write,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.mode == "validate-rest":
        if not args.output:
            print(json.dumps({"error": "--output is required for validate-rest mode"}), file=sys.stderr)
            sys.exit(1)
        result = run_validate_rest(kb_path, manifest_path, args.output)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.mode == "refresh-features":
        if not args.output:
            print(json.dumps({"error": "--output is required for refresh-features mode"}), file=sys.stderr)
            sys.exit(1)
        result = run_refresh_features(kb_path, args.output, dry_run=not args.write)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    else:
        print(json.dumps({"error": f"Unsupported mode: {args.mode}"}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
