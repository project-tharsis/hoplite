from datetime import datetime
from src.models.match import Match
from src.report import ReportOrchestrator, MatchReport
from src.analysis.base import AnalysisResult
from src.output.feishu_card import FeishuCardBuilder


def test_card_structure():
    match = Match(
        fixture_id=1, date=datetime(2025, 5, 1), competition="PL",
        home_team="Arsenal", away_team="Chelsea",
        home_score=3, away_score=1,
    )
    report = MatchReport(
        match=match,
        results=[
            AnalysisResult(lens_name="Set Pieces", summary="2 SP goals scored", score=8.5, key_moments=["Gabriel header at 34'"], insights=["Strong"]),
            AnalysisResult(lens_name="Goal Events", summary="3-1 result", score=7.0, key_moments=["Saka at 23'"], insights=["Good tempo"]),
        ]
    )
    
    builder = FeishuCardBuilder(chat_id="oc_test")
    card = builder.build_match_card(report)
    
    assert card["schema"] == "2.0"
    assert "header" in card
    assert "body" in card
    assert "elements" in card["body"]
    assert "3-1" in card["header"]["title"]["content"]
    assert "🟢" in card["header"]["title"]["content"]
    # Check table presence
    elements = card["body"]["elements"]
    tables = [e for e in elements if e.get("tag") == "table"]
    assert len(tables) == 1


def test_card_loss_emoji():
    match = Match(
        fixture_id=2, date=datetime(2025, 5, 1), competition="PL",
        home_team="Arsenal", away_team="Liverpool",
        home_score=0, away_score=2,
    )
    report = MatchReport(match=match)
    builder = FeishuCardBuilder(chat_id="oc_test")
    card = builder.build_match_card(report)
    assert "🔴" in card["header"]["title"]["content"]


def test_card_draw_emoji():
    match = Match(
        fixture_id=3, date=datetime(2025, 5, 1), competition="PL",
        home_team="Chelsea", away_team="Arsenal",
        home_score=1, away_score=1,
    )
    report = MatchReport(match=match)
    builder = FeishuCardBuilder(chat_id="oc_test")
    card = builder.build_match_card(report)
    assert "🟡" in card["header"]["title"]["content"]
