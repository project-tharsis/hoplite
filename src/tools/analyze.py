"""Tool: analyze_match — run v3 tactical assessment against a match."""
import json
import sys
from datetime import datetime

from src.models.match import Match, MatchEvent
from src.report import ReportOrchestrator


def _infer_pre_match_context(match: Match) -> dict:
    """Infer pre-match context based solely on match metadata."""
    opponent = match.away_team if match.arsenal_is_home else match.home_team

    # Opponent quality tiers
    top6 = {
        "Man City", "Liverpool", "Chelsea", "Spurs", "Man Utd", "Newcastle"
    }
    european_elite = {
        "Real Madrid", "Bayern Munich", "Bayern", "PSG",
        "Barcelona", "Inter", "Inter Milan",
    }
    mid_table = {
        "Aston Villa", "Villa", "Brighton", "West Ham", "Crystal Palace",
        "Brentford", "Fulham", "Everton", "Nottingham Forest",
        "Bournemouth", "Wolves",
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
    venue = "home" if match.arsenal_is_home else "away"

    # Competition stage
    month = match.date.month
    if "Premier League" in match.competition:
        competition_stage = "league_late" if month in {2, 3, 4, 5} else "league_early"
    elif "Champions League" in match.competition:
        competition_stage = "knockout" if month in {3, 4, 5} else "group_stage"
    else:
        competition_stage = "regular"

    return {
        "opponent_quality": opponent_quality,
        "venue": venue,
        "competition_stage": competition_stage,
        "injury_situation": "full_strength",
        "recent_form": "mixed",
        "opponent_style": "possession",
    }


def analyze_match(match_json: dict, search_queries: list = None) -> dict:
    """Run v3 tactical analysis on a match. Returns report + search queries."""
    # Deserialize Match
    m = Match(
        fixture_id=match_json["fixture_id"],
        date=datetime.fromisoformat(match_json["date"]),
        competition=match_json["competition"],
        home_team=match_json["home_team"],
        away_team=match_json["away_team"],
        home_score=match_json["home_score"],
        away_score=match_json["away_score"],
        home_xg=match_json.get("home_xg"),
        away_xg=match_json.get("away_xg"),
        home_formation=match_json.get("home_formation"),
        away_formation=match_json.get("away_formation"),
        events=[MatchEvent(**e) for e in match_json.get("events", [])],
        home_lineup=match_json.get("home_lineup", []),
        away_lineup=match_json.get("away_lineup", []),
    )

    # Build pre-match context from match metadata
    pre_match_context = _infer_pre_match_context(m)

    # Run v3 pipeline: predictor → mental models → 3D assessment → knowledge base
    orchestrator = ReportOrchestrator()
    report = orchestrator.generate(m, pre_match_context)

    return {
        "report": report.to_dict(),
        "search_queries": search_queries if search_queries is not None else [],
    }


if __name__ == "__main__":
    input_data = json.load(sys.stdin)
    result = analyze_match(input_data)
    print(json.dumps(result, indent=2, ensure_ascii=False))
