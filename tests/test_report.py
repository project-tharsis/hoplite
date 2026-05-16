from datetime import datetime
from src.models.match import Match
from src.report import ReportOrchestrator, MatchReport
from src.analysis.base import AnalysisResult


def test_match_report_overall_score():
    report = MatchReport(
        match=Match(
            fixture_id=1, date=datetime(2025, 5, 1), competition="PL",
            home_team="Arsenal", away_team="Chelsea",
            home_score=3, away_score=1,
        ),
        results=[
            AnalysisResult(lens_name="Set Pieces", summary="ok", score=7.0, key_moments=[], insights=[]),
            AnalysisResult(lens_name="Goals", summary="ok", score=8.0, key_moments=[], insights=[]),
        ]
    )
    assert report.overall_score == 7.5
    assert "3-1" in report.one_line_summary


def test_match_report_empty():
    report = MatchReport(
        match=Match(
            fixture_id=2, date=datetime(2025, 5, 1), competition="PL",
            home_team="Arsenal", away_team="Spurs",
            home_score=0, away_score=0,
        )
    )
    assert report.overall_score == 5.0
    assert report.results == []


def test_orchestrator_generates_report():
    match = Match(
        fixture_id=1, date=datetime(2025, 5, 1), competition="PL",
        home_team="Arsenal", away_team="Chelsea",
        home_score=3, away_score=1,
        events=[
            {"minute": 23, "type": "goal", "team": "home", "player": "Saka", "detail": "Right foot shot"},
            {"minute": 55, "type": "goal", "team": "home", "player": "Jesus", "detail": "Tap in"},
            {"minute": 78, "type": "goal", "team": "away", "player": "Sterling", "detail": "Counter"},
            {"minute": 89, "type": "goal", "team": "home", "player": "Odegaard", "detail": "Penalty"},
        ]
    )
    
    orchestrator = ReportOrchestrator()
    report = orchestrator.generate(match)
    
    assert len(report.results) == len(ReportOrchestrator.LENSES)
    assert report.overall_score > 0
    assert "3-1" in report.one_line_summary
    # Verify each result has valid data
    for r in report.results:
        assert 1.0 <= r.score <= 10.0
        assert r.lens_name != ""
