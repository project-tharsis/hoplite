"""Tool: analyze_match — extract raw data from match. No judgment."""
import json
import sys
from datetime import datetime

from src.models.match import Match, MatchEvent
from src.report import ReportOrchestrator
from src.tools.extract import (
    extract_match_stats,
    extract_key_events,
    extract_context,
    extract_set_piece_goals,
    extract_sub_impact,
)


def analyze_match(match_json: dict, search_queries: list = None) -> dict:
    """Extract raw match data. Returns pure data report + search_queries."""
    # Guard: if upstream returned an error, propagate it
    if match_json.get("ok") is False or ("error" in match_json and "fixture_id" not in match_json):
        return {
            "ok": False,
            "error": match_json.get("error", {
                "code": "UPSTREAM_ERROR",
                "message": str(match_json.get("error"))
            }),
        }

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

    # Extract pure data — no judgment
    stats = extract_match_stats(match_json)
    events = extract_key_events(match_json)
    context = extract_context(match_json)
    set_pieces = extract_set_piece_goals(events)
    subs = extract_sub_impact(events)

    # Assemble report
    orchestrator = ReportOrchestrator()
    report = orchestrator.assemble(m, stats, events, context, set_pieces, subs)

    return {
        "ok": True,
        "report": report.to_dict(),
        "search_queries": search_queries if search_queries is not None else [],
    }


if __name__ == "__main__":
    input_data = json.load(sys.stdin)
    result = analyze_match(input_data)
    print(json.dumps(result, indent=2, ensure_ascii=False))
