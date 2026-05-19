#!/usr/bin/env python3
"""Historical backfill seed-set pipeline.

Modes:
    inventory       Read KB + manifest, print JSON report. No writes.
    prepare-seed    Load raw/report JSON, run prepare_evaluation, write JSONL artifacts.

Usage:
    python scripts/backfill_history.py \\
        --kb data/knowledge.json \\
        --manifest data/backfill/backfill_manifest.json \\
        --mode inventory

    python scripts/backfill_history.py \\
        --kb data/knowledge.json \\
        --manifest data/backfill/backfill_manifest.json \\
        --mode prepare-seed \\
        --output data/backfill/runs/20260519-seed
"""
from __future__ import annotations

import argparse
import json
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
    "PREPARE_FAILED",
    "FEATURES_EMPTY",
    "DUPLICATE_FIXTURE_ID",
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
                else:
                    prepare_rows.append({
                        "legacy_match_id": legacy_id,
                        "fixture_id": fixture_id_str,
                        "ok": False,
                        "error": {
                            "code": "PREPARE_FAILED",
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
                        "code": "PREPARE_FAILED",
                        "message": f"analyze_match exception: {e}",
                    },
                })
                summary["errors"] += 1
                continue
            # Use raw match data for prepare_evaluation
            eval_input = input_data
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


# ── CLI ────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Historical backfill seed-set pipeline")
    parser.add_argument("--kb", required=True, help="Path to knowledge.json")
    parser.add_argument("--manifest", required=True, help="Path to backfill manifest")
    parser.add_argument("--mode", required=True, choices=["inventory", "prepare-seed"],
                        help="Backfill mode")
    parser.add_argument("--output", help="Run directory for output files")
    parser.add_argument("--write", action="store_true",
                        help="Allow KB mutation (required for apply-features)")
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
        print(json.dumps(report, indent=2, ensure_ascii=False))

    elif args.mode == "prepare-seed":
        if not args.output:
            print(json.dumps({"error": "--output is required for prepare-seed mode"}), file=sys.stderr)
            sys.exit(1)
        result = run_prepare_seed(kb_path, manifest_path, args.output, dry_run=not args.write)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    else:
        print(json.dumps({"error": f"Unsupported mode: {args.mode}"}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
