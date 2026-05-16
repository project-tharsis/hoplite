from datetime import datetime
from src.models.match import Match, MatchEvent, TeamStats


def test_match_result_win():
    m = Match(
        fixture_id=1, date=datetime(2025, 5, 1), competition="PL",
        home_team="Arsenal", away_team="Chelsea",
        home_score=3, away_score=1
    )
    assert m.result == "W"
    assert m.arsenal_is_home is True


def test_match_result_loss_away():
    m = Match(
        fixture_id=2, date=datetime(2025, 5, 1), competition="PL",
        home_team="Liverpool", away_team="Arsenal",
        home_score=2, away_score=0
    )
    assert m.result == "L"
    assert m.arsenal_is_home is False


def test_match_xg_property():
    m = Match(
        fixture_id=3, date=datetime(2025, 5, 1), competition="PL",
        home_team="Arsenal", away_team="Spurs",
        home_score=2, away_score=0, home_xg=2.5, away_xg=0.3
    )
    assert m.arsenal_xg == 2.5


def test_team_stats_dataclass():
    stats = TeamStats(possession=58.5, shots=15, xg=2.1)
    assert stats.possession == 58.5
