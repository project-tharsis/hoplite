from datetime import datetime
from src.models.match import Match
from src.analysis.set_pieces import SetPieceLens

def test_set_piece_analysis_strong():
    match = Match(
        fixture_id=1, date=datetime(2025, 5, 1), competition="PL",
        home_team="Arsenal", away_team="Chelsea",
        home_score=2, away_score=0,
        events=[
            {"minute": 34, "type": "goal", "team": "home", "player": "Gabriel", "detail": "Header from corner"},
            {"minute": 67, "type": "goal", "team": "home", "player": "Saliba", "detail": "Free kick cross"},
            {"minute": 82, "type": "goal", "team": "away", "player": "Jackson", "detail": "Counter attack"},
        ]
    )
    lens = SetPieceLens()
    result = lens.analyze(match)
    assert result.score >= 8.0
    assert "Gabriel" in result.summary
    assert len(result.key_moments) >= 2
    assert len(result.insights) >= 1

def test_set_piece_analysis_no_goals():
    match = Match(
        fixture_id=2, date=datetime(2025, 5, 1), competition="PL",
        home_team="Arsenal", away_team="Liverpool",
        home_score=0, away_score=0,
        events=[]
    )
    lens = SetPieceLens()
    result = lens.analyze(match)
    assert result.score == 5.0
    assert result.key_moments == []

def test_set_piece_conceded():
    match = Match(
        fixture_id=3, date=datetime(2025, 5, 1), competition="PL",
        home_team="Arsenal", away_team="Spurs",
        home_score=1, away_score=2,
        events=[
            {"minute": 15, "type": "goal", "team": "home", "player": "Saka", "detail": "Open play shot"},
            {"minute": 44, "type": "goal", "team": "away", "player": "Son", "detail": "Corner header"},
            {"minute": 88, "type": "goal", "team": "away", "player": "Romero", "detail": "Free kick volley"},
        ]
    )
    lens = SetPieceLens()
    result = lens.analyze(match)
    assert result.score <= 3.0  # conceded 2 SP goals, scored 0 SP
    assert "conceded" in result.summary.lower() or "2" in result.summary
