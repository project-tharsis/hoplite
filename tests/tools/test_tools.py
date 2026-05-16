import json
import pytest
from unittest.mock import patch, Mock
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


@patch("src.data.football_data.requests.Session.get")
@patch("src.data.api_football.requests.Session.get")
def test_fetch_match_data_with_api_football_merge(mock_af_get, mock_fd_get):
    """API-Football events and lineups merge into fetch output."""
    from src.tools.fetch import fetch_match_data

    # football-data.org response
    fd_resp = Mock()
    fd_resp.json.return_value = {
        "matches": [
            {
                "id": 538144,
                "utcDate": "2024-03-10T16:30:00Z",
                "competition": {"name": "Premier League"},
                "homeTeam": {"name": "Arsenal"},
                "awayTeam": {"name": "Chelsea FC"},
                "score": {"fullTime": {"home": 3, "away": 1}},
            }
        ]
    }
    fd_resp.raise_for_status = Mock()

    # API-Football fixture search
    af_fixture_resp = Mock()
    af_fixture_resp.json.return_value = {
        "response": [
            {
                "fixture": {"id": 888888, "date": "2024-03-10T16:30:00+00:00"},
                "teams": {"home": {"name": "Arsenal FC", "id": 42}, "away": {"name": "Chelsea FC", "id": 61}},
            }
        ]
    }
    af_fixture_resp.raise_for_status = Mock()

    # API-Football events
    af_events_resp = Mock()
    af_events_resp.json.return_value = {
        "response": [
            {"time": {"elapsed": 12}, "type": "Goal", "team": {"id": 42, "name": "Arsenal FC"}, "player": {"name": "Saka"}, "detail": "Normal Goal", "comments": None},
            {"time": {"elapsed": 55}, "type": "Card", "team": {"id": 61, "name": "Chelsea FC"}, "player": {"name": "Caicedo"}, "detail": "Yellow Card", "comments": "Foul"},
        ]
    }
    af_events_resp.raise_for_status = Mock()

    # API-Football lineups
    af_lineups_resp = Mock()
    af_lineups_resp.json.return_value = {
        "response": [
            {"team": {"id": 42, "name": "Arsenal FC"}, "formation": "4-3-3", "startXI": []},
            {"team": {"id": 61, "name": "Chelsea FC"}, "formation": "4-2-3-1", "startXI": []},
        ]
    }
    af_lineups_resp.raise_for_status = Mock()

    def unified_side_effect(url, params=None, **kwargs):
        if "api.football-data.org" in url:
            return fd_resp
        if "/fixtures/events" in url:
            return af_events_resp
        if "/fixtures/lineups" in url:
            return af_lineups_resp
        return af_fixture_resp

    mock_fd_get.side_effect = unified_side_effect
    mock_af_get.side_effect = unified_side_effect

    result = fetch_match_data()

    assert "error" not in result
    assert len(result["events"]) == 2
    assert result["events"][0]["player"] == "Saka"
    assert result["events"][0]["team"] == "home"
    assert result["home_formation"] == "4-3-3"
    assert result["away_formation"] == "4-2-3-1"
