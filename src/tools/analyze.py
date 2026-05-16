"""Tool: analyze_match — run 6 tactical lenses against a match."""
import json
import sys
from datetime import datetime
from src.models.match import Match
from src.report import ReportOrchestrator
from src.data.search_source import build_match_report_query


def analyze_match(match_json: dict, search_queries: list = None) -> dict:
    """Run tactical analysis on a match. Returns report + search queries."""
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
        events=match_json.get("events", []),
        home_lineup=match_json.get("home_lineup", []),
        away_lineup=match_json.get("away_lineup", []),
    )

    # Run 6 lenses
    orchestrator = ReportOrchestrator()
    report = orchestrator.generate(m)

    # Build search queries for agent
    if search_queries is None:
        opponent = m.away_team if m.arsenal_is_home else m.home_team
        search_queries = [build_match_report_query(opponent, m.date.strftime("%Y-%m-%d"))]
        # Add trend queries for top lenses
        search_queries.extend([
            "Arsenal set pieces analysis " + m.date.strftime("%Y-%m"),
            "Arsenal tactical patterns " + opponent + " post-match",
        ])

    # Serialize report
    results_json = []
    for r in report.results:
        results_json.append({
            "lens_name": r.lens_name,
            "summary": r.summary,
            "score": r.score,
            "key_moments": r.key_moments,
            "insights": r.insights,
        })

    return {
        "report": {
            "overall_score": report.overall_score,
            "one_line_summary": report.one_line_summary,
            "results": results_json,
        },
        "search_queries": search_queries,
    }


if __name__ == "__main__":
    input_data = json.load(sys.stdin)
    result = analyze_match(input_data)
    print(json.dumps(result, indent=2, ensure_ascii=False))
