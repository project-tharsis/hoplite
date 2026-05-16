from datetime import datetime
from src.models.match import Match, MatchEvent, TeamStats
from src.evaluation.mental_models import (
    CultureEvaluator,
    GameControlEvaluator,
    DefenceAsAttackEvaluator,
    MarginalGainsEvaluator,
    AddCapabilityEvaluator,
    RoleClarityEvaluator,
    MentalModelResult,
)


VALID_SIGNALS = {"🟢", "🟡", "🔴"}


def _make_match(**kwargs) -> Match:
    defaults = dict(
        fixture_id=1,
        date=datetime(2025, 5, 1),
        competition="PL",
        home_team="Arsenal",
        away_team="Chelsea",
        home_score=2,
        away_score=1,
        home_xg=2.1,
        away_xg=0.8,
        home_stats=TeamStats(
            possession=58.0,
            shots=15,
            shots_on_target=6,
            xg=2.1,
            passes=420,
            pass_accuracy=84.0,
            fouls=9,
            corners=7,
            yellow_cards=1,
            red_cards=0,
        ),
        away_stats=TeamStats(
            possession=42.0,
            shots=8,
            shots_on_target=2,
            xg=0.8,
            passes=310,
            pass_accuracy=76.0,
            fouls=12,
            corners=3,
            yellow_cards=3,
            red_cards=0,
        ),
        home_formation="4-3-3",
        away_formation="4-4-2",
        events=[
            MatchEvent(minute=12, type="goal", team="home", player="Saka", detail="Right-footed shot from inside box"),
            MatchEvent(minute=45, type="card", team="home", player="Partey", detail="Yellow card for late tackle"),
            MatchEvent(minute=55, type="goal", team="away", player="Palmer", detail="Penalty"),
            MatchEvent(minute=70, type="substitution", team="home", player="Trossard", detail="Replaced Martinelli"),
            MatchEvent(minute=78, type="goal", team="home", player="Trossard", detail="Counter-attack finish"),
        ],
        home_lineup=["Raya", "White", "Saliba", "Gabriel", "Zinchenko", "Partey", "Odegaard", "Rice", "Saka", "Havertz", "Martinelli"],
        away_lineup=["Sanchez", "James", "Colwill", "Badiashile", "Cucurella", "Caicedo", "Fernandez", "Palmer", "Madueke", "Jackson", "Nkunku"],
    )
    defaults.update(kwargs)
    return Match(**defaults)


def test_culture_evaluator():
    match = _make_match()
    eval = CultureEvaluator()
    result = eval.evaluate(match)
    assert isinstance(result, MentalModelResult)
    assert result.model_number == 1
    assert result.signal in VALID_SIGNALS
    assert len(result.evidence) > 0


def test_game_control_evaluator():
    match = _make_match()
    eval = GameControlEvaluator()
    result = eval.evaluate(match)
    assert isinstance(result, MentalModelResult)
    assert result.model_number == 2
    assert result.signal in VALID_SIGNALS
    assert len(result.evidence) > 0


def test_defence_as_attack_evaluator():
    match = _make_match()
    eval = DefenceAsAttackEvaluator()
    result = eval.evaluate(match)
    assert isinstance(result, MentalModelResult)
    assert result.model_number == 3
    assert result.signal in VALID_SIGNALS
    assert len(result.evidence) > 0


def test_marginal_gains_evaluator():
    match = _make_match()
    eval = MarginalGainsEvaluator()
    result = eval.evaluate(match)
    assert isinstance(result, MentalModelResult)
    assert result.model_number == 4
    assert result.signal in VALID_SIGNALS
    assert len(result.evidence) > 0


def test_add_capability_evaluator():
    match = _make_match()
    eval = AddCapabilityEvaluator()
    result = eval.evaluate(match)
    assert isinstance(result, MentalModelResult)
    assert result.model_number == 5
    assert result.signal in VALID_SIGNALS
    assert len(result.evidence) > 0


def test_role_clarity_evaluator():
    match = _make_match()
    eval = RoleClarityEvaluator()
    result = eval.evaluate(match)
    assert isinstance(result, MentalModelResult)
    assert result.model_number == 6
    assert result.signal in VALID_SIGNALS
    assert len(result.evidence) > 0


def test_all_evaluators_with_minimal_match():
    minimal = Match(
        fixture_id=99,
        date=datetime(2025, 5, 1),
        competition="PL",
        home_team="Arsenal",
        away_team="Spurs",
        home_score=1,
        away_score=1,
    )
    evaluators = [
        CultureEvaluator(),
        GameControlEvaluator(),
        DefenceAsAttackEvaluator(),
        MarginalGainsEvaluator(),
        AddCapabilityEvaluator(),
        RoleClarityEvaluator(),
    ]
    for ev in evaluators:
        result = ev.evaluate(minimal)
        assert isinstance(result, MentalModelResult)
        assert result.signal in VALID_SIGNALS
        assert len(result.evidence) >= 0


def test_signals_with_scenarios():
    # Heavy defeat with discipline collapse → red for culture
    bad_match = _make_match(
        home_score=0,
        away_score=3,
        events=[
            MatchEvent(minute=10, type="card", team="home", player="Partey", detail="Yellow card"),
            MatchEvent(minute=22, type="card", team="home", player="White", detail="Yellow card"),
            MatchEvent(minute=40, type="card", team="home", player="Saliba", detail="Red card"),
        ],
    )
    result = CultureEvaluator().evaluate(bad_match)
    assert result.signal == "🔴"

    # Dominant win with clean sheet → green for game control and defence
    dominant = _make_match(
        home_score=3,
        away_score=0,
        home_stats=TeamStats(possession=65, shots=20, shots_on_target=9, passes=500, pass_accuracy=88, corners=9, fouls=5, yellow_cards=0),
        away_stats=TeamStats(possession=35, shots=3, shots_on_target=0, passes=220, pass_accuracy=70, corners=1, fouls=14, yellow_cards=2),
        events=[
            MatchEvent(minute=15, type="goal", team="home", player="Saka", detail="Header from corner"),
            MatchEvent(minute=30, type="goal", team="home", player="Odegaard", detail="Direct free kick"),
            MatchEvent(minute=60, type="goal", team="home", player="Havertz", detail="Build-up play"),
        ],
    )
    gc = GameControlEvaluator().evaluate(dominant)
    assert gc.signal == "🟢"
    da = DefenceAsAttackEvaluator().evaluate(dominant)
    assert da.signal == "🟢"
    mg = MarginalGainsEvaluator().evaluate(dominant)
    assert mg.signal == "🟢"
