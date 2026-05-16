from datetime import datetime
import pytest

from src.models.match import Match, MatchEvent, TeamStats
from src.evaluation.dimensions import (
    DimensionResult,
    PreMatchExecutionDimension,
    InMatchAdjustmentDimension,
    ResultSatisfactionDimension,
)


def make_match(
    *,
    home_team="Arsenal",
    away_team="Chelsea",
    home_score=2,
    away_score=1,
    home_stats=None,
    away_stats=None,
    events=None,
    home_formation=None,
    away_formation=None,
    home_xg=None,
    away_xg=None,
):
    return Match(
        fixture_id=1,
        date=datetime(2025, 5, 1),
        competition="PL",
        home_team=home_team,
        away_team=away_team,
        home_score=home_score,
        away_score=away_score,
        home_stats=home_stats,
        away_stats=away_stats,
        events=events or [],
        home_formation=home_formation,
        away_formation=away_formation,
        home_xg=home_xg,
        away_xg=away_xg,
    )


class TestPreMatchExecutionDimension:
    def test_returns_dimension_result(self):
        dim = PreMatchExecutionDimension()
        match = make_match(
            home_stats=TeamStats(possession=62, shots=16, xg=2.0),
            away_stats=TeamStats(possession=38, shots=8),
        )
        plan = {"focus_areas": ["control midfield"], "likely_approach": "", "key_battles": []}
        result = dim.assess(match, plan)
        assert isinstance(result, DimensionResult)
        assert result.name == "赛前决策执行度"

    def test_signal_is_valid_emoji(self):
        dim = PreMatchExecutionDimension()
        match = make_match(
            home_stats=TeamStats(possession=65, shots=18, xg=2.5),
            away_stats=TeamStats(possession=35, shots=5),
        )
        plan = {
            "focus_areas": ["control midfield", "dominate attack"],
            "likely_approach": "",
            "key_battles": ["midfield duel"],
        }
        result = dim.assess(match, plan)
        assert result.signal in ("🟢", "🟡", "🔴")

    def test_green_for_strong_execution(self):
        dim = PreMatchExecutionDimension()
        match = make_match(
            home_stats=TeamStats(possession=65, shots=18, xg=2.5),
            away_stats=TeamStats(possession=35, shots=5, pass_accuracy=70),
        )
        plan = {
            "focus_areas": ["control midfield", "dominate attack", "high press"],
            "likely_approach": "",
            "key_battles": ["midfield duel"],
        }
        result = dim.assess(match, plan)
        assert result.signal == "🟢"
        assert len(result.evidence) > 0

    def test_red_for_poor_execution(self):
        dim = PreMatchExecutionDimension()
        match = make_match(
            home_stats=TeamStats(possession=40, shots=3, xg=0.2),
            away_stats=TeamStats(possession=60, shots=16, pass_accuracy=90),
        )
        plan = {
            "focus_areas": ["control midfield", "dominate attack", "high press"],
            "likely_approach": "",
            "key_battles": [],
        }
        result = dim.assess(match, plan)
        assert result.signal == "🔴"

    def test_early_pressure_green(self):
        dim = PreMatchExecutionDimension()
        match = make_match(
            events=[
                MatchEvent(minute=10, type="goal", team="home", player="Saka", detail="Saka"),
            ],
            home_stats=TeamStats(possession=55),
        )
        plan = {"focus_areas": [], "likely_approach": "early pressure", "key_battles": []}
        result = dim.assess(match, plan)
        assert result.signal == "🟢"


class TestInMatchAdjustmentDimension:
    def test_returns_dimension_result(self):
        dim = InMatchAdjustmentDimension()
        match = make_match()
        plan = {}
        result = dim.assess(match, plan)
        assert isinstance(result, DimensionResult)
        assert result.name == "赛中调整合理性"
        assert result.signal in ("🟢", "🟡", "🔴")

    def test_green_for_impactful_subs(self):
        dim = InMatchAdjustmentDimension()
        match = make_match(
            events=[
                MatchEvent(minute=60, type="substitution", team="home", player="Trossard", detail="on"),
                MatchEvent(minute=75, type="goal", team="home", player="Trossard", detail="Trossard"),
            ],
            home_score=2,
            away_score=1,
        )
        result = dim.assess(match, {})
        assert result.signal == "🟢"

    def test_red_for_late_subs_when_losing(self):
        dim = InMatchAdjustmentDimension()
        match = make_match(
            home_score=0,
            away_score=2,
            events=[
                MatchEvent(minute=85, type="substitution", team="home", player="Nketiah", detail="on"),
            ],
        )
        result = dim.assess(match, {})
        assert result.signal == "🔴"

    def test_yellow_when_winning_no_major_adjustments(self):
        dim = InMatchAdjustmentDimension()
        match = make_match(home_score=3, away_score=0, events=[])
        result = dim.assess(match, {})
        assert result.signal == "🟡"


class TestResultSatisfactionDimension:
    def test_returns_dimension_result(self):
        dim = ResultSatisfactionDimension()
        match = make_match()
        ctx = {"opponent_quality": "medium", "injury_situation": "normal", "competition_stage": "league"}
        result = dim.assess(match, ctx)
        assert isinstance(result, DimensionResult)
        assert result.name == "比赛结果满意度"
        assert result.signal in ("🟢", "🟡", "🔴")

    def test_green_win_vs_strong_opponent(self):
        dim = ResultSatisfactionDimension()
        match = make_match(home_score=2, away_score=1)
        ctx = {"opponent_quality": "top", "injury_situation": "normal", "competition_stage": "league"}
        result = dim.assess(match, ctx)
        assert result.signal == "🟢"

    def test_yellow_win_vs_weak_opponent(self):
        dim = ResultSatisfactionDimension()
        match = make_match(home_score=2, away_score=0)
        ctx = {"opponent_quality": "weak", "injury_situation": "normal", "competition_stage": "league"}
        result = dim.assess(match, ctx)
        assert result.signal == "🟡"

    def test_red_draw_vs_weak_opponent(self):
        dim = ResultSatisfactionDimension()
        match = make_match(home_score=1, away_score=1)
        ctx = {"opponent_quality": "weak", "injury_situation": "normal", "competition_stage": "league"}
        result = dim.assess(match, ctx)
        assert result.signal == "🔴"

    def test_green_draw_away_vs_strong(self):
        dim = ResultSatisfactionDimension()
        match = make_match(
            home_team="Liverpool",
            away_team="Arsenal",
            home_score=1,
            away_score=1,
        )
        ctx = {"opponent_quality": "top", "injury_situation": "normal", "competition_stage": "league"}
        result = dim.assess(match, ctx)
        assert result.signal == "🟢"

    def test_yellow_loss_vs_strong_opponent(self):
        dim = ResultSatisfactionDimension()
        match = make_match(
            home_team="Liverpool",
            away_team="Arsenal",
            home_score=2,
            away_score=1,
        )
        ctx = {"opponent_quality": "top", "injury_situation": "normal", "competition_stage": "league"}
        result = dim.assess(match, ctx)
        assert result.signal == "🟡"

    def test_red_loss_vs_weak_opponent(self):
        dim = ResultSatisfactionDimension()
        match = make_match(
            home_team="Arsenal",
            away_team="Burnley",
            home_score=0,
            away_score=1,
        )
        ctx = {"opponent_quality": "weak", "injury_situation": "normal", "competition_stage": "league"}
        result = dim.assess(match, ctx)
        assert result.signal == "🔴"

    def test_red_heavy_loss(self):
        dim = ResultSatisfactionDimension()
        match = make_match(
            home_team="Arsenal",
            away_team="Chelsea",
            home_score=0,
            away_score=4,
        )
        ctx = {"opponent_quality": "medium", "injury_situation": "normal", "competition_stage": "league"}
        result = dim.assess(match, ctx)
        assert result.signal == "🔴"

    def test_green_win_with_injury_crisis(self):
        dim = ResultSatisfactionDimension()
        match = make_match(home_score=1, away_score=0)
        ctx = {"opponent_quality": "medium", "injury_situation": "severe", "competition_stage": "league"}
        result = dim.assess(match, ctx)
        assert result.signal == "🟢"

    def test_red_knockout_loss(self):
        dim = ResultSatisfactionDimension()
        match = make_match(
            home_team="Arsenal",
            away_team="Bayern",
            home_score=0,
            away_score=1,
        )
        ctx = {"opponent_quality": "top", "injury_situation": "normal", "competition_stage": "knockout"}
        result = dim.assess(match, ctx)
        assert result.signal == "🔴"
