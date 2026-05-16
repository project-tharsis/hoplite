"""Test API-Football statistics parser."""
from src.data.stats_parser import parse_api_football_stats


SAMPLE_STATS_RESPONSE = [
    {
        "team": {"id": 42, "name": "Arsenal"},
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
        "team": {"id": 61, "name": "Chelsea"},
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


def test_parse_stats_arsenal_home():
    home, away = parse_api_football_stats(SAMPLE_STATS_RESPONSE, 42, arsenal_is_home=True)
    assert home is not None
    assert away is not None
    assert home.possession == 58.0
    assert home.shots == 15
    assert home.shots_on_target == 6
    assert home.passes == 512
    assert home.pass_accuracy == 87.0
    assert home.corners == 7
    assert home.yellow_cards == 1
    assert away.possession == 42.0
    assert away.shots == 8
    assert away.corners == 4


def test_parse_stats_arsenal_away():
    home, away = parse_api_football_stats(SAMPLE_STATS_RESPONSE, 42, arsenal_is_home=False)
    assert home is not None
    assert away is not None
    assert home.possession == 42.0
    assert away.possession == 58.0
    assert home.shots == 8
    assert away.shots == 15


def test_parse_stats_empty():
    home, away = parse_api_football_stats([], 42, True)
    assert home is None
    assert away is None
