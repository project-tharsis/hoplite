import json
import pytest
from unittest.mock import patch, Mock
from src.tools.fetch import fetch_match_data, match_to_json


def test_fetch_match_data_no_config():
    """Without config.yaml, returns error dict."""
    result = fetch_match_data()
    assert isinstance(result, dict)
    assert "error" in result or "fixture_id" in result


def test_analyze_match_with_minimal_data():
    from src.tools.analyze import analyze_match
    match_json = {
        "fixture_id": 1,
        "date": "2025-05-01T00:00:00",
        "competition": "Premier League",
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "home_score": 3,
        "away_score": 1,
        "events": [{"minute": 23, "type": "goal", "team": "home", "player": "Saka", "detail": "Shot"}],
    }
    result = analyze_match(match_json)
    report = result["report"]
    assert "report" in result
    assert "search_queries" in result
    # v4 schema: pure data report — no judgment fields
    assert "stats" in report
    assert "key_events" in report
    assert "context" in report
    assert "set_pieces" in report
    assert "sub_impact" in report
    assert "predicted_plan" in report
    assert "one_line_summary" in report
    # Verify NO judgment fields (v4 removed these)
    assert "mental_model_results" not in report
    assert "overall_score" not in report
    assert "overall_signal" not in report


def test_analyze_match_with_error_payload():
    """analyze_match handles upstream error without KeyError."""
    from src.tools.analyze import analyze_match
    error_json = {
        "ok": False,
        "error": {"code": "CONFIG_MISSING", "message": "config.yaml not found"},
    }
    result = analyze_match(error_json)
    assert result.get("ok") is False
    assert "error" in result
    # Must NOT have 'fixture_id' KeyError — should not reach Match construction
    assert "report" not in result


def test_analyze_match_stdin_error():
    """python -m src analyze_match with error JSON doesn't crash."""
    import subprocess
    import json
    error_input = json.dumps({"ok": False, "error": {"code": "TEST", "message": "test error"}})
    result = subprocess.run(
        ["python3", "-m", "src", "analyze_match"],
        input=error_input, capture_output=True, text=True, cwd="/tmp/hoplite",
    )
    # Should not crash with traceback
    assert result.returncode == 0
    parsed = json.loads(result.stdout)
    assert parsed.get("ok") is False


def test_build_narrative_prompt():
    from src.tools.prompt import build_narrative_prompt
    report_json = {
        "one_line_summary": "Arsenal 3-1 Chelsea (Premier League)",
        "predicted_plan": {
            "focus_areas": ["控制中场"],
            "likely_approach": "高位防线",
            "key_battles": ["中场对抗"],
            "expected_subs": "60' 边路换人",
        },
        "context": {
            "opponent_quality": "top6",
            "venue": "home",
            "competition_stage": "league_late",
        },
        "stats": {
            "score": {"arsenal": 3, "opponent": 1},
            "xg": {"arsenal": 2.5, "opponent": 0.6},
            "goals": {"arsenal": {"first_half": 1, "second_half": 2, "total": 3},
                      "opponent": {"first_half": 0, "second_half": 1, "total": 1}},
            "cards": {"arsenal": {"yellow": 0, "red": 0},
                      "opponent": {"yellow": 1, "red": 0}},
        },
        "key_events": [
            {"minute": 23, "type": "goal", "team": "Arsenal", "player": "Saka", "detail": "Shot", "is_arsenal": True},
        ],
        "set_pieces": {"arsenal": 0, "opponent": 0, "details": []},
        "sub_impact": [],
    }
    prompt = build_narrative_prompt(report_json, "Arsenal used 3-2-5 build-up.")
    assert "Arsenal 3-1 Chelsea" in prompt
    assert "3-2-5" in prompt
    # v4 prompt has Arteta framework with key Chinese phrases
    assert "心智模型" in prompt
    assert "评估框架" in prompt
    assert "Arteta" in prompt
    # Check writing style section exists
    assert "写作要求" in prompt
    # Check output format instructions exist
    assert "输出格式" in prompt


def test_build_card():
    from src.tools.card import build_card
    report_json = {
        "fixture_id": 123,
        "one_line_summary": "Arsenal 3-1 Chelsea (Premier League)",
        "stats": {
            "score": {"arsenal": 3, "opponent": 1},
        },
        "key_events": [],
        "context": {},
        "set_pieces": {},
        "sub_impact": [],
        "predicted_plan": {},
    }
    narrative = "阿森纳通过定位球控制和边路overload掌控了比赛节奏。"
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

    # API-Football statistics
    af_stats_resp = Mock()
    af_stats_resp.json.return_value = {
        "response": [
            {
                "team": {"id": 42, "name": "Arsenal FC"},
                "statistics": [
                    {"type": "Ball Possession", "value": "58%"},
                    {"type": "Total Shots", "value": 15},
                    {"type": "Shots on Goal", "value": 6},
                    {"type": "Total passes", "value": 512},
                    {"type": "Passes %", "value": "87%"},
                    {"type": "Fouls", "value": 8},
                    {"type": "Corner Kicks", "value": 7},
                    {"type": "Yellow Cards", "value": 1},
                    {"type": "Red Cards", "value": 0},
                ],
            },
            {
                "team": {"id": 61, "name": "Chelsea FC"},
                "statistics": [
                    {"type": "Ball Possession", "value": "42%"},
                    {"type": "Total Shots", "value": 8},
                    {"type": "Shots on Goal", "value": 3},
                    {"type": "Total passes", "value": 389},
                    {"type": "Passes %", "value": "79%"},
                    {"type": "Fouls", "value": 12},
                    {"type": "Corner Kicks", "value": 4},
                    {"type": "Yellow Cards", "value": 2},
                    {"type": "Red Cards", "value": 0},
                ],
            },
        ]
    }
    af_stats_resp.raise_for_status = Mock()

    def unified_side_effect(url, params=None, **kwargs):
        if "api.football-data.org" in url:
            return fd_resp
        if "/fixtures/statistics" in url:
            return af_stats_resp
        if "/fixtures/events" in url:
            return af_events_resp
        if "/fixtures/lineups" in url:
            return af_lineups_resp
        return af_fixture_resp

    mock_fd_get.side_effect = unified_side_effect
    mock_af_get.side_effect = unified_side_effect

    mock_config = {
        "data_sources": {
            "football_data": {"token": "test-fd-token"},
            "api_football": {"key": "test-af-key"},
        },
        "arsenal": {
            "team_id_football_data": 57,
            "team_id_api_football": 42,
        },
    }

    result = fetch_match_data(config=mock_config)

    assert "error" not in result
    assert len(result["events"]) == 2
    assert result["events"][0]["player"] == "Saka"
    assert result["events"][0]["team"] == "home"
    assert result["home_formation"] == "4-3-3"
    assert result["away_formation"] == "4-2-3-1"
    assert result["home_stats"] is not None
    assert result["home_stats"]["possession"] == 58.0
    assert result["home_stats"]["shots"] == 15
    assert result["away_stats"] is not None
    assert result["away_stats"]["possession"] == 42.0


def test_fetch_match_data_config_missing_structured_error():
    """When config is missing, returns structured error with ok=False."""
    from src.tools.fetch import fetch_match_data
    from pathlib import Path
    result = fetch_match_data(config=None, config_path=Path("/nonexistent/path.yaml"))
    assert result.get("ok") is False
    assert result["error"]["code"] == "CONFIG_MISSING"
