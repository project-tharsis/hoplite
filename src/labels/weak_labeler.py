"""Rule-based weak labeler for Arteta's 6 models and 3 dimensions.

Produces WeakLabels from MatchFeatures deterministically.
No LLM calls. Same input → same output every time.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.features.extractor import MatchFeatures

GREEN = "🟢"
YELLOW = "🟡"
RED = "🔴"

# Model IDs
MODEL_1 = "culture_as_os"
MODEL_2 = "where_game_is_played"
MODEL_3 = "defence_as_attacking_identity"
MODEL_4 = "marginal_gains"
MODEL_5 = "add_capability_keep_identity"
MODEL_6 = "role_clarity"

ALL_MODELS = [MODEL_1, MODEL_2, MODEL_3, MODEL_4, MODEL_5, MODEL_6]

# Dimension → constituent models
DIMENSION_MAP = {
    "execution": [MODEL_2, MODEL_4],
    "adjustment": [MODEL_6],
    "satisfaction": [MODEL_1, MODEL_3, MODEL_5],
}


@dataclass
class WeakLabels:
    """Weak label output matching spec Section 6.4."""

    model_signals: dict[str, str] = field(default_factory=dict)
    dimension_signals: dict[str, str] = field(default_factory=dict)
    overall_signal: str = ""
    confidence: dict[str, str] = field(default_factory=dict)
    evidence_refs: dict[str, list[str]] = field(default_factory=dict)
    missing_data_penalty: bool = False
    weak_label_version: str = "v1"


class WeakLabeler:
    """Rule-based weak labeler. Takes MatchFeatures, produces WeakLabels."""

    def label(self, features: MatchFeatures) -> WeakLabels:
        """Generate weak labels from match features."""
        wl = WeakLabels()
        wl.missing_data_penalty = bool(features.missing_data)

        # ── Label all 6 models ────────────────────────────────────────
        wl.model_signals[MODEL_1], wl.evidence_refs[MODEL_1], wl.confidence[MODEL_1] = (
            self._model_1_culture(features)
        )
        wl.model_signals[MODEL_2], wl.evidence_refs[MODEL_2], wl.confidence[MODEL_2] = (
            self._model_2_territory(features)
        )
        wl.model_signals[MODEL_3], wl.evidence_refs[MODEL_3], wl.confidence[MODEL_3] = (
            self._model_3_defence(features)
        )
        wl.model_signals[MODEL_4], wl.evidence_refs[MODEL_4], wl.confidence[MODEL_4] = (
            self._model_4_marginal(features)
        )
        wl.model_signals[MODEL_5], wl.evidence_refs[MODEL_5], wl.confidence[MODEL_5] = (
            self._model_5_identity(features)
        )
        wl.model_signals[MODEL_6], wl.evidence_refs[MODEL_6], wl.confidence[MODEL_6] = (
            self._model_6_subs(features)
        )

        # ── Derive dimensions (majority vote) ────────────────────────
        for dim, model_ids in DIMENSION_MAP.items():
            signals = [wl.model_signals[m] for m in model_ids]
            if len(signals) == 1:
                # Single-model dimension: model signal IS the dimension
                wl.dimension_signals[dim] = signals[0]
            else:
                green_count = sum(1 for s in signals if s == GREEN)
                red_count = sum(1 for s in signals if s == RED)
                if green_count >= 2:
                    wl.dimension_signals[dim] = GREEN
                elif red_count >= 2:
                    wl.dimension_signals[dim] = RED
                else:
                    wl.dimension_signals[dim] = YELLOW

        # ── Overall signal from dimension vote (≥2 → majority) ────────
        dim_signals = list(wl.dimension_signals.values())
        green_dims = sum(1 for s in dim_signals if s == GREEN)
        red_dims = sum(1 for s in dim_signals if s == RED)
        if green_dims >= 2:
            wl.overall_signal = GREEN
        elif red_dims >= 2:
            wl.overall_signal = RED
        else:
            wl.overall_signal = YELLOW

        # ── Apply missing data penalty to confidence ──────────────────
        if wl.missing_data_penalty:
            for model_id in ALL_MODELS:
                if wl.confidence[model_id] == "high":
                    wl.confidence[model_id] = "medium"

        return wl

    # ── Model 1: Culture as OS (discipline) ───────────────────────────

    def _model_1_culture(
        self, f: MatchFeatures
    ) -> tuple[str, list[str], str]:
        evidence: list[str] = []
        yellow = f.yellow_cards_for
        red = f.red_cards_for
        fouls = f.fouls_for
        fouls_opp = f.fouls_against

        evidence.append(f"yellow_cards_for={yellow}")
        evidence.append(f"red_cards_for={red}")

        # Red card → always red
        if red > 0:
            evidence.append("red_card_present")
            return RED, evidence, "high"

        # 4+ yellow → red
        if yellow >= 4:
            evidence.append(f"yellow_cards={yellow}>=4")
            return RED, evidence, "high"

        # Check critical-time cards from score_state_timeline
        critical_card = self._has_critical_time_card(f)
        if critical_card:
            evidence.append("critical_time_card")
            return RED, evidence, "high"

        # Fouls far above opponent → red
        if fouls is not None and fouls_opp is not None:
            evidence.append(f"fouls_for={fouls}")
            evidence.append(f"fouls_against={fouls_opp}")
            if fouls - fouls_opp >= 8:
                evidence.append(f"fouls_delta={fouls - fouls_opp}>=8")
                return RED, evidence, "high"

        # 2-3 yellow or fouls slightly above → yellow
        if yellow >= 2:
            evidence.append(f"yellow_cards={yellow}>=2")
            return YELLOW, evidence, "high"

        if fouls is not None and fouls_opp is not None:
            if fouls - fouls_opp >= 4:
                evidence.append(f"fouls_delta={fouls - fouls_opp}>=4")
                return YELLOW, evidence, "medium"

        # 0-1 yellow, no red, fouls ≤ opponent → green
        return GREEN, evidence, "high"

    def _has_critical_time_card(self, f: MatchFeatures) -> bool:
        """Check if any card occurred at a critical moment (e.g., while trailing late)."""
        # This is a simplified check — look for cards while losing after 70'
        # In full implementation, this would cross-reference card events with score timeline
        # For now, we use the score_state_timeline to detect if Arsenal was trailing late
        timeline = f.score_state_timeline
        if not timeline:
            return False
        # Check final state — if trailing at end, that's already captured by result
        # Critical-time card is specifically: card while losing late that changes game state
        # We approximate: if yellow_cards >= 2 AND result == L, it's likely critical
        if f.yellow_cards_for >= 2 and f.result == "L":
            return True
        return False

    # ── Model 2: Where the Game Is Played (territorial control) ───────

    def _model_2_territory(
        self, f: MatchFeatures
    ) -> tuple[str, list[str], str]:
        evidence: list[str] = []
        shot_delta = f.shot_delta
        xg_delta = f.xg_delta
        poss_delta = f.possession_delta
        corner_delta = f.corner_delta
        opp_sot = f.opponent_shots_on_target
        pa_delta = f.pass_accuracy_delta

        confidence = "high"

        # Track which data is available
        has_shots = shot_delta is not None
        has_xg = xg_delta is not None
        has_poss = poss_delta is not None
        has_corners = corner_delta is not None
        has_pa = pa_delta is not None

        if has_shots:
            evidence.append(f"shot_delta={shot_delta}")
        if has_xg:
            evidence.append(f"xg_delta={xg_delta:.2f}" if xg_delta is not None else "xg_delta=None")
        if has_poss:
            evidence.append(f"possession_delta={poss_delta:.1f}" if poss_delta is not None else "possession_delta=None")
        if has_corners:
            evidence.append(f"corner_delta={corner_delta}")
        if opp_sot is not None:
            evidence.append(f"opponent_shots_on_target={opp_sot}")

        # Green: positive shot_delta AND positive xg_delta
        if has_shots and has_xg:
            if shot_delta is not None and shot_delta > 0 and xg_delta is not None and xg_delta > 0:
                return GREEN, evidence, "high"
        # Green fallback: xg missing but shots+possession both positive
        if has_shots and not has_xg:
            if shot_delta is not None and shot_delta > 0 and has_poss and poss_delta is not None and poss_delta > 0:
                confidence = "medium"
                return GREEN, evidence, confidence

        # Red: negative shot_delta AND negative xg_delta AND corner_delta negative
        if has_shots and has_xg and has_corners:
            if (shot_delta is not None and shot_delta < 0
                    and xg_delta is not None and xg_delta < 0
                    and corner_delta is not None and corner_delta < 0):
                return RED, evidence, "high"

        # Mixed signals → yellow
        # Possession positive but shots negative, or vice versa
        if has_poss and has_shots:
            if poss_delta is not None and shot_delta is not None:
                if (poss_delta > 0 and shot_delta < 0) or (poss_delta < 0 and shot_delta > 0):
                    confidence = "medium"
                    return YELLOW, evidence, confidence

        # If we have some data but not enough for green/red, default to yellow
        if has_shots or has_poss or has_xg:
            return YELLOW, evidence, "medium"

        # Very little data → yellow with low confidence
        confidence = "low"
        return YELLOW, evidence, confidence

    # ── Model 3: Defence as Attacking Identity ────────────────────────

    def _model_3_defence(
        self, f: MatchFeatures
    ) -> tuple[str, list[str], str]:
        evidence: list[str] = []
        conceded = f.goals_conceded
        opp_sot = f.opponent_shots_on_target
        xg_a = f.xg_against

        evidence.append(f"goals_conceded={conceded}")
        if opp_sot is not None:
            evidence.append(f"opponent_shots_on_target={opp_sot}")
        if xg_a is not None:
            evidence.append(f"xg_against={xg_a:.2f}")

        confidence = "high"

        # Green: clean sheet
        if conceded == 0:
            return GREEN, evidence, confidence

        # Green: 1 goal conceded with opponent_shots_on_target ≤ 3
        if conceded == 1 and opp_sot is not None and opp_sot <= 3:
            return GREEN, evidence, confidence

        # Red: 3+ conceded
        if conceded >= 3:
            return RED, evidence, confidence

        # Red: high xg_against (>2.0)
        if xg_a is not None and xg_a > 2.0:
            confidence = "medium"
            return RED, evidence, confidence

        # Yellow: 1-2 conceded
        if conceded <= 2:
            # Higher opponent_shots_on_target but score margin positive → still yellow
            if opp_sot is not None and opp_sot > 5 and f.score_margin > 0:
                return YELLOW, evidence, "medium"
            return YELLOW, evidence, confidence

        return YELLOW, evidence, "medium"

    # ── Model 4: Marginal Gains (set pieces) ──────────────────────────

    def _model_4_marginal(
        self, f: MatchFeatures
    ) -> tuple[str, list[str], str]:
        evidence: list[str] = []
        sp_for = f.set_piece_goals_for
        sp_against = f.set_piece_goals_against
        corners_for = f.corners_for
        corners_against = f.corners_against

        evidence.append(f"set_piece_goals_for={sp_for}")
        evidence.append(f"set_piece_goals_against={sp_against}")

        confidence = "high"

        # Green: set_piece_goals_for > set_piece_goals_against
        if sp_for > sp_against:
            return GREEN, evidence, confidence

        # Green: even but corners advantage > 3
        if sp_for == sp_against and corners_for is not None and corners_against is not None:
            evidence.append(f"corners_for={corners_for}")
            evidence.append(f"corners_against={corners_against}")
            if corners_for - corners_against > 3:
                return GREEN, evidence, confidence

        # Red: set_piece_goals_against > set_piece_goals_for
        if sp_against > sp_for:
            return RED, evidence, confidence

        # Yellow: neutral
        if corners_for is not None and corners_against is not None:
            evidence.append(f"corners_for={corners_for}")
            evidence.append(f"corners_against={corners_against}")

        return YELLOW, evidence, confidence

    # ── Model 5: Add Capability, Keep Identity ────────────────────────

    def _model_5_identity(
        self, f: MatchFeatures
    ) -> tuple[str, list[str], str]:
        evidence: list[str] = []
        result = f.result
        pa = f.pass_accuracy_for
        poss = f.possession_for
        goals = f.arsenal_goals
        xg = f.xg_for

        evidence.append(f"result={result}")
        if pa is not None:
            evidence.append(f"pass_accuracy_for={pa:.1f}")
        if poss is not None:
            evidence.append(f"possession_for={poss:.1f}")
        evidence.append(f"goals_for={goals}")
        if xg is not None:
            evidence.append(f"xg_for={xg:.2f}")

        confidence = "high"
        has_pa = pa is not None
        has_poss = poss is not None

        # Green: win AND pass_accuracy > 80% AND possession > 50%
        if result == "W" and has_pa and has_poss:
            if pa is not None and pa > 80 and poss is not None and poss > 50:
                return GREEN, evidence, confidence

        # Red: loss
        if result == "L":
            return RED, evidence, confidence

        # Red: draw with poor control metrics
        if result == "D":
            poor_count = 0
            if has_pa and pa is not None and pa < 75:
                poor_count += 1
            if has_poss and poss is not None and poss < 45:
                poor_count += 1
            if poor_count >= 2:
                confidence = "medium"
                return RED, evidence, confidence

        # Yellow: win but one control metric below threshold
        if result == "W":
            below_threshold = 0
            if has_pa and pa is not None and pa <= 80:
                below_threshold += 1
            if has_poss and poss is not None and poss <= 50:
                below_threshold += 1
            if below_threshold >= 1:
                confidence = "medium"
                return YELLOW, evidence, confidence
            # If missing data, can't confirm green
            if not has_pa or not has_poss:
                confidence = "medium"
                return YELLOW, evidence, confidence

        # Yellow: draw with acceptable control
        if result == "D":
            return YELLOW, evidence, "medium"

        return YELLOW, evidence, "medium"

    # ── Model 6: Role Clarity > Pressure (substitutions) ─────────────

    def _model_6_subs(
        self, f: MatchFeatures
    ) -> tuple[str, list[str], str]:
        evidence: list[str] = []
        windows = f.substitution_windows
        sub_count = f.arsenal_sub_count
        goals_after = f.goals_after_arsenal_subs

        evidence.append(f"arsenal_sub_count={sub_count}")
        evidence.append(f"goals_after_arsenal_subs={goals_after}")

        # No subs when trailing → red
        if sub_count == 0 and f.result == "L":
            evidence.append("no_subs_when_trailing")
            return RED, evidence, "high"

        if sub_count == 0:
            evidence.append("no_substitutions")
            return YELLOW, evidence, "medium"

        # Find earliest and latest sub minutes
        minutes = [w.get("minute", 90) for w in windows] if windows else []
        earliest = min(minutes) if minutes else 90
        latest = max(minutes) if minutes else 90

        evidence.append(f"earliest_sub_min={earliest}")
        evidence.append(f"latest_sub_min={latest}")

        # Green: subs before 70' AND goals after subs > 0
        if earliest < 70 and goals_after > 0:
            # High confidence if subs directly scored/assisted;
            # medium if only starters scored after subs came on
            if f.goals_by_substitutes > 0:
                evidence.append(f"goals_by_substitutes={f.goals_by_substitutes}")
                return GREEN, evidence, "high"
            else:
                evidence.append("goals_after_subs_not_by_substitutes")
                return GREEN, evidence, "medium"

        # Red: subs late (>80') AND goals conceded after subs
        if latest > 80:
            # Check if opponent scored after subs
            conceded_after = self._goals_conceded_after_subs(f, earliest)
            evidence.append(f"goals_conceded_after_subs={conceded_after}")
            if conceded_after > 0:
                return RED, evidence, "high"

        # Yellow: subs present but impact unclear
        return YELLOW, evidence, "medium"

    def _goals_conceded_after_subs(self, f: MatchFeatures, first_sub_minute: int) -> int:
        """Estimate goals conceded after first substitution from score timeline."""
        timeline = f.score_state_timeline
        if not timeline or first_sub_minute >= 90:
            return 0

        conceded = 0
        prev_opponent_score = 0
        for entry in timeline:
            if entry.get("minute", 0) <= first_sub_minute:
                prev_opponent_score = entry.get("opponent_score", 0)
            elif entry.get("opponent_score", 0) > prev_opponent_score:
                conceded += entry.get("opponent_score", 0) - prev_opponent_score
                prev_opponent_score = entry.get("opponent_score", 0)

        return conceded
