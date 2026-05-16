import pytest
from src.data.api_football import ApiFootballClient
from unittest.mock import patch, Mock


def test_client_headers():
    client = ApiFootballClient(key="test_key")
    assert client.session.headers["x-apisports-key"] == "test_key"


@patch("src.data.api_football.requests.Session.get")
def test_get_match_events(mock_get):
    mock_response = Mock()
    mock_response.json.return_value = {
        "response": [
            {"type": "Goal", "player": {"name": "Saka"}, "team": {"name": "Arsenal"}}
        ]
    }
    mock_response.raise_for_status = Mock()
    mock_get.return_value = mock_response

    client = ApiFootballClient(key="test_key")
    events = client.get_match_events(fixture_id=12345, team_id=42)

    assert len(events) == 1
    assert events[0]["type"] == "Goal"
    assert events[0]["player"]["name"] == "Saka"


@patch("src.data.api_football.requests.Session.get")
def test_get_match_lineups(mock_get):
    mock_response = Mock()
    mock_response.json.return_value = {
        "response": [{"formation": "4-3-3", "startXI": []}]
    }
    mock_response.raise_for_status = Mock()
    mock_get.return_value = mock_response

    client = ApiFootballClient(key="test_key")
    lineups = client.get_match_lineups(fixture_id=12345)

    assert len(lineups) == 1
    assert lineups[0]["formation"] == "4-3-3"


@patch("src.data.api_football.requests.Session.get")
def test_get_team_fixtures(mock_get):
    mock_response = Mock()
    mock_response.json.return_value = {"response": [{"fixture": {"id": 100}}]}
    mock_response.raise_for_status = Mock()
    mock_get.return_value = mock_response

    client = ApiFootballClient(key="test_key")
    fixtures = client.get_team_fixtures(team_id=42, season=2025, limit=5)

    assert len(fixtures) == 1
    assert fixtures[0]["fixture"]["id"] == 100
    _, kwargs = mock_get.call_args
    assert kwargs["params"]["last"] == 5


@patch("src.data.api_football.requests.Session.get")
def test_get_team_fixtures_with_dates(mock_get):
    mock_response = Mock()
    mock_response.json.return_value = {"response": [{"fixture": {"id": 200}}]}
    mock_response.raise_for_status = Mock()
    mock_get.return_value = mock_response

    client = ApiFootballClient(key="test_key")
    fixtures = client.get_team_fixtures(team_id=42, season=2024, from_date="2024-01-01", to_date="2024-01-31")

    assert len(fixtures) == 1
    assert fixtures[0]["fixture"]["id"] == 200
    _, kwargs = mock_get.call_args
    assert kwargs["params"]["from"] == "2024-01-01"
    assert kwargs["params"]["to"] == "2024-01-31"
    assert "last" not in kwargs["params"]
