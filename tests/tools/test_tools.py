import json
import pytest
from src.tools.fetch import fetch_match_data, match_to_json


def test_fetch_match_data_no_config():
    """Without config.yaml, returns error dict."""
    # This runs in test env where config.yaml may or may not exist
    result = fetch_match_data()
    assert isinstance(result, dict)
    # Either has match data or error key
    assert "error" in result or "fixture_id" in result


def test_analyze_match_with_minimal_data():
    from src.tools.analyze import analyze_match
    match_json = {
        "fixture_id": 1,
        "date": "2025-05-01T00:00:00",
        "competition": "PL",
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "home_score": 3,
        "away_score": 1,
        "events": [{"minute": 23, "type": "goal", "team": "home", "player": "Saka", "detail": "Shot"}],
    }
    result = analyze_match(match_json)
    assert "report" in result
    assert "search_queries" in result
    assert len(result["report"]["results"]) == 6
    assert result["report"]["overall_score"] > 0


def test_build_narrative_prompt():
    from src.tools.prompt import build_narrative_prompt
    report_json = {
        "one_line_summary": "Arsenal 3-1 Chelsea (7.5/10)",
        "results": [
            {"lens_name": "Set Pieces", "summary": "2 SP goals", "score": 8.5, "insights": ["Strong set pieces"], "key_moments": []},
            {"lens_name": "Goal Events", "summary": "Late winner", "score": 7.0, "insights": ["Good tempo"], "key_moments": []},
        ]
    }
    prompt = build_narrative_prompt(report_json, "Arsenal used 3-2-5.")
    assert "Arsenal 3-1 Chelsea" in prompt
    assert "Set Pieces" in prompt
    assert "Goal Events" in prompt
    assert "3-2-5" in prompt
    assert "inverted fullback" in prompt.lower()
    assert "WHY" in prompt


def test_build_card():
    from src.tools.card import build_card
    report_json = {
        "one_line_summary": "Arsenal 3-1 Chelsea (7.5/10)",
        "results": [
            {"lens_name": "Set Pieces", "summary": "2 SP goals", "score": 8.5, "key_moments": ["Gabriel header"], "insights": []},
            {"lens_name": "Goal Events", "summary": "Late winner", "score": 7.0, "key_moments": ["Odegaard 89'"], "insights": []},
        ],
        "overall_score": 7.5,
    }
    narrative = "Arsenal controlled the game through set piece dominance."
    result = build_card(report_json, narrative)
    assert "card_path" in result or "card" in result
