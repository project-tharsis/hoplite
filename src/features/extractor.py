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
    opponent_name: str = ""         # e.g., "Bournemouth"
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
    goals_by_substitutes: int = 0  # goals directly scored or assisted by subs

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

    @staticmethod
    def extract_from_report(report_json: dict) -> MatchFeatures:
        """Extract features from an analyze_match report JSON.

        The report has shape: {match, stats, key_events, context, set_pieces,
        sub_impact, ...}.  This method reconstructs a match-like payload and
        delegates to ``extract()`` so feature semantics stay consistent.

        Raises:
            ValueError: if the report is too sparse to produce features.
        """
        match_meta = report_json.get("match")
        if not match_meta:
            raise ValueError(
                "报告中缺少 'match' 字段，无法提取特征。"
                "请提供包含 match、stats、key_events 的完整报告。"
            )

        home_team = match_meta.get("home_team", "")
        away_team = match_meta.get("away_team", "")

        # Reconstruct raw event format from enriched key_events
        raw_events: list[dict] = []
        for ev in report_json.get("key_events", []):
            raw_team = "home" if ev.get("is_arsenal") and "Arsenal" in home_team else (
                "home" if not ev.get("is_arsenal") and "Arsenal" not in home_team else "away"
            )
            # Flip: if Arsenal is home and event is NOT arsenal → away
            arsenal_is_home = "Arsenal" in home_team
            if ev.get("is_arsenal"):
                raw_team = "home" if arsenal_is_home else "away"
            else:
                raw_team = "away" if arsenal_is_home else "home"

            raw_events.append({
                "minute": ev.get("minute", 0),
                "type": ev.get("raw_type", ev.get("type", "")),
                "team": raw_team,
                "player": ev.get("player", ""),
                "detail": ev.get("detail", ""),
            })

        # Build match-like dict for extract()
        match_json: dict = {
            "fixture_id": match_meta.get("fixture_id", ""),
            "date": match_meta.get("date", ""),
            "competition": match_meta.get("competition", ""),
            "home_team": home_team,
            "away_team": away_team,
            "home_score": match_meta.get("home_score", 0),
            "away_score": match_meta.get("away_score", 0),
            "events": raw_events,
        }

        # Carry over optional fields
        for opt in ("home_xg", "away_xg", "home_formation", "away_formation"):
            if opt in match_meta:
                match_json[opt] = match_meta[opt]

        # Carry over stats from report (report.stats may have nested arsenal/opponent shape
        # or list shape [home_val, away_val]; reconstruct home_stats/away_stats for extract_match_stats)
        report_stats = report_json.get("stats", {})
        if report_stats and not match_json.get("home_stats"):
            arsenal_is_home = "Arsenal" in home_team
            # Map (home/away) → side labels for dict-shaped stats
            home_side = "arsenal" if arsenal_is_home else "opponent"
            away_side = "opponent" if arsenal_is_home else "arsenal"
            # For list-shaped stats [home_val, away_val], indices are always home=0, away=1
            home_idx, away_idx = 0, 1

            home_stats: dict = {}
            away_stats: dict = {}
            for stat_key in ("possession", "shots", "shots_on_target", "fouls", "corners"):
                val = report_stats.get(stat_key, {})
                if isinstance(val, list) and len(val) >= 2:
                    # List shape: always [home_val, away_val]
                    h = val[home_idx]
                    a = val[away_idx]
                elif isinstance(val, dict):
                    h = val.get(home_side)
                    a = val.get(away_side)
                else:
                    continue
                if h is not None:
                    home_stats[stat_key] = h
                if a is not None:
                    away_stats[stat_key] = a
            # Pass accuracy (nested or list)
            passes = report_stats.get("passes", {})
            passes_acc = report_stats.get("passes_accuracy", [])
            for side, stats_dict in [(home_side, home_stats), (away_side, away_stats)]:
                if isinstance(passes_acc, list) and len(passes_acc) >= 2:
                    idx = home_idx if side == home_side else away_idx
                    acc = passes_acc[idx]
                elif isinstance(passes, dict):
                    acc = passes.get(side, {}).get("accuracy")
                else:
                    acc = None
                if acc is not None:
                    stats_dict["pass_accuracy"] = acc
            # xG from report stats
            xg = report_stats.get("xg", {})
            if isinstance(xg, dict):
                if xg.get(home_side) is not None:
                    home_stats["expected_goals"] = xg[home_side]
                if xg.get(away_side) is not None:
                    away_stats["expected_goals"] = xg[away_side]

            if home_stats:
                match_json["home_stats"] = home_stats
            if away_stats:
                match_json["away_stats"] = away_stats

        # Validate that we have at minimum score data
        has_score = (
            match_json.get("home_score") is not None
            and match_json.get("away_score") is not None
        )
        has_teams = bool(home_team) and bool(away_team)
        if not has_score or not has_teams:
            raise ValueError(
                "报告中 match 数据不完整——至少需要 home_team、away_team、"
                "home_score、away_score 才能提取特征。"
            )

        # Carry report context as override (don't re-infer from team names)
        report_context = report_json.get("context")

        return FeatureExtractor().extract(match_json, context_override=report_context or None)

    def extract(self, match_json: dict, *, context_override: dict | None = None) -> MatchFeatures:
        """Main entry point. Returns a fully populated MatchFeatures.

        Args:
            match_json: Normalized match JSON dict.
            context_override: If provided, use this context dict instead of
                re-inferring from extract_context(). Keys: opponent_quality,
                venue, competition_stage, opponent.
        """
        features = MatchFeatures()

        # ── Raw extractions from existing tools ──────────────────────
        stats = extract_match_stats(match_json)
        events = extract_key_events(match_json)
        context = context_override if context_override else extract_context(match_json)
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

        # Derive opponent name from team fields
        arsenal_side = _detect_arsenal_side(match_json)
        home_team = match_json.get("home_team", "")
        away_team = match_json.get("away_team", "")
        features.opponent_name = away_team if arsenal_side == "home" else home_team

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
            sub_player_names = {
                (s.get("player") or "").lower().strip()
                for s in arsenal_subs
            }
            for e in events:
                if (e.get("type") == "goal"
                        and e.get("is_arsenal")
                        and e.get("minute", 0) > first_sub_minute):
                    goals_after += 1
            features.goals_after_arsenal_subs = goals_after

            # ── Goals directly by substitutes ─────────────────────────
            # Count goals scored or assisted by a substitute player
            goals_by_subs = 0
            for e in events:
                if e.get("type") != "goal" or not e.get("is_arsenal"):
                    continue
                scorer = e.get("player", "").lower().strip()
                assister = e.get("assist", "").lower().strip()
                if scorer in sub_player_names or assister in sub_player_names:
                    goals_by_subs += 1
            features.goals_by_substitutes = goals_by_subs
        else:
            features.goals_after_arsenal_subs = 0
            features.goals_by_substitutes = 0

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
