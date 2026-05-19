"""Tests for the rule-based weak labeler.

Covers all 6 models, 3 dimensions, overall signal, Bournemouth 3-2 case,
reproducibility, missing data penalty, and edge cases.
"""
import pytest

from src.features.extractor import MatchFeatures
from src.labels.weak_labeler import (
    WeakLabeler, WeakLabels,
    GREEN, YELLOW, RED,
    MODEL_1, MODEL_2, MODEL_3, MODEL_4, MODEL_5, MODEL_6,
)


@pytest.fixture
def labeler():
    return WeakLabeler()


def _base_features(**kwargs) -> MatchFeatures:
    """Create MatchFeatures with sensible defaults, overridden by kwargs."""
    defaults = dict(
        result="W",
        score_margin=1,
        arsenal_goals=2,
        opponent_goals=1,
        goals_conceded=1,
        yellow_cards_for=1,
        red_cards_for=0,
        fouls_for=10,
        fouls_against=10,
        possession_for=55.0,
        possession_against=45.0,
        possession_delta=10.0,
        shots_for=12,
        shots_against=8,
        shot_delta=4,
        shots_on_target_for=5,
        shots_on_target_against=3,
        shot_on_target_delta=2,
        xg_for=1.5,
        xg_against=0.8,
        xg_delta=0.7,
        pass_accuracy_for=85.0,
        pass_accuracy_against=80.0,
        pass_accuracy_delta=5.0,
        corners_for=6,
        corners_against=3,
        corner_delta=3,
        opponent_shots_on_target=3,
        set_piece_goals_for=1,
        set_piece_goals_against=0,
        substitution_windows=[{"minute": 60, "player": "Saka", "scored_after": True}],
        arsenal_sub_count=1,
        goals_after_arsenal_subs=1,
        score_state_timeline=[
            {"minute": 0, "arsenal_score": 0, "opponent_score": 0},
            {"minute": 30, "arsenal_score": 1, "opponent_score": 0},
            {"minute": 60, "arsenal_score": 1, "opponent_score": 1},
            {"minute": 80, "arsenal_score": 2, "opponent_score": 1},
        ],
        missing_data=[],
    )
    defaults.update(kwargs)
    return MatchFeatures(**defaults)


# ═══════════════════════════════════════════════════════════════════════
# Model 1 — Culture as OS
# ═══════════════════════════════════════════════════════════════════════

class TestModel1Culture:
    def test_green_no_cards(self, labeler):
        f = _base_features(yellow_cards_for=0, red_cards_for=0, fouls_for=8, fouls_against=10)
        wl = labeler.label(f)
        assert wl.model_signals[MODEL_1] == GREEN

    def test_green_one_yellow(self, labeler):
        f = _base_features(yellow_cards_for=1, red_cards_for=0, fouls_for=10, fouls_against=10)
        wl = labeler.label(f)
        assert wl.model_signals[MODEL_1] == GREEN

    def test_yellow_two_yellows(self, labeler):
        f = _base_features(yellow_cards_for=2, red_cards_for=0)
        wl = labeler.label(f)
        assert wl.model_signals[MODEL_1] == YELLOW

    def test_yellow_fouls_slightly_above(self, labeler):
        f = _base_features(yellow_cards_for=0, red_cards_for=0, fouls_for=14, fouls_against=10)
        wl = labeler.label(f)
        assert wl.model_signals[MODEL_1] == YELLOW

    def test_red_card(self, labeler):
        f = _base_features(red_cards_for=1)
        wl = labeler.label(f)
        assert wl.model_signals[MODEL_1] == RED

    def test_red_four_yellows(self, labeler):
        f = _base_features(yellow_cards_for=4, red_cards_for=0)
        wl = labeler.label(f)
        assert wl.model_signals[MODEL_1] == RED

    def test_red_fouls_far_above(self, labeler):
        f = _base_features(yellow_cards_for=0, red_cards_for=0, fouls_for=20, fouls_against=10)
        wl = labeler.label(f)
        assert wl.model_signals[MODEL_1] == RED


# ═══════════════════════════════════════════════════════════════════════
# Model 2 — Where the Game Is Played
# ═══════════════════════════════════════════════════════════════════════

class TestModel2Territory:
    def test_green_positive_shots_and_xg(self, labeler):
        f = _base_features(shot_delta=5, xg_delta=1.2, possession_delta=10)
        wl = labeler.label(f)
        assert wl.model_signals[MODEL_2] == GREEN

    def test_green_xg_missing_shots_and_poss_positive(self, labeler):
        f = _base_features(shot_delta=3, xg_for=None, xg_against=None, xg_delta=None,
                           possession_delta=8)
        wl = labeler.label(f)
        assert wl.model_signals[MODEL_2] == GREEN
        assert wl.confidence[MODEL_2] == "medium"

    def test_not_green_possession_alone(self, labeler):
        """CRITICAL: possession alone must NOT produce green."""
        f = _base_features(shot_delta=-3, xg_delta=-0.5, possession_delta=15,
                           corner_delta=2)
        wl = labeler.label(f)
        assert wl.model_signals[MODEL_2] != GREEN

    def test_yellow_mixed_signals(self, labeler):
        f = _base_features(shot_delta=-2, possession_delta=10, xg_delta=0.3,
                           corner_delta=1)
        wl = labeler.label(f)
        assert wl.model_signals[MODEL_2] == YELLOW

    def test_yellow_possession_negative_shots_positive(self, labeler):
        f = _base_features(shot_delta=2, possession_delta=-5, xg_delta=-0.3,
                           corner_delta=0)
        wl = labeler.label(f)
        assert wl.model_signals[MODEL_2] == YELLOW

    def test_red_all_negative(self, labeler):
        f = _base_features(shot_delta=-5, xg_delta=-1.0, corner_delta=-3,
                           possession_delta=-10)
        wl = labeler.label(f)
        assert wl.model_signals[MODEL_2] == RED


# ═══════════════════════════════════════════════════════════════════════
# Model 3 — Defence as Attacking Identity
# ═══════════════════════════════════════════════════════════════════════

class TestModel3Defence:
    def test_green_clean_sheet(self, labeler):
        f = _base_features(goals_conceded=0, opponent_shots_on_target=2)
        wl = labeler.label(f)
        assert wl.model_signals[MODEL_3] == GREEN

    def test_green_one_conceded_low_shots(self, labeler):
        f = _base_features(goals_conceded=1, opponent_shots_on_target=3)
        wl = labeler.label(f)
        assert wl.model_signals[MODEL_3] == GREEN

    def test_yellow_one_conceded(self, labeler):
        f = _base_features(goals_conceded=1, opponent_shots_on_target=5)
        wl = labeler.label(f)
        assert wl.model_signals[MODEL_3] == YELLOW

    def test_yellow_two_conceded(self, labeler):
        f = _base_features(goals_conceded=2, opponent_shots_on_target=4)
        wl = labeler.label(f)
        assert wl.model_signals[MODEL_3] == YELLOW

    def test_red_three_conceded(self, labeler):
        f = _base_features(goals_conceded=3)
        wl = labeler.label(f)
        assert wl.model_signals[MODEL_3] == RED

    def test_red_high_xg_against(self, labeler):
        f = _base_features(goals_conceded=2, xg_against=2.5)
        wl = labeler.label(f)
        assert wl.model_signals[MODEL_3] == RED


# ═══════════════════════════════════════════════════════════════════════
# Model 4 — Marginal Gains
# ═══════════════════════════════════════════════════════════════════════

class TestModel4Marginal:
    def test_green_set_piece_advantage(self, labeler):
        f = _base_features(set_piece_goals_for=2, set_piece_goals_against=0)
        wl = labeler.label(f)
        assert wl.model_signals[MODEL_4] == GREEN

    def test_green_corner_advantage(self, labeler):
        f = _base_features(set_piece_goals_for=0, set_piece_goals_against=0,
                           corners_for=8, corners_against=3)
        wl = labeler.label(f)
        assert wl.model_signals[MODEL_4] == GREEN

    def test_yellow_neutral(self, labeler):
        f = _base_features(set_piece_goals_for=1, set_piece_goals_against=1,
                           corners_for=5, corners_against=4)
        wl = labeler.label(f)
        assert wl.model_signals[MODEL_4] == YELLOW

    def test_red_set_piece_behind(self, labeler):
        f = _base_features(set_piece_goals_for=0, set_piece_goals_against=2)
        wl = labeler.label(f)
        assert wl.model_signals[MODEL_4] == RED


# ═══════════════════════════════════════════════════════════════════════
# Model 5 — Add Capability, Keep Identity
# ═══════════════════════════════════════════════════════════════════════

class TestModel5Identity:
    def test_green_win_high_control(self, labeler):
        f = _base_features(result="W", pass_accuracy_for=85.0, possession_for=55.0)
        wl = labeler.label(f)
        assert wl.model_signals[MODEL_5] == GREEN

    def test_yellow_win_low_pass_accuracy(self, labeler):
        f = _base_features(result="W", pass_accuracy_for=78.0, possession_for=55.0)
        wl = labeler.label(f)
        assert wl.model_signals[MODEL_5] == YELLOW

    def test_yellow_win_low_possession(self, labeler):
        f = _base_features(result="W", pass_accuracy_for=82.0, possession_for=48.0)
        wl = labeler.label(f)
        assert wl.model_signals[MODEL_5] == YELLOW

    def test_red_loss(self, labeler):
        f = _base_features(result="L", pass_accuracy_for=85.0, possession_for=55.0)
        wl = labeler.label(f)
        assert wl.model_signals[MODEL_5] == RED

    def test_red_draw_poor_control(self, labeler):
        f = _base_features(result="D", pass_accuracy_for=70.0, possession_for=40.0)
        wl = labeler.label(f)
        assert wl.model_signals[MODEL_5] == RED

    def test_yellow_draw_acceptable_control(self, labeler):
        f = _base_features(result="D", pass_accuracy_for=78.0, possession_for=50.0)
        wl = labeler.label(f)
        assert wl.model_signals[MODEL_5] == YELLOW


# ═══════════════════════════════════════════════════════════════════════
# Model 6 — Role Clarity (Substitutions)
# ═══════════════════════════════════════════════════════════════════════

class TestModel6Subs:
    def test_green_early_subs_with_goals(self, labeler):
        f = _base_features(
            substitution_windows=[{"minute": 55, "player": "Nketiah", "scored_after": True}],
            arsenal_sub_count=1,
            goals_after_arsenal_subs=1,
        )
        wl = labeler.label(f)
        assert wl.model_signals[MODEL_6] == GREEN

    def test_yellow_subs_no_goals_after(self, labeler):
        f = _base_features(
            substitution_windows=[{"minute": 65, "player": "Nketiah", "scored_after": False}],
            arsenal_sub_count=1,
            goals_after_arsenal_subs=0,
        )
        wl = labeler.label(f)
        assert wl.model_signals[MODEL_6] == YELLOW

    def test_red_late_subs_conceded_after(self, labeler):
        f = _base_features(
            substitution_windows=[{"minute": 82, "player": "Nketiah", "scored_after": False}],
            arsenal_sub_count=1,
            goals_after_arsenal_subs=0,
            result="L",
            score_state_timeline=[
                {"minute": 0, "arsenal_score": 0, "opponent_score": 0},
                {"minute": 75, "arsenal_score": 1, "opponent_score": 0},
                {"minute": 85, "arsenal_score": 1, "opponent_score": 1},
                {"minute": 90, "arsenal_score": 1, "opponent_score": 2},
            ],
        )
        wl = labeler.label(f)
        assert wl.model_signals[MODEL_6] == RED

    def test_red_no_subs_when_trailing(self, labeler):
        f = _base_features(
            substitution_windows=[],
            arsenal_sub_count=0,
            goals_after_arsenal_subs=0,
            result="L",
        )
        wl = labeler.label(f)
        assert wl.model_signals[MODEL_6] == RED

    def test_yellow_no_subs_when_winning(self, labeler):
        f = _base_features(
            substitution_windows=[],
            arsenal_sub_count=0,
            goals_after_arsenal_subs=0,
            result="W",
        )
        wl = labeler.label(f)
        assert wl.model_signals[MODEL_6] == YELLOW


# ═══════════════════════════════════════════════════════════════════════
# Dimension derivation
# ═══════════════════════════════════════════════════════════════════════

class TestDimensions:
    def test_execution_green(self, labeler):
        f = _base_features(
            shot_delta=5, xg_delta=1.0, possession_delta=10,
            set_piece_goals_for=2, set_piece_goals_against=0,
        )
        wl = labeler.label(f)
        assert wl.dimension_signals["execution"] == GREEN

    def test_execution_red(self, labeler):
        f = _base_features(
            shot_delta=-5, xg_delta=-1.0, corner_delta=-3, possession_delta=-10,
            set_piece_goals_for=0, set_piece_goals_against=2,
        )
        wl = labeler.label(f)
        assert wl.dimension_signals["execution"] == RED

    def test_satisfaction_green(self, labeler):
        f = _base_features(
            yellow_cards_for=0, red_cards_for=0, fouls_for=8, fouls_against=10,
            goals_conceded=0, opponent_shots_on_target=2,
            result="W", pass_accuracy_for=85.0, possession_for=55.0,
        )
        wl = labeler.label(f)
        assert wl.dimension_signals["satisfaction"] == GREEN

    def test_satisfaction_red_majority(self, labeler):
        f = _base_features(
            red_cards_for=1,  # model 1 -> red
            goals_conceded=3, opponent_shots_on_target=5,  # model 3 -> red
            result="W", pass_accuracy_for=85.0, possession_for=55.0,
        )
        wl = labeler.label(f)
        assert wl.dimension_signals["satisfaction"] == RED

    def test_satisfaction_yellow_single_red(self, labeler):
        """With >=2 rule, 1 red + 1 green + 1 yellow -> yellow (no majority)."""
        f = _base_features(
            red_cards_for=1,  # model 1 -> red
            goals_conceded=1, opponent_shots_on_target=5,  # model 3 -> yellow
            result="W", pass_accuracy_for=85.0, possession_for=55.0,  # model 5 -> green
        )
        wl = labeler.label(f)
        assert wl.dimension_signals["satisfaction"] == YELLOW

    def test_adjustment_equals_model_6(self, labeler):
        f = _base_features()
        wl = labeler.label(f)
        assert wl.dimension_signals["adjustment"] == wl.model_signals[MODEL_6]


# ═══════════════════════════════════════════════════════════════════════
# Overall signal
# ═══════════════════════════════════════════════════════════════════════

class TestOverallSignal:
    def test_green_four_or_more_green_no_red(self, labeler):
        f = _base_features(
            # M1 green
            yellow_cards_for=0, red_cards_for=0, fouls_for=8, fouls_against=10,
            # M2 green
            shot_delta=5, xg_delta=1.0, possession_delta=10,
            # M3 green
            goals_conceded=0, opponent_shots_on_target=0,
            # M4 green
            set_piece_goals_for=1, set_piece_goals_against=0,
            # M5 green
            result="W", pass_accuracy_for=85.0, possession_for=55.0,
            # M6 any
        )
        wl = labeler.label(f)
        # At least M1-M4 green, M5 green, M6 yellow → 5 green, 0 red
        assert wl.overall_signal == GREEN

    def test_red_two_or_more_red(self, labeler):
        f = _base_features(
            red_cards_for=1,  # M1 red -> satisfaction
            goals_conceded=3,  # M3 red -> satisfaction
            shot_delta=-5, xg_delta=-1.0, corner_delta=-3,  # M2 red -> execution
            set_piece_goals_for=0, set_piece_goals_against=2,  # M4 red -> execution
            result="W", pass_accuracy_for=85.0, possession_for=55.0,
        )
        wl = labeler.label(f)
        # satisfaction: M1r M3r M5g -> 2 red -> r
        # execution: M2r M4r -> 2 red -> r
        # overall: >=2 red dims -> RED
        assert wl.overall_signal == RED

    def test_yellow_mixed(self, labeler):
        f = _base_features(
            yellow_cards_for=2, red_cards_for=0,  # M1 yellow
            shot_delta=5, xg_delta=1.0, possession_delta=10,  # M2 green
            goals_conceded=1, opponent_shots_on_target=5,  # M3 yellow
            set_piece_goals_for=1, set_piece_goals_against=1,  # M4 yellow (even)
            result="W", pass_accuracy_for=78.0, possession_for=55.0,  # M5 yellow
            arsenal_sub_count=1, goals_after_arsenal_subs=1,
            substitution_windows=[{"minute": 60, "player": "X", "scored_after": True}],
        )
        wl = labeler.label(f)
        # execution: M2g M4y -> 1 green -> yellow
        # adjustment: M6 green (single model)
        # satisfaction: M1y M3y M5y -> yellow
        # overall: 1 green, 0 red -> yellow
        assert wl.overall_signal == YELLOW


# ═══════════════════════════════════════════════════════════════════════
# Bournemouth 3-2 case
# ═══════════════════════════════════════════════════════════════════════

class TestBournemouth32:
    """Arsenal 3-2 Bournemouth: a win but with mixed signals."""

    def _bournemouth_features(self) -> MatchFeatures:
        return _base_features(
            result="W",
            score_margin=1,
            arsenal_goals=3,
            opponent_goals=2,
            goals_conceded=2,
            yellow_cards_for=3,
            red_cards_for=0,
            fouls_for=12,
            fouls_against=10,
            possession_for=58.0,
            possession_against=42.0,
            possession_delta=16.0,
            shots_for=10,
            shots_against=12,
            shot_delta=-2,
            shots_on_target_for=5,
            shots_on_target_against=4,
            xg_for=1.8,
            xg_against=1.3,
            xg_delta=0.5,
            pass_accuracy_for=82.0,
            pass_accuracy_against=78.0,
            pass_accuracy_delta=4.0,
            corners_for=7,
            corners_against=4,
            corner_delta=3,
            opponent_shots_on_target=4,
            set_piece_goals_for=0,
            set_piece_goals_against=0,
            substitution_windows=[
                {"minute": 62, "player": "Nketiah", "scored_after": True},
                {"minute": 70, "player": "Vieira", "scored_after": False},
            ],
            arsenal_sub_count=2,
            goals_after_arsenal_subs=1,
            score_state_timeline=[
                {"minute": 0, "arsenal_score": 0, "opponent_score": 0},
                {"minute": 20, "arsenal_score": 0, "opponent_score": 1},
                {"minute": 40, "arsenal_score": 1, "opponent_score": 1},
                {"minute": 55, "arsenal_score": 1, "opponent_score": 2},
                {"minute": 72, "arsenal_score": 2, "opponent_score": 2},
                {"minute": 88, "arsenal_score": 3, "opponent_score": 2},
            ],
            missing_data=[],
        )

    def test_mixed_signals_not_all_green(self, labeler):
        f = self._bournemouth_features()
        wl = labeler.label(f)
        # Win, but 2 conceded and negative shot_delta → must NOT be all green
        green_count = sum(1 for s in wl.model_signals.values() if s == GREEN)
        assert green_count < 6, f"Expected mixed signals, got {green_count} greens: {wl.model_signals}"

    def test_not_overall_green(self, labeler):
        f = self._bournemouth_features()
        wl = labeler.label(f)
        assert wl.overall_signal != GREEN, "Bournemouth 3-2 should not be overall green"

    def test_has_at_least_one_yellow_or_red(self, labeler):
        f = self._bournemouth_features()
        wl = labeler.label(f)
        non_green = sum(1 for s in wl.model_signals.values() if s != GREEN)
        assert non_green >= 2, f"Expected at least 2 non-green signals, got {non_green}"

    def test_specific_model_signals(self, labeler):
        """Verify specific expected signals for Bournemouth 3-2."""
        f = self._bournemouth_features()
        wl = labeler.label(f)
        # M1: 3 yellows → yellow
        assert wl.model_signals[MODEL_1] == YELLOW
        # M2: shot_delta=-2, xg_delta=+0.5 → mixed (yellow)
        assert wl.model_signals[MODEL_2] == YELLOW
        # M3: 2 conceded, opp_sot=4 → yellow
        assert wl.model_signals[MODEL_3] == YELLOW
        # M5: win, pass_accuracy=82>80, possession=58>50 → green
        assert wl.model_signals[MODEL_5] == GREEN
        # M6: subs before 70, goals after → green
        assert wl.model_signals[MODEL_6] == GREEN


# ═══════════════════════════════════════════════════════════════════════
# Reproducibility
# ═══════════════════════════════════════════════════════════════════════

class TestReproducibility:
    def test_same_input_same_output(self, labeler):
        f = _base_features()
        wl1 = labeler.label(f)
        wl2 = labeler.label(f)
        assert wl1.model_signals == wl2.model_signals
        assert wl1.dimension_signals == wl2.dimension_signals
        assert wl1.overall_signal == wl2.overall_signal
        assert wl1.confidence == wl2.confidence
        assert wl1.evidence_refs == wl2.evidence_refs

    def test_deterministic_across_runs(self, labeler):
        """No randomness or LLM — same features always produce same labels."""
        f = _base_features(
            yellow_cards_for=2, shot_delta=-1, xg_delta=0.3,
            goals_conceded=1, set_piece_goals_for=0, set_piece_goals_against=1,
            result="W", pass_accuracy_for=79.0, possession_for=52.0,
        )
        results = [labeler.label(f) for _ in range(10)]
        for r in results[1:]:
            assert r.model_signals == results[0].model_signals
            assert r.overall_signal == results[0].overall_signal


# ═══════════════════════════════════════════════════════════════════════
# Missing data penalty
# ═══════════════════════════════════════════════════════════════════════

class TestMissingData:
    def test_missing_data_flag_set(self, labeler):
        f = _base_features(missing_data=["xG", "pressing"])
        wl = labeler.label(f)
        assert wl.missing_data_penalty is True

    def test_missing_xg_confidence_drops(self, labeler):
        f = _base_features(
            xg_for=None, xg_against=None, xg_delta=None,
            missing_data=["xG"],
            shot_delta=3, possession_delta=10,
        )
        wl = labeler.label(f)
        # Model 2 should still produce a label but with medium confidence
        assert wl.model_signals[MODEL_2] in (GREEN, YELLOW, RED)
        assert wl.confidence[MODEL_2] in ("medium", "low")

    def test_labels_still_produced_with_missing_data(self, labeler):
        f = _base_features(
            xg_for=None, xg_against=None, xg_delta=None,
            pass_accuracy_for=None, pass_accuracy_against=None, pass_accuracy_delta=None,
            possession_for=None, possession_against=None, possession_delta=None,
            missing_data=["xG", "pass_accuracy", "possession"],
        )
        wl = labeler.label(f)
        # All 6 models should still produce a signal
        assert len(wl.model_signals) == 6
        assert all(s in (GREEN, YELLOW, RED) for s in wl.model_signals.values())
        # All 3 dimensions should be set
        assert len(wl.dimension_signals) == 3

    def test_no_penalty_when_no_missing(self, labeler):
        f = _base_features(missing_data=[])
        wl = labeler.label(f)
        assert wl.missing_data_penalty is False


# ═══════════════════════════════════════════════════════════════════════
# Edge cases
# ═══════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_clean_sheet(self, labeler):
        f = _base_features(
            result="W", arsenal_goals=2, opponent_goals=0, goals_conceded=0,
            opponent_shots_on_target=1,
        )
        wl = labeler.label(f)
        assert wl.model_signals[MODEL_3] == GREEN

    def test_heavy_loss(self, labeler):
        f = _base_features(
            result="L", score_margin=-4, arsenal_goals=0, opponent_goals=4,
            goals_conceded=4, opponent_shots_on_target=8,
            yellow_cards_for=4, red_cards_for=1,
            pass_accuracy_for=70.0, possession_for=40.0,
            set_piece_goals_for=0, set_piece_goals_against=2,
            shot_delta=-5, xg_delta=-1.5, corner_delta=-3,  # M2 red -> execution
        )
        wl = labeler.label(f)
        assert wl.model_signals[MODEL_3] == RED
        assert wl.model_signals[MODEL_5] == RED
        assert wl.model_signals[MODEL_1] == RED
        # satisfaction: M1r M3r M5r -> r, execution: M2r M4r -> r
        # overall: >=2 red dims -> RED
        assert wl.overall_signal == RED

    def test_draw(self, labeler):
        f = _base_features(
            result="D", score_margin=0, arsenal_goals=1, opponent_goals=1,
            goals_conceded=1, opponent_shots_on_target=4,
            pass_accuracy_for=78.0, possession_for=50.0,
        )
        wl = labeler.label(f)
        assert wl.model_signals[MODEL_5] == YELLOW  # draw with acceptable control

    def test_high_scoring_win(self, labeler):
        f = _base_features(
            result="W", arsenal_goals=5, opponent_goals=1,
            goals_conceded=1, opponent_shots_on_target=2,
            shot_delta=10, xg_delta=2.5,
            yellow_cards_for=0, red_cards_for=0, fouls_for=8, fouls_against=12,
            pass_accuracy_for=88.0, possession_for=62.0,
            set_piece_goals_for=2, set_piece_goals_against=0,
        )
        wl = labeler.label(f)
        assert wl.model_signals[MODEL_1] == GREEN
        assert wl.model_signals[MODEL_2] == GREEN
        assert wl.model_signals[MODEL_3] == GREEN
        assert wl.model_signals[MODEL_4] == GREEN
        assert wl.model_signals[MODEL_5] == GREEN
        assert wl.overall_signal == GREEN

    def test_evidence_refs_populated(self, labeler):
        f = _base_features()
        wl = labeler.label(f)
        for model_id in [MODEL_1, MODEL_2, MODEL_3, MODEL_4, MODEL_5, MODEL_6]:
            assert model_id in wl.evidence_refs
            assert len(wl.evidence_refs[model_id]) > 0

    def test_weak_label_version_set(self, labeler):
        f = _base_features()
        wl = labeler.label(f)
        assert wl.weak_label_version == "v1.1"


# ═══════════════════════════════════════════════════════════════════════
# WK v1.1 Result-aware loss guards
# ═══════════════════════════════════════════════════════════════════════

def _lower_loss_dominant_features() -> MatchFeatures:
    """1531572-style: all stats dominant, but result=L, opponent=lower."""
    return MatchFeatures(
        result="L", opponent_quality="lower", venue="away",
        competition_stage="regular", opponent_name="Southampton",
        arsenal_goals=1, opponent_goals=2, score_margin=-1,
        goals_conceded=2, yellow_cards_for=1, red_cards_for=0,
        possession_for=64.0, possession_against=36.0, possession_delta=28.0,
        shots_for=23, shots_against=8, shot_delta=15,
        shots_on_target_for=7, shots_on_target_against=4, shot_on_target_delta=3,
        xg_for=2.10, xg_against=0.80, xg_delta=1.30,
        pass_accuracy_for=89.0, pass_accuracy_against=79.0, pass_accuracy_delta=10.0,
        corners_for=9, corners_against=4, corner_delta=5,
        fouls_for=11, fouls_against=9,
        substitution_windows=[{"minute": 60, "player": "Trossard", "scored_after": True}],
        arsenal_sub_count=5, goals_after_arsenal_subs=1, goals_by_substitutes=0,
        missing_data=["pressing", "pressing_recoveries", "transition"],
    )


def test_loss_to_lower_with_dominant_stats_is_red():
    """1531572-style: WK must veto satisfaction and overall to 🔴."""
    from src.labels.weak_labeler import WeakLabeler
    f = _lower_loss_dominant_features()
    wl = WeakLabeler().label(f)
    assert wl.dimension_signals["satisfaction"] == "🔴"
    assert wl.overall_signal == "🔴"
    assert wl.weak_label_version == "v1.1"


def test_loss_to_mid_table_cannot_be_green():
    """1379109-style: satisfaction=🔴, overall must not be 🟢."""
    from src.labels.weak_labeler import WeakLabeler
    from src.features.extractor import MatchFeatures
    f = MatchFeatures(
        result="L", opponent_quality="mid_table", venue="away",
        arsenal_goals=1, opponent_goals=2, score_margin=-1,
        goals_conceded=2, yellow_cards_for=2, red_cards_for=0,
        possession_for=53.0, possession_against=47.0, possession_delta=6.0,
        shots_for=15, shots_against=15, shot_delta=0,
        shots_on_target_for=9, shots_on_target_against=6, shot_on_target_delta=3,
        xg_for=1.92, xg_against=2.16, xg_delta=-0.24,
        pass_accuracy_for=85.0, pass_accuracy_against=82.0, pass_accuracy_delta=3.0,
        corners_for=3, corners_against=3, corner_delta=0,
        fouls_for=8, fouls_against=10,
        substitution_windows=[{"minute": 46, "player": "Sub", "scored_after": True}],
        arsenal_sub_count=5, goals_after_arsenal_subs=1,
        missing_data=[],
    )
    wl = WeakLabeler().label(f)
    assert wl.dimension_signals["satisfaction"] == "🔴"
    assert wl.overall_signal != "🟢"
    assert wl.weak_label_version == "v1.1"


def test_loss_to_top6_cannot_be_green():
    """Loss to top6 may be 🔴 or 🟡, but never 🟢."""
    from src.labels.weak_labeler import WeakLabeler
    from src.features.extractor import MatchFeatures
    f = MatchFeatures(
        result="L", opponent_quality="top6", venue="away",
        arsenal_goals=0, opponent_goals=1, score_margin=-1,
        goals_conceded=1, yellow_cards_for=2, red_cards_for=0,
        possession_for=47.0, possession_against=53.0, possession_delta=-6.0,
        shots_for=11, shots_against=9, shot_delta=2,
        shots_on_target_for=1, shots_on_target_against=3, shot_on_target_delta=-2,
        xg_for=0.49, xg_against=0.52, xg_delta=-0.03,
        pass_accuracy_for=82.0, pass_accuracy_against=85.0, pass_accuracy_delta=-3.0,
        corners_for=8, corners_against=3, corner_delta=5,
        fouls_for=10, fouls_against=7,
        substitution_windows=[{"minute": 5, "player": "Early", "scored_after": False}],
        arsenal_sub_count=4, goals_after_arsenal_subs=0,
        missing_data=[],
    )
    wl = WeakLabeler().label(f)
    assert wl.overall_signal != "🟢"
    assert wl.dimension_signals["satisfaction"] != "🟢"


def test_win_with_dominant_stats_unchanged():
    """1208154-style: W must not be affected by loss guard."""
    from src.labels.weak_labeler import WeakLabeler
    from src.features.extractor import MatchFeatures
    f = MatchFeatures(
        result="W", opponent_quality="top6", venue="home",
        arsenal_goals=2, opponent_goals=0, score_margin=2,
        goals_conceded=0, yellow_cards_for=1, red_cards_for=0,
        possession_for=50.0, possession_against=50.0, possession_delta=0.0,
        shots_for=14, shots_against=5, shot_delta=9,
        shots_on_target_for=6, shots_on_target_against=2, shot_on_target_delta=4,
        xg_for=2.16, xg_against=0.22, xg_delta=1.94,
        pass_accuracy_for=87.0, pass_accuracy_against=87.0, pass_accuracy_delta=0.0,
        corners_for=13, corners_against=0, corner_delta=13,
        fouls_for=12, fouls_against=8,
        substitution_windows=[{"minute": 71, "player": "Sub", "scored_after": True}],
        arsenal_sub_count=3, goals_after_arsenal_subs=1,
        missing_data=[],
    )
    wl = WeakLabeler().label(f)
    assert wl.dimension_signals["satisfaction"] != "🔴"
    assert wl.overall_signal != "🔴"
    assert wl.weak_label_version == "v1.1"


def test_weak_label_version_is_v1_1():
    """Any label output must have version=v1.1."""
    from src.labels.weak_labeler import WeakLabeler
    from src.features.extractor import MatchFeatures
    f = MatchFeatures(result="D", opponent_quality="mid_table", venue="home",
        arsenal_goals=1, opponent_goals=1, score_margin=0,
        goals_conceded=1, yellow_cards_for=0, red_cards_for=0,
        possession_for=55.0, possession_against=45.0, possession_delta=10.0,
        shots_for=10, shots_against=10, shot_delta=0,
        shots_on_target_for=3, shots_on_target_against=3, shot_on_target_delta=0,
        xg_for=1.0, xg_against=1.0, xg_delta=0.0,
        pass_accuracy_for=80.0, pass_accuracy_against=80.0, pass_accuracy_delta=0.0,
        corners_for=5, corners_against=5, corner_delta=0,
        fouls_for=10, fouls_against=10,
        missing_data=[],
    )
    wl = WeakLabeler().label(f)
    assert wl.weak_label_version == "v1.1"
