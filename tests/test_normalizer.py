from datetime import datetime
from src.normalizer import normalize_football_data_match, merge_match_data
from src.models.match import Match

SAMPLE_FD_MATCH = {
    "id": 500001,
    "utcDate": "2025-05-10T15:00:00Z",
    "competition": {"name": "Premier League"},
    "homeTeam": {"name": "Arsenal", "shortName": "Arsenal"},
    "awayTeam": {"name": "Chelsea", "shortName": "Chelsea"},
    "score": {
        "fullTime": {"home": 3, "away": 1}
    }
}

SAMPLE_UNDERSTAT_MATCH = {
    "home_team": "Arsenal",
    "away_team": "Chelsea",
    "home_xg": 2.5,
    "away_xg": 0.6,
    "home_goals": 3,
    "away_goals": 1
}


def test_normalize_football_data():
    match = normalize_football_data_match(SAMPLE_FD_MATCH)
    assert match.fixture_id == 500001
    assert match.home_team == "Arsenal"
    assert match.away_team == "Chelsea"
    assert match.home_score == 3
    assert match.away_score == 1
    assert match.competition == "Premier League"
    assert match.result == "W"


def test_merge_understat_xg():
    match = normalize_football_data_match(SAMPLE_FD_MATCH)
    merge_match_data(match, understat_data=SAMPLE_UNDERSTAT_MATCH)
    assert match.home_xg == 2.5
    assert match.away_xg == 0.6


def test_normalize_null_scores():
    """Handle null scores (match not yet played)."""
    raw = dict(SAMPLE_FD_MATCH)
    raw["score"]["fullTime"] = {"home": None, "away": None}
    match = normalize_football_data_match(raw)
    assert match.home_score == 0
    assert match.away_score == 0


def test_merge_without_understat():
    """merge_match_data should be a no-op when understat_data is None."""
    match = normalize_football_data_match(SAMPLE_FD_MATCH)
    merge_match_data(match, understat_data=None)
    assert match.home_xg is None
    assert match.away_xg is None
