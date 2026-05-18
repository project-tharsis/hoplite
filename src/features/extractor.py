"""Feature extraction from normalized match JSON.

Design principles:
- Deterministic: same input → same output.
- missing_data MUST be populated: unavailable data is explicitly recorded.
- Pure extraction — no judgment, no scoring.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

from src.tools.extract import (
    _detect_arsenal_side,
    extract_match_stats,
    extract_key_events,
    extract_context,
    extract_set_piece_goals,
    extract_sub_impact,
    normalize_event_type,
)


# ── MatchFeatures dataclass (Section 6.3 of spec) ────────────────────


@dataclass
class MatchFeatures:
    """Stable features derived from MatchRaw and NormalizedEvent.

    Every field has a sensible default so partial extraction is possible.
    ``missing_data`` is required and must be populated explicitly.
    """

    # Result & context
    result: str = ""                # W | D | L
    score_margin: int = 0
    opponent_quality: str = ""      # top6 | european_elite | mid_table | lower
    venue: str = ""                 # home | away
    competition_stage: str = ""     # league_early | league_late | group_stage | knockout | regular

    # Scores
    arsenal_goals: int = 0
    opponent_goals: int = 0

    # Possession
    possession_for: Optional[float] = None
    possession_against: Optional[float] = None
    possession_delta: Optional[float] = None

    # Shots
    shots_for: Optional[int] = None
    shots_against: Optional[int] = None
    shot_delta: Optional[int] = None

    # Shots on target
    shots_on_target_for: Optional[int] = None
    shots_on_target_against: Optional[int] = None
    shot_on_target_delta: Optional[int] = None

    # xG
    xg_for: Optional[float] = None
    xg_against: Optional[float] = None
    xg_delta: Optional[float] = None

    # Pass accuracy
    pass_accuracy_for: Optional[float] = None
    pass_accuracy_against: Optional[float] = None
    pass_accuracy_delta: Optional[float] = None

    # Corners
    corners_for: Optional[int] = None
    corners_against: Optional[int] = None
    corner_delta: Optional[int] = None

    # Discipline
    fouls_for: Optional[int] = None
    fouls_against: Optional[int] = None
    yellow_cards_for: int = 0
    red_cards_for: int = 0

    # Defensive
    goals_conceded: int = 0
    opponent_shots_on_target: Optional[int] = None

    # Set pieces
    set_piece_goals_for: int = 0
    set_piece_goals_against: int = 0

    # Substitutions
    substitution_windows: list = field(default_factory=list)  # list of {start_minute, end_minute, player}
    arsenal_sub_count: int = 0
    goals_after_arsenal_subs: int = 0

    # Score state timeline: list of {minute, arsenal_score, opponent_score}
    score_state_timeline: list = field(default_factory=list)

    # Pre-match predicted plan context
    predicted_plan_match_features: dict = field(default_factory=dict)

    # REQUIRED — explicitly list what data is unavailable
    missing_data: list = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize to a plain dict (for JSON storage)."""
        return asdict(self)


# ── FeatureExtractor ─────────────────────────────────────────────────


class FeatureExtractor:
    """Extract MatchFeatures from a normalized match JSON dict.

    Deterministic: the same input always produces the same output.
    Populates ``missing_data`` for any unavailable fields.
    """

    def extract(self, match_json: dict) -> MatchFeatures:
        """Main entry point. Returns a fully populated MatchFeatures."""
        features = MatchFeatures()

        # ── Raw extractions from existing tools ──────────────────────
        stats = extract_match_stats(match_json)
        events = extract_key_events(match_json)
        context = extract_context(match_json)
        set_pieces = extract_set_piece_goals(events)
        subs = extract_sub_impact(events)

        # ── Result & context ─────────────────────────────────────────
        arsenal_score = stats["score"]["arsenal"]
        opponent_score = stats["score"]["opponent"]

        if arsenal_score > opponent_score:
            features.result = "W"
        elif arsenal_score < opponent_score:
            features.result = "L"
        else:
            features.result = "D"

        features.score_margin = arsenal_score - opponent_score
        features.arsenal_goals = arsenal_score
        features.opponent_goals = opponent_score
        features.goals_conceded = opponent_score

        features.opponent_quality = context.get("opponent_quality", "unknown")
        features.venue = context.get("venue", "")
        features.competition_stage = context.get("competition_stage", "")

        # ── Stats fields + missing_data tracking ─────────────────────
        missing: list[str] = []

        # Possession
        poss_a = stats["possession"]["arsenal"]
        poss_o = stats["possession"]["opponent"]
        if poss_a is not None and poss_o is not None:
            features.possession_for = _to_float(poss_a)
            features.possession_against = _to_float(poss_o)
            features.possession_delta = features.possession_for - features.possession_against
        else:
            missing.append("possession")

        # Shots
        shots_a = stats["shots"]["arsenal"]
        shots_o = stats["shots"]["opponent"]
        if shots_a is not None and shots_o is not None:
            features.shots_for = _to_int(shots_a)
            features.shots_against = _to_int(shots_o)
            features.shot_delta = features.shots_for - features.shots_against
        else:
            missing.append("shots")

        # Shots on target
        sot_a = stats["shots_on_target"]["arsenal"]
        sot_o = stats["shots_on_target"]["opponent"]
        if sot_a is not None and sot_o is not None:
            features.shots_on_target_for = _to_int(sot_a)
            features.shots_on_target_against = _to_int(sot_o)
            features.shot_on_target_delta = features.shots_on_target_for - features.shots_on_target_against
        else:
            missing.append("shots_on_target")
        features.opponent_shots_on_target = features.shots_on_target_against

        # xG
        xg_a = stats["xg"]["arsenal"]
        xg_o = stats["xg"]["opponent"]
        if xg_a is not None and xg_o is not None:
            features.xg_for = _to_float(xg_a)
            features.xg_against = _to_float(xg_o)
            features.xg_delta = features.xg_for - features.xg_against
        else:
            missing.append("xG")

        # Pass accuracy
        pa_a = stats["passes"]["arsenal"]["accuracy"]
        pa_o = stats["passes"]["opponent"]["accuracy"]
        if pa_a is not None and pa_o is not None:
            features.pass_accuracy_for = _to_float(pa_a)
            features.pass_accuracy_against = _to_float(pa_o)
            features.pass_accuracy_delta = features.pass_accuracy_for - features.pass_accuracy_against
        else:
            missing.append("pass_accuracy")

        # Corners
        corn_a = stats["corners"]["arsenal"]
        corn_o = stats["corners"]["opponent"]
        if corn_a is not None and corn_o is not None:
            features.corners_for = _to_int(corn_a)
            features.corners_against = _to_int(corn_o)
            features.corner_delta = features.corners_for - features.corners_against
        else:
            missing.append("corners")

        # Fouls
        fouls_a = stats["fouls"]["arsenal"]
        fouls_o = stats["fouls"]["opponent"]
        if fouls_a is not None and fouls_o is not None:
            features.fouls_for = _to_int(fouls_a)
            features.fouls_against = _to_int(fouls_o)
        else:
            missing.append("fouls")

        # Cards (event-derived — always available if events exist)
        features.yellow_cards_for = stats["cards"]["arsenal"]["yellow"]
        features.red_cards_for = stats["cards"]["arsenal"]["red"]

        # Set pieces
        features.set_piece_goals_for = set_pieces["arsenal"]
        features.set_piece_goals_against = set_pieces["opponent"]

        # Data that is typically unavailable from current sources
        missing.append("pressing")
        missing.append("pressing_recoveries")
        missing.append("transition")

        features.missing_data = sorted(set(missing))

        # ── Score state timeline ─────────────────────────────────────
        features.score_state_timeline = _build_score_timeline(match_json, events)

        # ── Substitution windows ─────────────────────────────────────
        arsenal_subs = [s for s in subs if s.get("is_arsenal", False)]
        features.arsenal_sub_count = len(arsenal_subs)
        features.substitution_windows = _build_substitution_windows(arsenal_subs)

        # ── Goals after Arsenal subs ─────────────────────────────────
        # Count Arsenal goals scored after the first Arsenal substitution
        if arsenal_subs:
            first_sub_minute = min(s["minute"] for s in arsenal_subs)
            goals_after = 0
            for e in events:
                if (e.get("type") == "goal"
                        and e.get("is_arsenal")
                        and e.get("minute", 0) > first_sub_minute):
                    goals_after += 1
            features.goals_after_arsenal_subs = goals_after
        else:
            features.goals_after_arsenal_subs = 0

        # ── Predicted plan match features ────────────────────────────
        features.predicted_plan_match_features = {
            "opponent_quality": features.opponent_quality,
            "venue": features.venue,
            "competition_stage": features.competition_stage,
            "opponent": context.get("opponent", ""),
        }

        return features


# ── Helpers ───────────────────────────────────────────────────────────


def _to_float(val) -> float:
    """Convert a possibly-string stat value to float."""
    if isinstance(val, str):
        return float(val.replace("%", "").strip())
    return float(val)


def _to_int(val) -> int:
    """Convert a possibly-string stat value to int."""
    if isinstance(val, str):
        return int(val.replace("%", "").strip())
    return int(val)


def _build_score_timeline(match_json: dict, events: list[dict]) -> list[dict]:
    """Build a minute-by-minute score state from goal events.

    Returns a sorted list of {minute, arsenal_score, opponent_score}.
    Starts with 0-0 at minute 0 if there are any goals.
    """
    goals = [e for e in events if e.get("type") == "goal"]
    if not goals:
        return []

    # Sort goals by minute for deterministic ordering
    goals_sorted = sorted(goals, key=lambda e: (e.get("minute", 0), e.get("player", "")))

    timeline: list[dict] = [{"minute": 0, "arsenal_score": 0, "opponent_score": 0}]
    a_score = 0
    o_score = 0

    for g in goals_sorted:
        if g.get("is_arsenal"):
            a_score += 1
        else:
            o_score += 1
        timeline.append({
            "minute": g.get("minute", 0),
            "arsenal_score": a_score,
            "opponent_score": o_score,
        })

    return timeline


def _build_substitution_windows(arsenal_subs: list[dict]) -> list[dict]:
    """Build substitution window descriptors.

    Each window tracks a substitution minute and the player involved.
    Returns a sorted list of {minute, player, scored_after}.
    """
    windows: list[dict] = []
    for s in sorted(arsenal_subs, key=lambda x: x.get("minute", 0)):
        windows.append({
            "minute": s.get("minute", 0),
            "player": s.get("player", ""),
            "scored_after": s.get("scored_after", False),
        })
    return windows
