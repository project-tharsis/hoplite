from datetime import datetime
from src.models.match import Match
from src.analysis.goals import GoalEventsLens


def test_goal_events_win_with_late_goal():
    match = Match(
        fixture_id=1, date=datetime(2025, 5, 1), competition="PL",
        home_team="Arsenal", away_team="Chelsea",
        home_score=2, away_score=1,
        events=[
            {"minute": 23, "type": "goal", "team": "home", "player": "Saka", "detail": "Shot"},
            {"minute": 55, "type": "goal", "team": "away", "player": "Sterling", "detail": "Counter"},
            {"minute": 89, "type": "goal", "team": "home", "player": "Odegaard", "detail": "Penalty"},
        ]
    )
    lens = GoalEventsLens()
    result = lens.analyze(match)
    # Early goal + late winner in a win = bonus points
    assert result.score > 5.0
    assert len(result.key_moments) == 3
    assert any("early" in insight.lower() or "started" in insight.lower() for insight in result.insights)


def test_goal_events_draw():
    match = Match(
        fixture_id=2, date=datetime(2025, 5, 1), competition="PL",
        home_team="Chelsea", away_team="Arsenal",
        home_score=1, away_score=1,
        events=[
            {"minute": 45, "type": "goal", "team": "away", "player": "Jesus", "detail": "Tap in"},
            {"minute": 72, "type": "goal", "team": "home", "player": "Palmer", "detail": "Long shot"},
        ]
    )
    lens = GoalEventsLens()
    result = lens.analyze(match)
    assert "1-1" in result.summary
    assert "Jesus" in result.summary
    assert "Palmer" in result.summary
