import pytest
from src.data.football_data import FootballDataClient
from unittest.mock import patch, Mock

def test_client_initialization():
    client = FootballDataClient(token="test_token")
    assert client.session.headers["X-Auth-Token"] == "test_token"

@patch("src.data.football_data.requests.Session.get")
def test_get_team_matches(mock_get):
    mock_response = Mock()
    mock_response.json.return_value = {"matches": [{"id": 1, "homeTeam": {"name": "Arsenal"}}]}
    mock_response.raise_for_status = Mock()
    mock_get.return_value = mock_response
    
    client = FootballDataClient(token="test_token")
    matches = client.get_team_matches(team_id=57, status="FINISHED", limit=5)
    
    assert len(matches) == 1
    mock_get.assert_called_once()

@patch("src.data.football_data.requests.Session.get")
def test_get_standings(mock_get):
    mock_response = Mock()
    mock_response.json.return_value = {"standings": [{"table": []}]}
    mock_response.raise_for_status = Mock()
    mock_get.return_value = mock_response
    
    client = FootballDataClient(token="test_token")
    standings = client.get_standings()
    
    assert len(standings) == 1
    assert "table" in standings[0]
