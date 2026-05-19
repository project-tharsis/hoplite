#!/usr/bin/env python3
"""Replay historical KB entries through the weak labeler.

Deterministic, no LLM calls.  Never mutates knowledge.json.

Usage:
    python scripts/replay_history.py \
        --kb data/knowledge.json \
        --mode weak-label-only \
        --output /tmp/hoplite_replay_report.json
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import fields as dataclass_fields
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.features.extractor import MatchFeatures
from src.labels.weak_labeler import WeakLabeler


def features_from_dict(d: dict) -> MatchFeatures:
    """Reconstruct a MatchFeatures dataclass from a stored dict.

    Only accepts keys that are valid MatchFields fields; ignores extras.
    """
    valid_keys = {f.name for f in dataclass_fields(MatchFeatures)}
    filtered = {k: v for k, v in d.items() if k in valid_keys}
    return MatchFeatures(**filtered)


def _compare_weak_labels(stored: dict, recomputed: dict) -> list[dict]:
    """Compare stored weak labels to recomputed, return list of changes."""
    changes: list[dict] = []

    # Compare overall_signal
    if stored.get("overall_signal") != recomputed.get("overall_signal"):
        changes.append({
            "field": "weak_labels.overall_signal",
            "old": stored.get("overall_signal"),
            "new": recomputed.get("overall_signal"),
        })

    # Compare model_signals
    stored_models = stored.get("model_signals", {})
    recomputed_models = recomputed.get("model_signals", {})
    for key in sorted(set(stored_models) | set(recomputed_models)):
        old_val = stored_models.get(key)
        new_val = recomputed_models.get(key)
        if old_val != new_val:
            changes.append({
                "field": f"weak_labels.model_signals.{key}",
                "old": old_val,
                "new": new_val,
            })

    # Compare dimension_signals
    stored_dims = stored.get("dimension_signals", {})
    recomputed_dims = recomputed.get("dimension_signals", {})
    for key in sorted(set(stored_dims) | set(recomputed_dims)):
        old_val = stored_dims.get(key)
        new_val = recomputed_dims.get(key)
        if old_val != new_val:
            changes.append({
                "field": f"weak_labels.dimension_signals.{key}",
                "old": old_val,
                "new": new_val,
            })

    return changes


def replay_weak_label_only(kb_path: str) -> dict:
    """Replay all entries with stored features.

    Returns a replay report dict with summary, changes, and skipped.
    """
    with open(kb_path, encoding="utf-8") as f:
        entries = json.load(f)

    labeler = WeakLabeler()
    total = len(entries)
    replayed = 0
    changed_count = 0
    all_changes: list[dict] = []
    skipped: list[dict] = []

    for entry in entries:
        match_id = str(entry.get("match_id", "unknown"))
        stored_features = entry.get("features")

        if not stored_features:
            skipped.append({"match_id": match_id, "reason": "missing features"})
            continue

        # Reconstruct MatchFeatures from stored dict
        try:
            mf = features_from_dict(stored_features)
        except Exception as e:
            skipped.append({"match_id": match_id, "reason": f"features parse error: {e}"})
            continue

        # Recompute weak labels
        recomputed = labeler.label(mf)
        recomputed_dict = {
            "model_signals": recomputed.model_signals,
            "dimension_signals": recomputed.dimension_signals,
            "overall_signal": recomputed.overall_signal,
        }

        # Compare with stored
        stored_wl = entry.get("weak_labels", {})
        changes = _compare_weak_labels(stored_wl, recomputed_dict)

        for change in changes:
            change["match_id"] = match_id
            all_changes.append(change)

        if changes:
            changed_count += 1

        replayed += 1

    return {
        "summary": {
            "total_entries": total,
            "replayed": replayed,
            "skipped": len(skipped),
            "changed": changed_count,
        },
        "changes": all_changes,
        "skipped": skipped,
    }


def replay_compare_human(kb_path: str) -> dict:
    """Replay WK v1.1, compare against LLM eval and human_override."""
    with open(kb_path, encoding="utf-8") as f:
        entries = json.load(f)

    labeler = WeakLabeler()
    all_changes: list[dict] = []
    changed_count = 0
    replayed = 0
    skipped: list[dict] = []
    human_comparisons: list[dict] = []

    for entry in entries:
        match_id = str(entry.get("match_id", "unknown"))
        stored_features = entry.get("features")

        if not stored_features:
            skipped.append({"match_id": match_id, "reason": "missing features"})
            continue

        try:
            mf = features_from_dict(stored_features)
        except Exception as e:
            skipped.append({"match_id": match_id, "reason": f"features parse error: {e}"})
            continue

        recomputed = labeler.label(mf)
        recomputed_dict = {
            "model_signals": recomputed.model_signals,
            "dimension_signals": recomputed.dimension_signals,
            "overall_signal": recomputed.overall_signal,
        }

        stored_wl = entry.get("weak_labels", {})
        changes = _compare_weak_labels(stored_wl, recomputed_dict)
        for change in changes:
            change["match_id"] = match_id
            all_changes.append(change)
        if changes:
            changed_count += 1
        replayed += 1

        ho = entry.get("human_override")
        if ho:
            eval_ = entry.get("evaluation", {})
            try:
                disagreements = _compute_human_disagreements(recomputed_dict, eval_, ho)
            except Exception:
                disagreements = []
            human_comparisons.append({
                "match_id": match_id,
                "wk": {
                    "overall_signal": recomputed.overall_signal,
                    "dimension_signals": recomputed.dimension_signals,
                    "model_signals": recomputed.model_signals,
                },
                "llm": {
                    "overall_signal": eval_.get("overall_signal"),
                    "dimension_signals": eval_.get("dimension_signals", {}),
                    "model_signals": eval_.get("model_signals", {}),
                },
                "human": {
                    "overall_signal": ho.get("corrected_overall_signal"),
                    "dimension_signals": ho.get("corrected_dimension_signals", {}),
                    "model_signals": ho.get("corrected_model_signals", {}),
                },
                "disagreements": disagreements,
            })

    return {
        "summary": {
            "total_entries": len(entries),
            "replayed": replayed,
            "skipped": len(skipped),
            "changed": changed_count,
            "human_reviewed": sum(1 for e in entries if e.get("human_override")),
            "human_compared": len(human_comparisons),
        },
        "changes": all_changes,
        "human_comparisons": human_comparisons,
        "skipped": skipped,
    }


def _compute_human_disagreements(wk: dict, llm: dict, human: dict) -> list[dict]:
    """Compare WK, LLM, and human signals."""
    disagreements: list[dict] = []
    h_overall = human.get("corrected_overall_signal")
    if h_overall:
        wk_os = wk.get("overall_signal")
        llm_os = llm.get("overall_signal")
        if wk_os != h_overall or llm_os != h_overall:
            disagreements.append({"field": "overall_signal", "wk": wk_os, "llm": llm_os, "human": h_overall})

    h_dims = human.get("corrected_dimension_signals", {})
    for dim_key in sorted(set(list(wk.get("dimension_signals", {}).keys()) + list(llm.get("dimension_signals", {}).keys()) + list(h_dims.keys()))):
        wk_v = wk.get("dimension_signals", {}).get(dim_key)
        llm_v = llm.get("dimension_signals", {}).get(dim_key)
        h_v = h_dims.get(dim_key)
        if h_v is not None and (wk_v != h_v or llm_v != h_v):
            disagreements.append({"field": f"dimension_signals.{dim_key}", "wk": wk_v, "llm": llm_v, "human": h_v})

    h_models = human.get("corrected_model_signals", {})
    for m_key in sorted(set(list(wk.get("model_signals", {}).keys()) + list(llm.get("model_signals", {}).keys()) + list(h_models.keys()))):
        wk_v = wk.get("model_signals", {}).get(m_key)
        llm_v = llm.get("model_signals", {}).get(m_key)
        h_v = h_models.get(m_key)
        if h_v is not None and (wk_v != h_v or llm_v != h_v):
            disagreements.append({"field": f"model_signals.{m_key}", "wk": wk_v, "llm": llm_v, "human": h_v})

    return disagreements


def main():
    parser = argparse.ArgumentParser(description="Replay historical KB entries")
    parser.add_argument("--kb", required=True, help="Path to knowledge.json")
    parser.add_argument("--mode", default="weak-label-only",
                        choices=["weak-label-only"],
                        help="Replay mode (currently only weak-label-only)")
    parser.add_argument("--compare-human", action="store_true",
                        help="Include human override comparison in output")
    parser.add_argument("--output", required=True, help="Output report path")
    args = parser.parse_args()

    kb_path = args.kb
    if not Path(kb_path).exists():
        print(f"错误: KB 文件不存在: {kb_path}", file=sys.stderr)
        sys.exit(1)

    if args.mode == "weak-label-only":
        if args.compare_human:
            report = replay_compare_human(kb_path)
        else:
            report = replay_weak_label_only(kb_path)
    else:
        print(f"错误: 不支持的模式: {args.mode}", file=sys.stderr)
        sys.exit(1)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"回放报告已写入: {output_path}")
    print(f"  总计: {report['summary']['total_entries']}")
    print(f"  已回放: {report['summary']['replayed']}")
    print(f"  跳过: {report['summary']['skipped']}")
    print(f"  有变化: {report['summary']['changed']}")


if __name__ == "__main__":
    main()
