import pytest

from src.evaluation.predictor import ArtetaPredictor, PredictedPlan


@pytest.fixture
def predictor():
    return ArtetaPredictor()


def test_predict_returns_populated_plan(predictor):
    ctx = {
        "opponent_quality": "top6",
        "venue": "home",
        "competition_stage": "league_early",
        "injury_situation": "full_strength",
        "recent_form": "W3",
        "opponent_style": "possession",
    }
    plan = predictor.predict(ctx)
    assert isinstance(plan, PredictedPlan)
    assert len(plan.focus_areas) >= 1
    assert plan.likely_approach != ""
    assert len(plan.key_battles) >= 1
    assert plan.expected_subs != ""


def test_home_vs_away_produces_different_focus_areas(predictor):
    home_ctx = {
        "opponent_quality": "lower",
        "venue": "home",
        "competition_stage": "league_early",
        "injury_situation": "full_strength",
        "recent_form": "W3",
        "opponent_style": "low_block",
    }
    away_ctx = {
        "opponent_quality": "top6",
        "venue": "away",
        "competition_stage": "league_early",
        "injury_situation": "full_strength",
        "recent_form": "mixed",
        "opponent_style": "pressing",
    }
    home_plan = predictor.predict(home_ctx)
    away_plan = predictor.predict(away_ctx)
    assert home_plan.focus_areas != away_plan.focus_areas


def test_different_contexts_produce_different_predictions(predictor):
    ctx_a = {
        "opponent_quality": "lower",
        "venue": "home",
        "competition_stage": "group_stage",
        "injury_situation": "full_strength",
        "recent_form": "W3",
        "opponent_style": "low_block",
    }
    ctx_b = {
        "opponent_quality": "european_elite",
        "venue": "away",
        "competition_stage": "knockout",
        "injury_situation": "crisis",
        "recent_form": "poor",
        "opponent_style": "physical",
    }
    plan_a = predictor.predict(ctx_a)
    plan_b = predictor.predict(ctx_b)

    assert plan_a.focus_areas != plan_b.focus_areas
    assert plan_a.likely_approach != plan_b.likely_approach
    assert plan_a.key_battles != plan_b.key_battles
    assert plan_a.expected_subs != plan_b.expected_subs


def test_injury_crisis_produces_conservative_plan(predictor):
    ctx = {
        "opponent_quality": "mid_table",
        "venue": "home",
        "competition_stage": "league_early",
        "injury_situation": "crisis",
        "recent_form": "mixed",
        "opponent_style": "possession",
    }
    plan = predictor.predict(ctx)
    assert any("保护" in area for area in plan.focus_areas)
    assert any("简化" in area for area in plan.focus_areas)


def test_knockout_emphasizes_structure_and_set_pieces(predictor):
    ctx = {
        "opponent_quality": "top6",
        "venue": "neutral",
        "competition_stage": "final",
        "injury_situation": "full_strength",
        "recent_form": "W3",
        "opponent_style": "possession",
    }
    plan = predictor.predict(ctx)
    assert "定位球重点部署" in plan.likely_approach or "定位球" in str(plan.focus_areas)


def test_poor_form_prompts_early_change(predictor):
    ctx = {
        "opponent_quality": "mid_table",
        "venue": "home",
        "competition_stage": "league_early",
        "injury_situation": "full_strength",
        "recent_form": "poor",
        "opponent_style": "counter",
    }
    plan = predictor.predict(ctx)
    assert "50'" in plan.expected_subs
