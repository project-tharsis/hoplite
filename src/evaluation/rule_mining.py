"""Deterministic candidate rule extraction from WK-vs-B disagreements.

This module does NOT use a learning model. It extracts candidate rules
from repeated WK-vs-B disagreement patterns using deterministic feature
views and grouping logic.

Non-mutation: never writes KB or code.
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any


# ── Feature derivation thresholds ──────────────────────────────────────

_THRESHOLD_XG_DOMINANT = 0.75
_THRESHOLD_SHOT_DOMINANT = 5
_THRESHOLD_POSSESSION_DOMINANT = 8
_THRESHOLD_CORNER_DOMINANT = 4

_THRESHOLD_XG_POOR = -0.5
_THRESHOLD_SHOT_POOR = -4
_THRESHOLD_POSSESSION_POOR = -8
_THRESHOLD_CORNER_POOR = -3

# Fields required for feature view derivation
_DERIVATION_FIELDS = [
    "xg_delta", "shot_delta", "possession_delta", "corner_delta",
    "goals_conceded", "yellow_cards_for", "red_cards_for",
    "goals_after_arsenal_subs", "goals_by_substitutes",
    "set_piece_goals_for", "set_piece_goals_against",
    "substitution_windows", "arsenal_sub_count",
]

# Fields that have explicit integer/float defaults in the extractor
# and are considered "present" even when 0
_NUMERIC_DEFAULT_FIELDS = {
    "goals_conceded": 0,
    "yellow_cards_for": 0,
    "red_cards_for": 0,
    "goals_after_arsenal_subs": 0,
    "goals_by_substitutes": 0,
    "set_piece_goals_for": 0,
    "set_piece_goals_against": 0,
    "arsenal_sub_count": 0,
}


# ── Signal ordering ────────────────────────────────────────────────────

_SIGNAL_ORDER = {"🔴": 0, "🟡": 1, "🟢": 2}


# ── Feature view ───────────────────────────────────────────────────────

def _safe_get(features: dict, key: str) -> Any:
    """Get value from features, returning None if key is missing or null."""
    val = features.get(key)
    if val is None and key not in features:
        return None
    return val


def _is_present(val: Any) -> bool:
    """Check if a value is meaningfully present (not None)."""
    return val is not None


def build_feature_view(row: dict) -> dict:
    """Derive a candidate feature view from an adjudicated row.

    Returns a dict with boolean/numeric fields derived from row["features"].
    Missing data fields produce False for derived booleans and are tracked
    in missing_features.
    """
    features = row.get("features", {})
    context = row.get("context", {})
    missing: list[str] = []

    # Track missing fields
    for field_name in _DERIVATION_FIELDS:
        val = features.get(field_name)
        if field_name in _NUMERIC_DEFAULT_FIELDS:
            # For extractor-default fields, None means missing; 0 is valid
            if val is None and field_name not in features:
                missing.append(field_name)
        else:
            if not _is_present(val):
                missing.append(field_name)

    # Also track xg_for/xg_against for xg_present
    xg_for = _safe_get(features, "xg_for")
    xg_against = _safe_get(features, "xg_against")

    # Get deltas (None if missing)
    xg_delta = _safe_get(features, "xg_delta")
    shot_delta = _safe_get(features, "shot_delta")
    possession_delta = _safe_get(features, "possession_delta")
    corner_delta = _safe_get(features, "corner_delta")

    # ── Derive booleans ────────────────────────────────────────────

    # dominant_xg
    dominant_xg = (xg_delta is not None and xg_delta >= _THRESHOLD_XG_DOMINANT)

    # dominant_shots
    dominant_shots = (shot_delta is not None and shot_delta >= _THRESHOLD_SHOT_DOMINANT)

    # dominant_control: ≥2 of 4 conditions
    control_conditions = [
        xg_delta is not None and xg_delta >= _THRESHOLD_XG_DOMINANT,
        shot_delta is not None and shot_delta >= _THRESHOLD_SHOT_DOMINANT,
        possession_delta is not None and possession_delta >= _THRESHOLD_POSSESSION_DOMINANT,
        corner_delta is not None and corner_delta >= _THRESHOLD_CORNER_DOMINANT,
    ]
    dominant_control = sum(control_conditions) >= 2

    # poor_control: ≥2 of 4 conditions
    poor_conditions = [
        xg_delta is not None and xg_delta <= _THRESHOLD_XG_POOR,
        shot_delta is not None and shot_delta <= _THRESHOLD_SHOT_POOR,
        possession_delta is not None and possession_delta <= _THRESHOLD_POSSESSION_POOR,
        corner_delta is not None and corner_delta <= _THRESHOLD_CORNER_POOR,
    ]
    poor_control = sum(poor_conditions) >= 2

    # goals_conceded: use features value, default 0 only if field exists
    goals_conceded_val = features.get("goals_conceded")
    if goals_conceded_val is None and "goals_conceded" not in features:
        goals_conceded = 0
        clean_sheet = False
    else:
        goals_conceded = goals_conceded_val if goals_conceded_val is not None else 0
        clean_sheet = goals_conceded == 0

    # cards_pressure: yellow_cards_for >= 2 or red_cards_for > 0
    yellow = features.get("yellow_cards_for")
    red = features.get("red_cards_for")
    if yellow is None and "yellow_cards_for" not in features:
        cards_pressure = False
    else:
        yellow = yellow if yellow is not None else 0
        red = red if red is not None else 0
        cards_pressure = yellow >= 2 or red > 0

    # late_subs: earliest sub after 75min, or latest sub after 85min when not leading
    late_subs = False
    sub_windows = features.get("substitution_windows")
    if sub_windows and isinstance(sub_windows, list) and len(sub_windows) > 0:
        minutes = []
        for sw in sub_windows:
            if isinstance(sw, dict) and "start_minute" in sw and sw["start_minute"] is not None:
                minutes.append(sw["start_minute"])
        if minutes:
            earliest = min(minutes)
            latest = max(minutes)
            # earliest sub after 75min
            if earliest > 75:
                late_subs = True
            # latest sub after 85min when not leading
            if latest > 85:
                # Check if leading at that point — use result as proxy
                result = context.get("result", row.get("result", ""))
                if result != "W":
                    late_subs = True

    # sub_impact: goals_after_arsenal_subs > 0 or goals_by_substitutes > 0
    goals_after_subs = features.get("goals_after_arsenal_subs")
    goals_by_subs = features.get("goals_by_substitutes")
    sub_impact = False
    if goals_after_subs is not None and goals_after_subs > 0:
        sub_impact = True
    if goals_by_subs is not None and goals_by_subs > 0:
        sub_impact = True

    # set_piece_edge: set_piece_goals_for > set_piece_goals_against or corner_delta >= 4
    sp_for = features.get("set_piece_goals_for")
    sp_against = features.get("set_piece_goals_against")
    set_piece_edge = False
    if sp_for is not None and sp_against is not None and sp_for > sp_against:
        set_piece_edge = True
    if corner_delta is not None and corner_delta >= _THRESHOLD_CORNER_DOMINANT:
        set_piece_edge = True

    # xg_present
    xg_present = xg_for is not None and xg_against is not None

    return {
        "result": context.get("result", row.get("result", "")),
        "opponent_quality": context.get("opponent_quality", ""),
        "venue": context.get("venue", ""),
        "competition_stage": context.get("competition_stage", ""),
        "xg_present": xg_present,
        "dominant_xg": dominant_xg,
        "dominant_shots": dominant_shots,
        "dominant_control": dominant_control,
        "poor_control": poor_control,
        "clean_sheet": clean_sheet,
        "goals_conceded": goals_conceded,
        "cards_pressure": cards_pressure,
        "late_subs": late_subs,
        "sub_impact": sub_impact,
        "set_piece_edge": set_piece_edge,
        "missing_features": missing,
    }


# ── Candidate rule construction ───────────────────────────────────────

def _group_key(fv: dict, status: str) -> str:
    """Build a grouping key from feature view + status.

    Groups by: status + result + venue + competition_stage
    + dominant_control + poor_control + clean_sheet + xg_present.

    opponent_quality is intentionally excluded so that rows with different
    opponents but similar feature patterns are grouped together, supporting
    the diversity requirement for promotion.
    """
    parts = [
        status,
        fv.get("result", ""),
        fv.get("venue", ""),
        fv.get("competition_stage", ""),
        f"xg_present={fv.get('xg_present', False)}",
        f"dominant_control={fv.get('dominant_control', False)}",
        f"poor_control={fv.get('poor_control', False)}",
        f"clean_sheet={fv.get('clean_sheet', False)}",
    ]
    return "|".join(str(p) for p in parts)


def _determine_direction(status: str) -> str:
    if status == "wk_too_harsh":
        return "upgrade"
    elif status == "wk_too_generous":
        return "downgrade"
    return "unknown"


def _precision(group: list[dict]) -> float:
    """Compute precision: fraction of rows in group with the same direction.

    Since we group by status, all rows in a group have the same direction.
    But we also need to check if there are counterexamples from the
    opposite direction with the same features.
    """
    if not group:
        return 0.0
    # All rows in a group share the same status, so precision = 1.0 within group.
    # Cross-group conflicts reduce precision.
    return 1.0


def _count_opponents_or_competitions(rows: list[dict]) -> int:
    """Count distinct opponents or competitions in the examples."""
    opponents = set()
    competitions = set()
    for row in rows:
        ctx = row.get("context", {})
        if ctx.get("opponent_quality"):
            opponents.add(ctx["opponent_quality"])
        if ctx.get("competition_stage"):
            competitions.add(ctx["competition_stage"])
    return max(len(opponents), len(competitions))


def _has_human_override_or_second_pass(rows: list[dict]) -> bool:
    """Check if any row has human_override or second-pass evaluator agreement."""
    for row in rows:
        entry = row.get("entry", {})
        if entry.get("human_override"):
            return True
        if row.get("second_pass_agreement"):
            return True
    return False


def _extract_predicate(fv: dict, status: str) -> dict:
    """Build a predicate dict from a feature view for the candidate rule."""
    predicate: dict[str, Any] = {}

    if fv.get("result"):
        predicate["result"] = fv["result"]
    if fv.get("opponent_quality"):
        predicate["opponent_quality"] = [fv["opponent_quality"]]
    if fv.get("venue"):
        predicate["venue"] = fv["venue"]
    if fv.get("competition_stage"):
        predicate["competition_stage"] = fv["competition_stage"]

    for bool_field in ["dominant_xg", "dominant_shots", "dominant_control", "poor_control",
                        "clean_sheet", "cards_pressure", "late_subs", "sub_impact",
                        "set_piece_edge", "xg_present"]:
        if fv.get(bool_field):
            predicate[bool_field] = True

    return predicate


def _candidate_id(status: str, predicate: dict) -> str:
    """Generate a deterministic candidate ID."""
    parts = [status]
    for k, v in sorted(predicate.items()):
        parts.append(f"{k}={v}")
    return "_".join(str(p) for p in parts)


def _wk_pattern(group: list[dict]) -> str:
    """Extract the most common WK signal from the group."""
    signals = defaultdict(int)
    for row in group:
        wk = row.get("wk", {})
        overall = wk.get("overall_signal", "unknown")
        signals[overall] += 1
    if signals:
        return max(signals, key=signals.get)
    return "unknown"


def _b_pattern(group: list[dict]) -> str:
    """Extract the most common B signal from the group."""
    signals = defaultdict(int)
    for row in group:
        b = row.get("b", {})
        overall = b.get("overall_signal", "unknown")
        signals[overall] += 1
    if signals:
        return max(signals, key=signals.get)
    return "unknown"


def _build_candidate_rule(
    group_key: str,
    group: list[dict],
    feature_views: list[dict],
    conflict_groups: dict[str, list[dict]],
) -> dict | None:
    """Build a candidate rule from a group of rows with similar features and same status."""
    if not group:
        return None

    status = group[0]["status"]
    direction = _determine_direction(status)
    fv = feature_views[0]

    predicate = _extract_predicate(fv, status)

    # Expand opponent_quality to include all in group
    all_opponents = set()
    for fv_item in feature_views:
        if fv_item.get("opponent_quality"):
            all_opponents.add(fv_item["opponent_quality"])
    if all_opponents:
        predicate["opponent_quality"] = sorted(all_opponents)

    support = len(group)
    examples = [row["match_id"] for row in group]

    # Counterexamples: rows with the same features but opposite direction
    opposite_status = "wk_too_generous" if status == "wk_too_harsh" else "wk_too_harsh"
    opposite_key = group_key.replace(status, opposite_status)
    counterexample_rows = conflict_groups.get(opposite_key, [])
    counterexamples = [r["match_id"] for r in counterexample_rows]
    false_positive_count = len(counterexamples)

    # Precision: support / (support + false_positive_count)
    total = support + false_positive_count
    precision = support / total if total > 0 else 0.0

    # Diversity check
    diversity = _count_opponents_or_competitions(group)

    # Human override check
    has_human = _has_human_override_or_second_pass(group)

    # Candidate ID
    cid = _candidate_id(status, predicate)

    # Determine proposed_action
    proposed_action = _determine_action(
        support=support,
        precision=precision,
        false_positive_count=false_positive_count,
        diversity=diversity,
        has_human_override=has_human,
        predicate=predicate,
    )

    # Risk assessment
    if proposed_action == "wk_patch_proposal":
        risk = "high"
    elif proposed_action == "prompt_blind_spot":
        risk = "medium"
    else:
        risk = "low"

    # Rationale
    rationale = _build_rationale(status, support, precision, direction, fv)

    return {
        "id": cid,
        "target": "overall_signal",
        "predicate": predicate,
        "wk_pattern": _wk_pattern(group),
        "b_pattern": _b_pattern(group),
        "direction": direction,
        "support": support,
        "precision_vs_b": round(precision, 4),
        "false_positive_count": false_positive_count,
        "examples": examples,
        "counterexamples": counterexamples,
        "proposed_action": proposed_action,
        "risk": risk,
        "rationale": rationale,
    }


def _determine_action(
    support: int,
    precision: float,
    false_positive_count: int,
    diversity: int,
    has_human_override: bool,
    predicate: dict,
) -> str:
    """Determine the proposed action based on thresholds.

    prompt_blind_spot: support >= 3, precision >= 0.70, fp <= 2, diversity >= 2
    wk_patch_proposal: support >= 5, precision >= 0.80, fp <= 1, has_human_override
    """
    # Check wk_patch_proposal first (higher bar)
    if (support >= 5
            and precision >= 0.80
            and false_positive_count <= 1
            and has_human_override):
        return "wk_patch_proposal"

    # Check prompt_blind_spot
    if (support >= 3
            and precision >= 0.70
            and false_positive_count <= 2
            and diversity >= 2):
        return "prompt_blind_spot"

    return "rejected"


def _build_rationale(
    status: str,
    support: int,
    precision: float,
    direction: str,
    fv: dict,
) -> str:
    """Build a human-readable rationale for the candidate."""
    if status == "wk_too_harsh":
        return (
            f"评估器B在{support}场比赛中认为WK评分偏低"
            f"（precision={precision:.2f}）。"
            f"特征模式：dominant_control={fv.get('dominant_control')}, "
            f"clean_sheet={fv.get('clean_sheet')}, "
            f"dominant_xg={fv.get('dominant_xg')}。"
        )
    elif status == "wk_too_generous":
        return (
            f"评估器B在{support}场比赛中认为WK评分偏高"
            f"（precision={precision:.2f}）。"
            f"特征模式：poor_control={fv.get('poor_control')}, "
            f"cards_pressure={fv.get('cards_pressure')}。"
        )
    return f"Support={support}, precision={precision:.2f}, direction={direction}"


def _rejection_reasons(
    support: int,
    precision: float,
    false_positive_count: int,
    diversity: int,
    has_human_override: bool,
) -> list[str]:
    """List reasons why a candidate fails promotion thresholds."""
    reasons = []
    if support < 3:
        reasons.append(f"support={support} < 3 (minimum for prompt_blind_spot)")
    if precision < 0.70:
        reasons.append(f"precision={precision:.4f} < 0.70")
    if false_positive_count > 2:
        reasons.append(f"false_positive_count={false_positive_count} > 2")
    if diversity < 2:
        reasons.append(f"diversity={diversity} < 2 (need ≥2 different opponents or competitions)")
    return reasons


# ── Main entry point ───────────────────────────────────────────────────

def run_rule_mining(adjudication_report_path: str, output_path: str) -> dict:
    """Run rule mining on an adjudication report.

    Reads the adjudication report, extracts feature views for disagreement
    rows, groups them, builds candidate rules, applies promotion thresholds,
    and writes the output.

    Args:
        adjudication_report_path: Path to the adjudication report JSON.
        output_path: Path to write the rule_candidates.json output.

    Returns:
        The output dict with version, candidates, and rejected_candidates.
    """
    with open(adjudication_report_path) as f:
        report = json.load(f)

    rows = report.get("rows", [])

    # Filter to disagreement rows only
    disagreement_statuses = {"wk_too_harsh", "wk_too_generous"}
    disagreement_rows = [r for r in rows if r.get("status") in disagreement_statuses]

    # Build feature views and group
    groups: dict[str, list[dict]] = defaultdict(list)
    feature_view_groups: dict[str, list[dict]] = defaultdict(list)

    for row in disagreement_rows:
        fv = build_feature_view(row)
        gk = _group_key(fv, row["status"])
        groups[gk].append(row)
        feature_view_groups[gk].append(fv)

    # Also group by same features but opposite status for conflict detection
    conflict_groups: dict[str, list[dict]] = defaultdict(list)
    for row in disagreement_rows:
        fv = build_feature_view(row)
        opposite_status = "wk_too_generous" if row["status"] == "wk_too_harsh" else "wk_too_harsh"
        gk = _group_key(fv, opposite_status)
        conflict_groups[gk].append(row)

    # Build candidate rules
    candidates = []
    rejected_candidates = []

    for gk, group in groups.items():
        fvs = feature_view_groups[gk]
        candidate = _build_candidate_rule(gk, group, fvs, conflict_groups)
        if candidate is None:
            continue

        if candidate["proposed_action"] != "rejected":
            # Post-check: prompt_blind_spot diversity
            if candidate["proposed_action"] == "prompt_blind_spot":
                diversity = _count_opponents_or_competitions(group)
                if diversity < 2:
                    candidate["proposed_action"] = "rejected"
                    candidate["rejection_reasons"] = [
                        f"diversity={diversity} < 2 (need ≥2 different opponents or competitions)"
                    ]
                    rejected_candidates.append(candidate)
                    continue
            candidates.append(candidate)
        else:
            # Collect rejection reasons
            support = candidate["support"]
            precision = candidate["precision_vs_b"]
            fp = candidate["false_positive_count"]
            diversity = _count_opponents_or_competitions(group)
            has_human = _has_human_override_or_second_pass(group)
            candidate["rejection_reasons"] = _rejection_reasons(
                support, precision, fp, diversity, has_human,
            )
            rejected_candidates.append(candidate)

    # Sort for determinism
    candidates.sort(key=lambda c: c["id"])
    rejected_candidates.sort(key=lambda c: c["id"])

    output = {
        "version": "v1",
        "candidates": candidates,
        "rejected_candidates": rejected_candidates,
    }

    with open(output_path, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    return output
