"""Tests for Phase 2 feature extraction (MatchFeatures / FeatureExtractor)."""
from __future__ import annotations

import pytest

from src.features.extractor import MatchFeatures, FeatureExtractor


# ── Fixture: Arsenal 3-2 Bournemouth (complete stats, no xG) ──────────


def _arsenal_3_2_bournemouth() -> dict:
    """Arsenal 3-2 Bournemouth — the canonical P1 test pattern.

    Has possession, shots, shots on target, corners, fouls.
    No xG (common for lower-table opponents).
    Subs: Nketiah (65'), Havertz (70') — both scored after.
    """
    return {
        "fixture_id": 12345,
        "date": "2025-05-01T15:00:00",
        "competition": "Premier League",
        "home_team": "Arsenal",
        "away_team": "Bournemouth",
        "home_score": 3,
        "away_score": 2,
        # No xG — intentionally omitted
        "home_stats": {
            "Ball Possession": "62%",
            "Total Shots": 18,
            "Shots on Goal": 7,
            "Passes %": "88%",
            "Corner Kicks": 9,
            "Fouls": 10,
        },
        "away_stats": {
            "Ball Possession": "38%",
            "Total Shots": 11,
            "Shots on Goal": 4,
            "Passes %": "76%",
            "Corner Kicks": 3,
            "Fouls": 14,
        },
        "events": [
            {"minute": 12, "type": "Goal", "team": "home", "player": "Saka", "detail": "Normal Goal"},
            {"minute": 45, "type": "Goal", "team": "away", "player": "Solanke", "detail": "Normal Goal"},
            {"minute": 60, "type": "Card", "team": "away", "player": "Cook", "detail": "Yellow Card"},
            {"minute": 65, "type": "subst", "team": "home", "player": "Nketiah", "detail": "Tactical"},
            {"minute": 70, "type": "subst", "team": "home", "player": "Havertz", "detail": "Tactical"},
            {"minute": 80, "type": "Goal", "team": "home", "player": "Nketiah", "detail": "Normal Goal"},
            {"minute": 85, "type": "Goal", "team": "home", "player": "Havertz", "detail": "Normal Goal"},
            {"minute": 90, "type": "Goal", "team": "away", "player": "Tavernier", "detail": "Normal Goal"},
        ],
    }


def _arsenal_3_2_with_xg() -> dict:
    """Same 3-2 Bournemouth match but WITH xG data."""
    m = _arsenal_3_2_bournemouth()
    m["home_xg"] = 2.4
    m["away_xg"] = 1.1
    return m


def _arsenal_win_with_set_pieces() -> dict:
    """Arsenal 2-0 with a penalty and a corner goal."""
    return {
        "fixture_id": 99999,
        "date": "2025-03-15T15:00:00",
        "competition": "Premier League",
        "home_team": "Arsenal",
        "away_team": "Everton",
        "home_score": 2,
        "away_score": 0,
        "home_xg": 1.8,
        "away_xg": 0.3,
        "home_stats": {
            "Ball Possession": "65%",
            "Total Shots": 15,
            "Shots on Goal": 6,
            "Passes %": "90%",
            "Corner Kicks": 7,
            "Fouls": 8,
        },
        "away_stats": {
            "Ball Possession": "35%",
            "Total Shots": 5,
            "Shots on Goal": 1,
            "Passes %": "72%",
            "Corner Kicks": 2,
            "Fouls": 12,
        },
        "events": [
            {"minute": 23, "type": "Goal", "team": "home", "player": "Saka", "detail": "Penalty"},
            {"minute": 67, "type": "Goal", "team": "home", "player": "Gabriel", "detail": "Header from corner"},
        ],
    }


def _arsenal_away_draw() -> dict:
    """Arsenal 1-1 away draw against Man City."""
    return {
        "fixture_id": 88888,
        "date": "2025-04-01T20:00:00",
        "competition": "Premier League",
        "home_team": "Man City",
        "away_team": "Arsenal",
        "home_score": 1,
        "away_score": 1,
        "home_xg": 0.9,
        "away_xg": 0.7,
        "home_stats": {
            "Ball Possession": "55%",
            "Total Shots": 10,
            "Shots on Goal": 3,
            "Passes %": "89%",
            "Corner Kicks": 5,
            "Fouls": 9,
        },
        "away_stats": {
            "Ball Possession": "45%",
            "Total Shots": 8,
            "Shots on Goal": 2,
            "Passes %": "85%",
            "Corner Kicks": 3,
            "Fouls": 11,
        },
        "events": [
            {"minute": 34, "type": "Goal", "team": "home", "player": "Haaland", "detail": "Normal Goal"},
            {"minute": 72, "type": "Goal", "team": "away", "player": "Rice", "detail": "Normal Goal"},
        ],
    }


def _empty_match() -> dict:
    """Match with minimal data — most stats missing."""
    return {
        "fixture_id": 0,
        "date": "2025-01-01T15:00:00",
        "competition": "FA Cup",
        "home_team": "Arsenal",
        "away_team": "Unknown FC",
        "home_score": 0,
        "away_score": 0,
    }


# ── Test class ────────────────────────────────────────────────────────


class TestMatchFeaturesDataclass:
    """MatchFeatures dataclass basic properties."""

    def test_default_missing_data_is_empty_list(self):
        f = MatchFeatures()
        assert f.missing_data == []

    def test_to_dict_returns_all_fields(self):
        d = MatchFeatures(result="W", arsenal_goals=3).to_dict()
        assert d["result"] == "W"
        assert d["arsenal_goals"] == 3
        assert "missing_data" in d
        assert "score_state_timeline" in d


class TestFeatureExtractorResultDetection:
    """Result W/D/L detection from scores."""

    def test_win(self):
        f = FeatureExtractor().extract(_arsenal_3_2_bournemouth())
        assert f.result == "W"
        assert f.score_margin == 1

    def test_draw(self):
        f = FeatureExtractor().extract(_arsenal_away_draw())
        assert f.result == "D"
        assert f.score_margin == 0

    def test_loss(self):
        m = _arsenal_away_draw()
        m["home_score"] = 3
        m["away_score"] = 1
        f = FeatureExtractor().extract(m)
        assert f.result == "L"
        assert f.score_margin == -2


class TestFeatureExtractorVenueDetection:
    """Venue home/away detection."""

    def test_home(self):
        f = FeatureExtractor().extract(_arsenal_3_2_bournemouth())
        assert f.venue == "home"

    def test_away(self):
        f = FeatureExtractor().extract(_arsenal_away_draw())
        assert f.venue == "away"


class TestFeatureExtractorOpponentQuality:
    """Opponent quality tier classification."""

    def test_mid_table_opponent(self):
        f = FeatureExtractor().extract(_arsenal_3_2_bournemouth())
        assert f.opponent_quality == "mid_table"

    def test_top6_opponent(self):
        f = FeatureExtractor().extract(_arsenal_away_draw())
        assert f.opponent_quality == "top6"


class TestFeatureExtractorStatsFields:
    """Stats fields extraction from match data."""

    def test_possession_parsed(self):
        f = FeatureExtractor().extract(_arsenal_3_2_bournemouth())
        assert f.possession_for == 62.0
        assert f.possession_against == 38.0
        assert f.possession_delta == pytest.approx(24.0)

    def test_shots_parsed(self):
        f = FeatureExtractor().extract(_arsenal_3_2_bournemouth())
        assert f.shots_for == 18
        assert f.shots_against == 11
        assert f.shot_delta == 7

    def test_shots_on_target_parsed(self):
        f = FeatureExtractor().extract(_arsenal_3_2_bournemouth())
        assert f.shots_on_target_for == 7
        assert f.shots_on_target_against == 4
        assert f.shot_on_target_delta == 3

    def test_corners_parsed(self):
        f = FeatureExtractor().extract(_arsenal_3_2_bournemouth())
        assert f.corners_for == 9
        assert f.corners_against == 3
        assert f.corner_delta == 6

    def test_fouls_parsed(self):
        f = FeatureExtractor().extract(_arsenal_3_2_bournemouth())
        assert f.fouls_for == 10
        assert f.fouls_against == 14

    def test_pass_accuracy_parsed(self):
        f = FeatureExtractor().extract(_arsenal_3_2_bournemouth())
        assert f.pass_accuracy_for == pytest.approx(88.0)
        assert f.pass_accuracy_against == pytest.approx(76.0)
        assert f.pass_accuracy_delta == pytest.approx(12.0)

    def test_xg_parsed_when_present(self):
        f = FeatureExtractor().extract(_arsenal_3_2_with_xg())
        assert f.xg_for == pytest.approx(2.4)
        assert f.xg_against == pytest.approx(1.1)
        assert f.xg_delta == pytest.approx(1.3)

    def test_cards_from_events(self):
        f = FeatureExtractor().extract(_arsenal_3_2_bournemouth())
        # Arsenal has 0 cards; opponent has 1 yellow
        assert f.yellow_cards_for == 0
        assert f.red_cards_for == 0


class TestFeatureExtractorMissingData:
    """missing_data population — the primary quality gate."""

    def test_missing_xg_when_not_provided(self):
        f = FeatureExtractor().extract(_arsenal_3_2_bournemouth())
        assert "xG" in f.missing_data

    def test_xg_present_not_in_missing(self):
        f = FeatureExtractor().extract(_arsenal_3_2_with_xg())
        assert "xG" not in f.missing_data

    def test_pressing_always_missing(self):
        """Pressing data is not available from current sources."""
        f = FeatureExtractor().extract(_arsenal_3_2_bournemouth())
        assert "pressing" in f.missing_data
        assert "pressing_recoveries" in f.missing_data

    def test_transition_always_missing(self):
        """Transition data is not available from current sources."""
        f = FeatureExtractor().extract(_arsenal_3_2_with_xg())
        assert "transition" in f.missing_data

    def test_missing_data_sorted_unique(self):
        """missing_data must be sorted and deduplicated."""
        f = FeatureExtractor().extract(_empty_match())
        assert f.missing_data == sorted(set(f.missing_data))

    def test_empty_match_has_many_missing(self):
        """Match with no stats should flag many missing fields."""
        f = FeatureExtractor().extract(_empty_match())
        assert "xG" in f.missing_data
        assert "possession" in f.missing_data
        assert "shots" in f.missing_data
        assert "pressing" in f.missing_data

    def test_comprehensive_match_missing_data_reasonable(self):
        """Complete match (with xG) should have few missing fields."""
        f = FeatureExtractor().extract(_arsenal_3_2_with_xg())
        # Only data types unavailable from current sources
        expected_missing = {"pressing", "pressing_recoveries", "transition"}
        assert set(f.missing_data) == expected_missing


class TestFeatureExtractorDeterminism:
    """Deterministic: same input twice → same output."""

    def test_deterministic_output(self):
        m = _arsenal_3_2_bournemouth()
        ext = FeatureExtractor()
        f1 = ext.extract(m)
        f2 = ext.extract(m)

        d1 = f1.to_dict()
        d2 = f2.to_dict()
        assert d1 == d2

    def test_deterministic_with_xg(self):
        m = _arsenal_3_2_with_xg()
        ext = FeatureExtractor()
        f1 = ext.extract(m)
        f2 = ext.extract(m)
        assert f1.to_dict() == f2.to_dict()

    def test_deterministic_score_timeline(self):
        m = _arsenal_3_2_bournemouth()
        ext = FeatureExtractor()
        f1 = ext.extract(m)
        f2 = ext.extract(m)
        assert f1.score_state_timeline == f2.score_state_timeline


class TestFeatureExtractorScoreTimeline:
    """Score state timeline from goal events."""

    def test_timeline_starts_at_zero(self):
        f = FeatureExtractor().extract(_arsenal_3_2_bournemouth())
        assert len(f.score_state_timeline) > 0
        assert f.score_state_timeline[0] == {"minute": 0, "arsenal_score": 0, "opponent_score": 0}

    def test_timeline_tracks_all_goals(self):
        f = FeatureExtractor().extract(_arsenal_3_2_bournemouth())
        # 5 goals total → 6 entries (including 0-0)
        assert len(f.score_state_timeline) == 6

    def test_timeline_final_state_matches_score(self):
        f = FeatureExtractor().extract(_arsenal_3_2_bournemouth())
        last = f.score_state_timeline[-1]
        assert last["arsenal_score"] == 3
        assert last["opponent_score"] == 2

    def test_timeline_sorted_by_minute(self):
        f = FeatureExtractor().extract(_arsenal_3_2_bournemouth())
        minutes = [s["minute"] for s in f.score_state_timeline]
        assert minutes == sorted(minutes)

    def test_no_goals_empty_timeline(self):
        m = _empty_match()
        f = FeatureExtractor().extract(m)
        assert f.score_state_timeline == []


class TestFeatureExtractorSubstitutionWindows:
    """Substitution windows from subst events."""

    def test_substitution_windows_populated(self):
        f = FeatureExtractor().extract(_arsenal_3_2_bournemouth())
        assert len(f.substitution_windows) == 2
        assert f.substitution_windows[0]["player"] == "Nketiah"
        assert f.substitution_windows[0]["minute"] == 65
        assert f.substitution_windows[1]["player"] == "Havertz"
        assert f.substitution_windows[1]["minute"] == 70

    def test_substitution_scored_after(self):
        f = FeatureExtractor().extract(_arsenal_3_2_bournemouth())
        nketiah = f.substitution_windows[0]
        havertz = f.substitution_windows[1]
        assert nketiah["scored_after"] is True
        assert havertz["scored_after"] is True

    def test_arsenal_sub_count(self):
        f = FeatureExtractor().extract(_arsenal_3_2_bournemouth())
        assert f.arsenal_sub_count == 2

    def test_goals_after_arsenal_subs(self):
        """Nketiah (80') and Havertz (85') both scored after first sub at 65'."""
        f = FeatureExtractor().extract(_arsenal_3_2_bournemouth())
        assert f.goals_after_arsenal_subs == 2

    def test_no_subs_empty_windows(self):
        m = _empty_match()
        f = FeatureExtractor().extract(m)
        assert f.substitution_windows == []
        assert f.arsenal_sub_count == 0
        assert f.goals_after_arsenal_subs == 0

    def test_windows_sorted_by_minute(self):
        """Even if events come in different order, windows are sorted."""
        m = _arsenal_3_2_bournemouth()
        # Reverse the events order
        m["events"] = list(reversed(m["events"]))
        f = FeatureExtractor().extract(m)
        minutes = [w["minute"] for w in f.substitution_windows]
        assert minutes == sorted(minutes)


class TestFeatureExtractorSetPieceGoals:
    """Set piece goal detection from event details."""

    def test_penalty_detected(self):
        f = FeatureExtractor().extract(_arsenal_win_with_set_pieces())
        assert f.set_piece_goals_for == 2  # penalty + header from corner
        assert f.set_piece_goals_against == 0

    def test_corner_goal_detected(self):
        m = _arsenal_win_with_set_pieces()
        f = FeatureExtractor().extract(m)
        # Both goals are set pieces
        assert f.set_piece_goals_for == 2

    def test_no_set_pieces_in_normal_goals(self):
        f = FeatureExtractor().extract(_arsenal_3_2_bournemouth())
        # All goals are "Normal Goal" — no set pieces
        assert f.set_piece_goals_for == 0
        assert f.set_piece_goals_against == 0

    def test_opponent_set_piece_goal(self):
        m = _arsenal_win_with_set_pieces()
        m["events"].append(
            {"minute": 88, "type": "Goal", "team": "away", "player": "Tarkowski",
             "detail": "Header from corner"}
        )
        m["away_score"] = 1
        f = FeatureExtractor().extract(m)
        assert f.set_piece_goals_against == 1


class TestFeatureExtractorPredictedPlan:
    """Predicted plan match features extraction."""

    def test_predicted_plan_populated(self):
        f = FeatureExtractor().extract(_arsenal_3_2_bournemouth())
        pp = f.predicted_plan_match_features
        assert pp["opponent_quality"] == "mid_table"
        assert pp["venue"] == "home"
        assert pp["competition_stage"] == "league_late"
        assert pp["opponent"] == "Bournemouth"

    def test_predicted_plan_away_top6(self):
        f = FeatureExtractor().extract(_arsenal_away_draw())
        pp = f.predicted_plan_match_features
        assert pp["opponent_quality"] == "top6"
        assert pp["venue"] == "away"
        assert pp["opponent"] == "Man City"


class TestFeatureExtractorGoalsConceded:
    """Goals conceded = opponent goals."""

    def test_goals_conceded_matches_opponent_score(self):
        f = FeatureExtractor().extract(_arsenal_3_2_bournemouth())
        assert f.goals_conceded == 2

    def test_clean_sheet(self):
        f = FeatureExtractor().extract(_arsenal_win_with_set_pieces())
        assert f.goals_conceded == 0


class TestFeatureExtractorAutoGreenBlock:
    """3-2 Bournemouth must NOT auto-green: xG absent → missing_data flags it."""

    def test_3_2_bournemouth_not_auto_green(self):
        """xG absence appears in missing_data; match is not fully evaluable."""
        f = FeatureExtractor().extract(_arsenal_3_2_bournemouth())
        assert "xG" in f.missing_data
        assert f.xg_for is None
        assert f.xg_against is None
        assert f.xg_delta is None

    def test_3_2_bournemouth_with_xg_still_has_gaps(self):
        """Even with xG, pressing/transition data is still missing."""
        f = FeatureExtractor().extract(_arsenal_3_2_with_xg())
        assert "pressing" in f.missing_data
        assert "transition" in f.missing_data


class TestFeatureExtractorCompetitionStage:
    """Competition stage detection."""

    def test_premier_league_late_season(self):
        """May (month 5) → league_late."""
        f = FeatureExtractor().extract(_arsenal_3_2_bournemouth())
        assert f.competition_stage == "league_late"

    def test_premier_league_early_season(self):
        m = _arsenal_win_with_set_pieces()
        m["date"] = "2025-09-15T15:00:00"
        f = FeatureExtractor().extract(m)
        assert f.competition_stage == "league_early"
