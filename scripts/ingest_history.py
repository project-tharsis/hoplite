#!/usr/bin/env python3
"""Batch ingest historical Arsenal matches into knowledge base.

Usage:
    python scripts/ingest_history.py --season 2024 --league 39 --dry-run
    python scripts/ingest_history.py --season 2023 --league 39
    python scripts/ingest_history.py --season 2022 --league 2
"""

import argparse
import json
import sys
import time
from pathlib import Path

import requests
import yaml

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.knowledge import KnowledgeBase
from src.evaluation.predictor import ArtetaPredictor

# ── Constants ─────────────────────────────────────────────────────────

ARSENAL_TEAM_ID = 42
LEAGUE_NAMES = {
    39: "Premier League",
    2: "Champions League",
}

# Opponent quality tiers (same as src/tools/extract.py)
TOP6 = {"Man City", "Liverpool", "Chelsea", "Tottenham", "Tottenham Hotspur", "Man Utd", "Newcastle"}
EUROPEAN_ELITE = {
    "Real Madrid", "Bayern Munich", "Bayern", "PSG",
    "Barcelona", "Inter", "Inter Milan",
}
MID_TABLE = {
    "Aston Villa", "Villa", "Brighton", "West Ham", "Crystal Palace",
    "Brentford", "Fulham", "Everton", "Nottingham Forest",
    "Bournemouth", "Wolves", "PSV", "PSV Eindhoven",
    "Sporting", "Sporting CP", "Sporting Lisbon",
    "Leverkusen", "Bayer Leverkusen", "Atletico", "Atletico Madrid",
    "Roma", "Napoli", "Lazio", "Fiorentina", "Monaco",
}


# ── API helpers ───────────────────────────────────────────────────────

def load_config() -> dict:
    config_path = PROJECT_ROOT / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def make_session(key: str) -> requests.Session:
    s = requests.Session()
    s.headers["x-apisports-key"] = key
    return s


def api_get(session: requests.Session, endpoint: str, params: dict, max_retries: int = 3) -> dict:
    """Make an API call with rate-limit retry handling."""
    base = "https://v3.football.api-sports.io"
    for attempt in range(max_retries):
        resp = session.get(f"{base}/{endpoint}", params=params)
        if resp.status_code == 429:
            wait = 2 ** attempt * 5  # 5s, 10s, 20s
            print(f"  ⏳ Rate limited (429). Waiting {wait}s before retry...", file=sys.stderr)
            time.sleep(wait)
            continue
        resp.raise_for_status()
        data = resp.json()
        return data.get("response", [])
    # Final attempt
    resp.raise_for_status()
    return []


# ── Data fetching ─────────────────────────────────────────────────────

def fetch_fixtures(session: requests.Session, season: int, league_id: int) -> list[dict]:
    """Fetch all Arsenal finished fixtures for a season/league."""
    params = {
        "team": ARSENAL_TEAM_ID,
        "season": season,
        "league": league_id,
        "status": "FT",  # Finished matches only
    }
    return api_get(session, "fixtures", params)


def fetch_events(session: requests.Session, fixture_id: int) -> list[dict]:
    """Fetch events (goals, cards, subs) for a fixture."""
    return api_get(session, "fixtures/events", {"fixture": fixture_id})


def fetch_lineups(session: requests.Session, fixture_id: int) -> list[dict]:
    """Fetch starting lineups and formations."""
    return api_get(session, "fixtures/lineups", {"fixture": fixture_id})


# ── Parsing helpers ───────────────────────────────────────────────────

def get_team_name(team_data: dict) -> str:
    """Extract team name from API-Football team object."""
    name = team_data.get("name", "")
    # Normalize some names to match our KB conventions
    name_map = {
        "Manchester United": "Man Utd",
        "Manchester City": "Man City",
        "Tottenham Hotspur": "Tottenham",
        "Newcastle United": "Newcastle",
        "Wolverhampton Wanderers": "Wolves",
        "West Ham United": "West Ham",
        "Brighton & Hove Albion": "Brighton",
        "Nottingham Forest": "Nottingham Forest",
        "AFC Bournemouth": "Bournemouth",
        "Crystal Palace": "Crystal Palace",
        "Aston Villa": "Aston Villa",
        "Leicester City": "Leicester",
        "Southampton": "Southampton",
        "Ipswich Town": "Ipswich",
        "Bayern München": "Bayern Munich",
        "Atletico Madrid": "Atletico Madrid",
        "Bayer Leverkusen": "Leverkusen",
        "Sporting CP": "Sporting",
        "PSV Eindhoven": "PSV",
        "Inter": "Inter Milan",
    }
    return name_map.get(name, name)


def classify_opponent(opponent_name: str) -> str:
    """Classify opponent into quality tier."""
    if opponent_name in TOP6:
        return "top6"
    if opponent_name in EUROPEAN_ELITE:
        return "european_elite"
    if opponent_name in MID_TABLE:
        return "mid_table"
    return "lower"


def infer_competition_stage(competition: str, match_date_str: str) -> str:
    """Infer competition stage from competition name and date."""
    month = 8
    if match_date_str:
        try:
            month = int(match_date_str.split("-")[1])
        except (ValueError, IndexError):
            pass

    if "Premier League" in competition:
        return "league_late" if month in {2, 3, 4, 5} else "league_early"
    if "Champions League" in competition:
        return "knockout" if month in {2, 3, 4, 5} else "group_stage"
    return "regular"


def parse_events(events_raw: list[dict], arsenal_is_home: bool) -> list[dict]:
    """Parse API-Football events into our format."""
    events = []
    for ev in events_raw:
        time_data = ev.get("time", {})
        team_data = ev.get("team", {})
        player_data = ev.get("player", {})
        assist_data = ev.get("assist", {})

        team_id = team_data.get("id", 0)
        is_arsenal = team_id == ARSENAL_TEAM_ID
        side = "home" if (is_arsenal and arsenal_is_home) or (not is_arsenal and not arsenal_is_home) else "away"

        ev_type = ev.get("type", "").lower()
        detail = ev.get("detail", "")
        comments = ev.get("comments", "") or ""

        events.append({
            "minute": time_data.get("elapsed", 0),
            "type": ev_type,
            "team": side,
            "player": player_data.get("name", ""),
            "detail": f"{detail} {comments}".strip(),
        })
    return events


def parse_lineups(lineups_raw: list[dict], arsenal_is_home: bool) -> dict:
    """Parse lineups to extract formations."""
    formations = {"home": None, "away": None}
    for lu in lineups_raw:
        team_id = lu.get("team", {}).get("id", 0)
        formation = lu.get("formation")
        is_arsenal = team_id == ARSENAL_TEAM_ID
        side = "home" if (is_arsenal and arsenal_is_home) or (not is_arsenal and not arsenal_is_home) else "away"
        formations[side] = formation
    return formations


# ── Build match entry ─────────────────────────────────────────────────

def build_match_entry(
    fixture: dict,
    events_raw: list[dict],
    lineups_raw: list[dict],
    competition: str,
    predictor: ArtetaPredictor,
) -> dict:
    """Build a KB entry from API-Football fixture data."""
    fixture_data = fixture["fixture"]
    teams = fixture["teams"]
    # Prefer score.fulltime as primary source (more reliable), fall back to goals
    score_wrapper = fixture.get("score", {}) or {}
    fulltime = score_wrapper.get("fulltime", {}) or {}
    goals = fixture.get("goals", {}) or {}

    fixture_id = str(fixture_data["id"])
    match_date = fixture_data["date"]  # ISO format from API

    home_name = get_team_name(teams["home"])
    away_name = get_team_name(teams["away"])
    # Use fulltime score first, fall back to goals
    home_score = fulltime.get("home") if fulltime.get("home") is not None else goals.get("home", 0)
    away_score = fulltime.get("away") if fulltime.get("away") is not None else goals.get("away", 0)
    home_score = home_score or 0
    away_score = away_score or 0

    arsenal_is_home = teams["home"]["id"] == ARSENAL_TEAM_ID
    opponent_name = away_name if arsenal_is_home else home_name
    arsenal_score = home_score if arsenal_is_home else away_score
    opponent_score = away_score if arsenal_is_home else home_score

    # Result
    if arsenal_score > opponent_score:
        result = "W"
    elif arsenal_score < opponent_score:
        result = "L"
    else:
        result = "D"

    # Parse events and lineups
    events = parse_events(events_raw, arsenal_is_home)
    formations = parse_lineups(lineups_raw, arsenal_is_home)

    # Build context
    opponent_quality = classify_opponent(opponent_name)
    venue = "home" if arsenal_is_home else "away"
    competition_stage = infer_competition_stage(competition, match_date[:10] if match_date else "")

    pre_match_context = {
        "opponent_quality": opponent_quality,
        "venue": venue,
        "competition_stage": competition_stage,
        "injury_situation": "full_strength",  # Unknown for historical
        "recent_form": "mixed",  # Unknown for historical
        "opponent_style": "possession",  # Default assumption
    }

    # Predict plan
    plan = predictor.predict(pre_match_context)

    return {
        "match_id": fixture_id,
        "timestamp": match_date,
        "opponent": opponent_name,
        "score": f"{arsenal_score}-{opponent_score}",
        "result": result,
        "competition": competition,
        "pre_match_context": pre_match_context,
        "predicted_plan": {
            "focus_areas": plan.focus_areas,
            "likely_approach": plan.likely_approach,
            "key_battles": plan.key_battles,
            "expected_subs": plan.expected_subs,
        },
        # No LLM evaluation for historical matches
        "evaluation": {"model_signals": {}, "dimension_signals": {}},
    }


# ── Main ingest logic ─────────────────────────────────────────────────

def ingest_season(
    season: int,
    league_id: int,
    kb: KnowledgeBase,
    predictor: ArtetaPredictor,
    session: requests.Session,
    dry_run: bool = False,
) -> dict:
    """Ingest all Arsenal fixtures for a season/league into the KB."""
    competition = LEAGUE_NAMES.get(league_id, f"League {league_id}")

    # Get existing match_ids for idempotency
    existing_ids = {e.get("match_id") for e in kb.get_all()}

    print(f"\n📥 Fetching {competition} {season} fixtures...")
    fixtures = fetch_fixtures(session, season, league_id)

    if not fixtures:
        print("  No finished fixtures found.")
        return {"total": 0, "new": 0, "skipped": 0}

    total = len(fixtures)
    new_count = 0
    skipped = 0

    print(f"  Found {total} finished fixtures.\n")

    for i, fixture in enumerate(fixtures, 1):
        fixture_id = str(fixture["fixture"]["id"])
        home_name = get_team_name(fixture["teams"]["home"])
        away_name = get_team_name(fixture["teams"]["away"])
        date_str = fixture["fixture"]["date"][:10]

        # Idempotency check
        if fixture_id in existing_ids:
            print(f"  [{i}/{total}] ⏭ {date_str} {home_name} vs {away_name} (already in KB)")
            skipped += 1
            continue

        print(f"  [{i}/{total}] 📋 {date_str} {home_name} vs {away_name}", end="")

        # Fetch events and lineups (2 API calls per fixture)
        time.sleep(2)  # Rate limit: ~30 req/min for free tier
        events_raw = fetch_events(session, fixture["fixture"]["id"])
        time.sleep(2)  # Rate limit
        lineups_raw = fetch_lineups(session, fixture["fixture"]["id"])

        # Build entry
        entry = build_match_entry(fixture, events_raw, lineups_raw, competition, predictor)

        score = entry["score"]
        result = entry["result"]
        result_emoji = {"W": "🟢", "D": "🟡", "L": "🔴"}[result]
        print(f" → {score} {result_emoji}")

        if dry_run:
            print(f"    [DRY RUN] Would save: {json.dumps(entry, ensure_ascii=False)[:200]}...")
        else:
            kb.save_entry(entry)
            existing_ids.add(fixture_id)

        new_count += 1

    return {"total": total, "new": new_count, "skipped": skipped}


# ── CLI ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Batch ingest historical Arsenal matches")
    parser.add_argument("--season", type=int, default=2024, help="Season year (e.g. 2024)")
    parser.add_argument("--league", type=int, default=39, help="League ID (39=PL, 2=CL)")
    parser.add_argument("--dry-run", action="store_true", help="Print without saving")
    args = parser.parse_args()

    print("=" * 60)
    print("⚽ Hoplite Historical Ingest")
    print(f"   Season: {args.season}  |  League: {LEAGUE_NAMES.get(args.league, args.league)}")
    print(f"   Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    print("=" * 60)

    config = load_config()
    key = config["data_sources"]["api_football"]["key"]
    session = make_session(key)

    kb = KnowledgeBase()
    predictor = ArtetaPredictor()

    stats = ingest_season(
        season=args.season,
        league_id=args.league,
        kb=kb,
        predictor=predictor,
        session=session,
        dry_run=args.dry_run,
    )

    print("\n" + "=" * 60)
    print(f"✅ Done! Total: {stats['total']} | New: {stats['new']} | Skipped: {stats['skipped']}")
    if args.dry_run:
        print("   (Dry run — nothing was saved)")
    print("=" * 60)


if __name__ == "__main__":
    main()
