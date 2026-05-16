"""Tool: extract — pure data extraction from match JSON. NO judgment, NO scoring."""
from __future__ import annotations


def _detect_arsenal_side(match_json: dict) -> str:
    """Return 'home' or 'away' depending on where Arsenal is."""
    if "Arsenal" in match_json.get("home_team", ""):
        return "home"
    return "away"


def _opponent_side(arsenal_side: str) -> str:
    return "away" if arsenal_side == "home" else "home"


# ── extract_match_stats ──────────────────────────────────────────────

def extract_match_stats(match_json: dict) -> dict:
    """Pure stat aggregation. Returns raw numbers only — no judgment.

    Maps scores, xG, and event-derived counts (goals, cards) into a
    consistent {arsenal: ..., opponent: ...} structure regardless of
    home/away status.
    """
    arsenal_side = _detect_arsenal_side(match_json)
    opp_side = _opponent_side(arsenal_side)

    home_score = match_json.get("home_score", 0) or 0
    away_score = match_json.get("away_score", 0) or 0
    arsenal_score = home_score if arsenal_side == "home" else away_score
    opponent_score = away_score if arsenal_side == "home" else home_score

    home_xg = match_json.get("home_xg")
    away_xg = match_json.get("away_xg")
    arsenal_xg = home_xg if arsenal_side == "home" else away_xg
    opponent_xg = away_xg if arsenal_side == "home" else home_xg

    # Count goals and cards from events
    events = match_json.get("events", [])
    goals = {"arsenal": {"first_half": 0, "second_half": 0},
             "opponent": {"first_half": 0, "second_half": 0}}
    cards = {"arsenal": {"yellow": 0, "red": 0},
             "opponent": {"yellow": 0, "red": 0}}

    for e in events:
        side_key = "arsenal" if e.get("team") == arsenal_side else "opponent"
        if e.get("type") == "goal":
            minute = e.get("minute", 0) or 0
            if minute <= 45:
                goals[side_key]["first_half"] += 1
            else:
                goals[side_key]["second_half"] += 1
        elif e.get("type") == "card":
            detail_lower = (e.get("detail") or "").lower()
            if "red" in detail_lower:
                cards[side_key]["red"] += 1
            else:
                # Default to yellow if not explicitly red
                cards[side_key]["yellow"] += 1

    goals["arsenal"]["total"] = goals["arsenal"]["first_half"] + goals["arsenal"]["second_half"]
    goals["opponent"]["total"] = goals["opponent"]["first_half"] + goals["opponent"]["second_half"]

    return {
        "score": {"arsenal": arsenal_score, "opponent": opponent_score},
        "xg": {"arsenal": arsenal_xg, "opponent": opponent_xg},
        "goals": goals,
        "cards": cards,
    }


# ── extract_key_events ───────────────────────────────────────────────

def extract_key_events(match_json: dict) -> list[dict]:
    """Extract ALL events with rich context.

    Each event includes is_arsenal flag and resolved team name.
    """
    arsenal_side = _detect_arsenal_side(match_json)
    home_team = match_json.get("home_team", "Home")
    away_team = match_json.get("away_team", "Away")

    def _team_name(event_team: str) -> str:
        if event_team == arsenal_side:
            return "Arsenal"
        return home_team if arsenal_side == "away" else away_team

    return [
        {
            "minute": e.get("minute", 0),
            "type": e.get("type", ""),
            "team": _team_name(e.get("team", "")),
            "player": e.get("player", ""),
            "detail": e.get("detail", ""),
            "is_arsenal": e.get("team") == arsenal_side,
        }
        for e in match_json.get("events", [])
    ]


# ── extract_set_piece_goals ──────────────────────────────────────────

SET_PIECE_KEYWORDS = [
    "corner", "free kick", "set piece", "header from corner",
    "direct free kick", "penalty", "cross from free kick",
]


def extract_set_piece_goals(events: list[dict]) -> dict:
    """Count set-piece-related goals from event detail text.

    Returns counts per side plus a human-readable detail list.
    No scoring — just raw extraction.
    """
    arsenal_count = 0
    opponent_count = 0
    details: list[str] = []

    for e in events:
        if e.get("type") != "goal":
            continue
        detail_lower = (e.get("detail") or "").lower()
        is_set_piece = any(kw in detail_lower for kw in SET_PIECE_KEYWORDS)
        if not is_set_piece:
            continue

        minute = e.get("minute", 0)
        player = e.get("player", "")
        desc = f"{minute}' {player} — {e.get('detail', '')}"
        details.append(desc)

        if e.get("is_arsenal"):
            arsenal_count += 1
        else:
            opponent_count += 1

    return {
        "arsenal": arsenal_count,
        "opponent": opponent_count,
        "details": details,
    }


# ── extract_context ──────────────────────────────────────────────────

def extract_context(match_json: dict) -> dict:
    """Extract pre-match context (opponent quality, venue, stage).

    Pure data inference from metadata — no qualitative judgment.
    """
    arsenal_side = _detect_arsenal_side(match_json)
    opponent = (
        match_json["away_team"] if arsenal_side == "home"
        else match_json["home_team"]
    )

    # Opponent quality tiers
    top6 = {"Man City", "Liverpool", "Chelsea", "Spurs", "Man Utd", "Newcastle"}
    european_elite = {
        "Real Madrid", "Bayern Munich", "Bayern", "PSG",
        "Barcelona", "Inter", "Inter Milan",
    }
    mid_table = {
        "Aston Villa", "Villa", "Brighton", "West Ham", "Crystal Palace",
        "Brentford", "Fulham", "Everton", "Nottingham Forest",
        "Bournemouth", "Wolves", "PSV", "PSV Eindhoven",
        "Sporting", "Sporting CP", "Sporting Lisbon",
        "Leverkusen", "Bayer Leverkusen", "Atletico", "Atletico Madrid",
        "Roma", "Napoli", "Lazio", "Fiorentina", "Monaco",
    }

    if opponent in top6:
        opponent_quality = "top6"
    elif opponent in european_elite:
        opponent_quality = "european_elite"
    elif opponent in mid_table:
        opponent_quality = "mid_table"
    else:
        opponent_quality = "lower"

    # Venue
    venue = "home" if arsenal_side == "home" else "away"

    # Competition stage
    date_str = match_json.get("date", "")
    month = 8  # sensible default
    if date_str:
        try:
            month = int(date_str.split("-")[1])
        except (ValueError, IndexError):
            pass

    competition = match_json.get("competition", "")
    if "Premier League" in competition:
        competition_stage = "league_late" if month in {2, 3, 4, 5} else "league_early"
    elif "Champions League" in competition:
        competition_stage = "knockout" if month in {3, 4, 5} else "group_stage"
    else:
        competition_stage = "regular"

    return {
        "opponent": opponent,
        "opponent_quality": opponent_quality,
        "venue": venue,
        "competition_stage": competition_stage,
        "injury_situation": "full_strength",
        "recent_form": "mixed",
        "opponent_style": "possession",
    }


# ── extract_sub_impact ───────────────────────────────────────────────

def extract_sub_impact(events: list[dict]) -> list[dict]:
    """Extract substitution events + whether the sub scored afterward.

    Returns a list of dicts with sub info and a scored_after flag.
    Requires events to include is_arsenal key (from extract_key_events).
    """
    subs = []
    goals_after: dict[str, list[int]] = {}

    # First pass: collect all goals with player + minute
    for e in events:
        if e.get("type") == "goal":
            player = e.get("player", "")
            goals_after.setdefault(player, []).append(e.get("minute", 0))

    # Second pass: extract substitutions
    for e in events:
        if e.get("type") != "substitution":
            continue
        sub_minute = e.get("minute", 0)
        player = e.get("player", "")
        detail = e.get("detail", "")
        # Check if the subbed-on player scored after coming on
        scored_after = False
        if player in goals_after:
            scored_after = any(m > sub_minute for m in goals_after[player])

        subs.append({
            "minute": sub_minute,
            "player": player,
            "detail": detail,
            "is_arsenal": e.get("is_arsenal", False),
            "scored_after": scored_after,
        })

    return subs
