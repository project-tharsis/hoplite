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
    # v3 schema: mental_model_results instead of results
    assert len(report["mental_model_results"]) == 6
    assert report["overall_signal"] in ("🟢", "🟡", "🔴")
    assert "one_line_summary" in report


def test_build_narrative_prompt():
    from src.tools.prompt import build_narrative_prompt
    report_json = {
        "one_line_summary": "🟢 Arsenal 3-1 Chelsea",
        "predicted_plan": {
            "focus_areas": ["控制中场"],
            "likely_approach": "高位防线",
            "key_battles": ["中场对抗"],
            "expected_subs": "60' 边路换人",
        },
        "mental_model_results": [
            {"model_number": 1, "model_name": "文化标准", "signal": "🟢", "summary": "Discipline held", "evidence": ["0 cards"], "insights": []},
            {"model_number": 2, "model_name": "比赛控制", "signal": "🟢", "summary": "Dominated territory", "evidence": ["62% possession"], "insights": []},
        ],
        "execution": {"signal": "🟢", "verdict": "执行到位", "reasoning": "球队贯彻了赛前部署", "evidence": ["control midfield achieved"]},
        "adjustment": {"signal": "🟡", "verdict": "调整合理", "reasoning": "换人时机恰当", "evidence": []},
        "satisfaction": {"signal": "🟢", "verdict": "取胜满意", "reasoning": "", "evidence": []},
        "overall_signal": "🟢",
    }
    prompt = build_narrative_prompt(report_json, "Arsenal used 3-2-5 build-up.")
    assert "Arsenal 3-1 Chelsea" in prompt
    assert "文化标准" in prompt
    assert "比赛控制" in prompt
    assert "3-2-5" in prompt
    # New prompt is Chinese, so check for Chinese keywords
    assert "中文" in prompt or "Chinese" in prompt.lower()
    assert "inverted-fullback" in prompt.lower()  # Elio style: no spaces in English terms
    assert "为什么" in prompt or "WHY" in prompt


def test_build_card():
    from src.tools.card import build_card
    report_json = {
        "one_line_summary": "🟢 Arsenal 3-1 Chelsea",
        "mental_model_results": [
            {"model_number": 1, "model_name": "文化标准", "signal": "🟢", "summary": "Discipline held", "evidence": [], "insights": []},
            {"model_number": 2, "model_name": "比赛控制", "signal": "🟢", "summary": "Dominated", "evidence": [], "insights": []},
        ],
        "execution": {"signal": "🟢", "verdict": "执行到位", "reasoning": "", "evidence": []},
        "adjustment": {"signal": "🟡", "verdict": "调整合理", "reasoning": "", "evidence": []},
        "satisfaction": {"signal": "🟢", "verdict": "取胜满意", "reasoning": "", "evidence": []},
        "overall_signal": "🟢",
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
