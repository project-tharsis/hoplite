"""Adjudication module — compare WK v1.1 vs Evaluator B across feature-backed KB entries.

Non-mutation mode: never writes to KB.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from src.evaluation.llm_result import validate_llm_result

# ── Constants ─────────────────────────────────────────────────────────────

SIGNAL_ORDER = {"🔴": 0, "🟡": 1, "🟢": 2}
VALID_SIGNALS = set(SIGNAL_ORDER.keys())

MODEL_KEY_MAP = {
    "culture_as_os": "1",
    "where_game_is_played": "2",
    "defence_as_attacking_identity": "3",
    "marginal_gains": "4",
    "add_capability_keep_identity": "5",
    "role_clarity": "6",
}

REQUIRED_B_FIELDS = {
    "overall_signal",
    "model_signals",
    "dimension_signals",
    "narrative",
    "confidence",
    "missing_or_weak_evidence",
    "weak_label_disagreements",
}

STATUS_VALUES = [
    "agreement_high_confidence",
    "agreement_low_confidence",
    "wk_too_harsh",
    "wk_too_generous",
    "model_level_disagreement",
    "dimension_level_disagreement",
    "missing_evaluator_b",
    "invalid_evaluator_b",
    "needs_second_pass",
]


# ── Helpers ───────────────────────────────────────────────────────────────


def _normalize_wk_model_signals(raw: dict[str, str]) -> dict[str, str]:
    """Convert semantic WK model keys to numeric keys."""
    out: dict[str, str] = {}
    for key, value in raw.items():
        numeric = MODEL_KEY_MAP.get(key, key)
        out[numeric] = value
    return out


def _signal_rank(sig: str) -> int:
    return SIGNAL_ORDER.get(sig, -1)


def _signals_match(a: str, b: str) -> bool:
    return a == b


def _is_feature_backed(entry: dict) -> bool:
    return "features" in entry and isinstance(entry["features"], dict) and bool(entry["features"])


def _has_valid_b(entry: dict) -> bool:
    """Check if entry has a valid Evaluator B evaluation (strict v2)."""
    ev = entry.get("evaluation")
    if not isinstance(ev, dict):
        return False
    if ev.get("source") != "llm":
        return False
    # Check required strict v2 fields
    for field in REQUIRED_B_FIELDS:
        if field not in ev:
            return False
    # Validate signal values
    if ev.get("overall_signal") not in VALID_SIGNALS:
        return False
    model_sigs = ev.get("model_signals", {})
    if not isinstance(model_sigs, dict) or set(model_sigs.keys()) != {"1", "2", "3", "4", "5", "6"}:
        return False
    dim_sigs = ev.get("dimension_signals", {})
    if not isinstance(dim_sigs, dict) or set(dim_sigs.keys()) != {"execution", "adjustment", "satisfaction"}:
        return False
    return True


def _has_b_evaluation(entry: dict) -> bool:
    """Check if entry has any evaluation dict (may be invalid)."""
    return isinstance(entry.get("evaluation"), dict) and bool(entry["evaluation"])


def _extract_context(features: dict) -> dict:
    """Extract context fields from features."""
    return {
        "opponent_quality": features.get("opponent_quality", "unknown"),
        "venue": features.get("venue", "unknown"),
        "competition_stage": features.get("competition_stage", "unknown"),
        "result": features.get("result", "unknown"),
        "xg_present": (
            features.get("xg_for") is not None and features.get("xg_against") is not None
        ),
    }


# ── Adjudicator ───────────────────────────────────────────────────────────


class Adjudicator:
    """Compare WK v1.1 weak labels against Evaluator B evaluations."""

    def __init__(
        self,
        entries: list[dict] | None = None,
        kb_path: str | Path | None = None,
        run_id: str = "unknown",
    ):
        if entries is not None:
            self._entries = entries
        elif kb_path is not None:
            with open(kb_path, "r", encoding="utf-8") as f:
                self._entries = json.load(f)
        else:
            raise ValueError("Provide either entries or kb_path")
        self._run_id = run_id

    # ── public API ────────────────────────────────────────────────────

    def run(self) -> dict:
        """Run adjudication and return the full report dict."""
        total = len(self._entries)
        feature_backed = [e for e in self._entries if _is_feature_backed(e)]
        fb_count = len(feature_backed)

        rows: list[dict] = []
        status_counts: dict[str, int] = {s: 0 for s in STATUS_VALUES}

        compared_count = 0
        overall_agree = 0
        dim_agree = 0
        model_agree = 0

        for entry in feature_backed:
            row = self._adjudicate_one(entry)
            rows.append(row)
            status_counts[row["status"]] += 1

            if row["status"] not in ("missing_evaluator_b", "invalid_evaluator_b"):
                compared_count += 1
                if not row["differences"] or "overall" not in row["differences"]:
                    overall_agree += 1
                # dimension agreement: no dimension-level or higher differences
                if row["status"] in ("agreement_high_confidence", "agreement_low_confidence", "model_level_disagreement"):
                    dim_agree += 1
                if row["status"] in ("agreement_high_confidence", "agreement_low_confidence"):
                    model_agree += 1

        # Rates
        overall_rate = overall_agree / compared_count if compared_count else 0.0
        dim_rate = dim_agree / compared_count if compared_count else 0.0
        model_rate = model_agree / compared_count if compared_count else 0.0

        context_breakdowns = self._build_context_breakdowns(rows)

        return {
            "run_id": self._run_id,
            "summary": {
                "total_entries": total,
                "feature_backed": fb_count,
                "compared": compared_count,
                "missing_evaluator_b": status_counts["missing_evaluator_b"],
                "overall_agreement_rate": round(overall_rate, 4),
                "dimension_agreement_rate": round(dim_rate, 4),
                "model_agreement_rate": round(model_rate, 4),
            },
            "status_counts": status_counts,
            "context_breakdowns": context_breakdowns,
            "rows": rows,
        }

    # ── per-entry logic ───────────────────────────────────────────────

    def _adjudicate_one(self, entry: dict) -> dict:
        match_id = entry.get("match_id", "unknown")
        features = entry.get("features", {})
        context = _extract_context(features)
        # Pass through top-level opponent and competition for diversity gate
        opponent_name = entry.get("opponent", "")
        competition = entry.get("competition", "")

        wk_raw = entry.get("weak_labels", {})
        wk_norm = self._normalize_wk(wk_raw)

        # Missing B
        if not _has_b_evaluation(entry):
            return self._build_row(match_id, context, "missing_evaluator_b", wk_norm, {}, [], features, opponent_name, competition)

        # Invalid B
        if not _has_valid_b(entry):
            return self._build_row(match_id, context, "invalid_evaluator_b", wk_norm, {}, [], features, opponent_name, competition)

        ev = entry["evaluation"]
        b_signals = {
            "overall_signal": ev["overall_signal"],
            "dimension_signals": dict(ev["dimension_signals"]),
            "model_signals": dict(ev["model_signals"]),
        }
        confidence = ev.get("confidence", {})
        missing_evidence = ev.get("missing_or_weak_evidence", [])
        wld = ev.get("weak_label_disagreements", [])

        has_low_conf = any(v == "low" for v in confidence.values() if isinstance(v, str))

        # Compare signals
        differences: list[str] = []
        wk_overall = wk_norm["overall_signal"]
        b_overall = b_signals["overall_signal"]

        # Overall disagreement
        overall_match = _signals_match(wk_overall, b_overall)
        if not overall_match:
            differences.append("overall")

        # Dimension comparison
        dim_diffs = []
        for dim in ("execution", "adjustment", "satisfaction"):
            wk_d = wk_norm["dimension_signals"].get(dim)
            b_d = b_signals["dimension_signals"].get(dim)
            if wk_d and b_d and not _signals_match(wk_d, b_d):
                dim_diffs.append(dim)
        if dim_diffs:
            differences.extend(dim_diffs)

        # Model comparison
        model_diffs = []
        for mk in ("1", "2", "3", "4", "5", "6"):
            wk_m = wk_norm["model_signals"].get(mk)
            b_m = b_signals["model_signals"].get(mk)
            if wk_m and b_m and not _signals_match(wk_m, b_m):
                model_diffs.append(mk)
        if model_diffs:
            differences.extend(model_diffs)

        # Classify status
        if not differences:
            # All match — check confidence
            if has_low_conf:
                status = "agreement_low_confidence"
            else:
                status = "agreement_high_confidence"
        elif has_low_conf and not wld:
            # Disagreements exist but B confidence is low and no explanation provided
            status = "needs_second_pass"
        elif overall_match and not dim_diffs and model_diffs:
            status = "model_level_disagreement"
        elif overall_match and dim_diffs:
            status = "dimension_level_disagreement"
        else:
            # Overall mismatch
            wk_rank = _signal_rank(wk_overall)
            b_rank = _signal_rank(b_overall)
            if wk_rank < b_rank:
                status = "wk_too_harsh"
            elif wk_rank > b_rank:
                status = "wk_too_generous"
            else:
                # Shouldn't happen if overall_match is False but ranks equal
                status = "dimension_level_disagreement"

        return self._build_row(
            match_id, context, status, wk_norm, b_signals, differences, features, opponent_name, competition
        )

    # ── normalization ─────────────────────────────────────────────────

    def _normalize_wk(self, wk_raw: dict) -> dict:
        """Normalize WK signals: convert semantic model keys to numeric."""
        model_raw = wk_raw.get("model_signals", {})
        return {
            "overall_signal": wk_raw.get("overall_signal", ""),
            "dimension_signals": dict(wk_raw.get("dimension_signals", {})),
            "model_signals": _normalize_wk_model_signals(model_raw),
        }

    # ── row builder ───────────────────────────────────────────────────

    @staticmethod
    def _build_row(
        match_id: str,
        context: dict,
        status: str,
        wk: dict,
        b: dict,
        differences: list[str],
        features: dict,
        opponent_name: str = "",
        competition: str = "",
    ) -> dict:
        return {
            "match_id": match_id,
            "context": context,
            "status": status,
            "wk": {
                "overall_signal": wk.get("overall_signal", ""),
                "dimension_signals": dict(wk.get("dimension_signals", {})),
                "model_signals": dict(wk.get("model_signals", {})),
            },
            "b": {
                "overall_signal": b.get("overall_signal", ""),
                "dimension_signals": dict(b.get("dimension_signals", {})),
                "model_signals": dict(b.get("model_signals", {})),
            },
            "differences": differences,
            "features": {
                "result": features.get("result"),
                "opponent_quality": features.get("opponent_quality"),
                "opponent_name": opponent_name,
                "competition": competition,
            },
        }

    # ── context breakdowns ────────────────────────────────────────────

    @staticmethod
    def _build_context_breakdowns(rows: list[dict]) -> list[dict]:
        """Group rows by context dimension and compute per-bucket status counts."""
        dimensions = ["opponent_quality", "venue", "competition_stage", "result"]
        breakdowns: list[dict] = []

        for dim in dimensions:
            buckets: dict[str, dict[str, int]] = defaultdict(lambda: {s: 0 for s in STATUS_VALUES})
            for row in rows:
                val = row["context"].get(dim, "unknown")
                buckets[val][row["status"]] += 1
            for val, counts in sorted(buckets.items()):
                breakdowns.append(
                    {
                        "dimension": dim,
                        "value": val,
                        "total": sum(counts.values()),
                        "status_counts": dict(counts),
                    }
                )

        # xg_present breakdown
        for xg_val in (True, False):
            counts = {s: 0 for s in STATUS_VALUES}
            total = 0
            for row in rows:
                if row["context"].get("xg_present") == xg_val:
                    counts[row["status"]] += 1
                    total += 1
            if total:
                breakdowns.append(
                    {
                        "dimension": "xg_present",
                        "value": str(xg_val),
                        "total": total,
                        "status_counts": dict(counts),
                    }
                )

        return breakdowns


# ── Module-level entry point ──────────────────────────────────────────────


def run_adjudication(
    kb_path: str | Path,
    run_id: str,
    output_path: str | Path | None = None,
) -> dict:
    """Run adjudication from a KB file and optionally write report.

    Non-mutation: never modifies the KB.
    """
    adj = Adjudicator(kb_path=kb_path, run_id=run_id)
    report = adj.run()

    if output_path is not None:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

    return report
