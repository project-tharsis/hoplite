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


# ── v2 Fixtures ──────────────────────────────────────────────────────


def _arsenal_comeback_from_behind() -> dict:
    """Arsenal 3-2 comeback: opponent scores first, Arsenal equalizes, leads, opponent equalizes, Arsenal wins late."""
    return {
        "fixture_id": 77777,
        "date": "2025-04-15T20:00:00",
        "competition": "Premier League",
        "home_team": "Arsenal",
        "away_team": "Liverpool",
        "home_score": 3,
        "away_score": 2,
        "home_xg": 2.8,
        "away_xg": 1.5,
        "home_stats": {
            "Ball Possession": "55%",
            "Total Shots": 16,
            "Shots on Goal": 8,
            "Passes %": "87%",
            "Corner Kicks": 6,
            "Fouls": 12,
        },
        "away_stats": {
            "Ball Possession": "45%",
            "Total Shots": 12,
            "Shots on Goal": 5,
            "Passes %": "82%",
            "Corner Kicks": 4,
            "Fouls": 10,
        },
        "events": [
            {"minute": 10, "type": "Goal", "team": "away", "player": "Salah", "detail": "Normal Goal"},  # 0-1
            {"minute": 25, "type": "Goal", "team": "home", "player": "Saka", "detail": "Normal Goal"},    # 1-1
            {"minute": 55, "type": "Goal", "team": "away", "player": "Díaz", "detail": "Normal Goal"},    # 1-2
            {"minute": 70, "type": "Goal", "team": "home", "player": "Havertz", "detail": "Normal Goal"}, # 2-2
            {"minute": 85, "type": "Goal", "team": "home", "player": "Rice", "detail": "Normal Goal"},    # 3-2
        ],
    }


def _arsenal_protects_early_lead() -> dict:
    """Arsenal 1-0: scores early, protects lead."""
    return {
        "fixture_id": 66666,
        "date": "2025-02-10T15:00:00",
        "competition": "Premier League",
        "home_team": "Arsenal",
        "away_team": "Burnley",
        "home_score": 1,
        "away_score": 0,
        "home_xg": 1.2,
        "away_xg": 0.4,
        "home_stats": {
            "Ball Possession": "70%",
            "Total Shots": 14,
            "Shots on Goal": 4,
            "Passes %": "91%",
            "Corner Kicks": 8,
            "Fouls": 6,
        },
        "away_stats": {
            "Ball Possession": "30%",
            "Total Shots": 4,
            "Shots on Goal": 1,
            "Passes %": "70%",
            "Corner Kicks": 1,
            "Fouls": 14,
        },
        "events": [
            {"minute": 15, "type": "Goal", "team": "home", "player": "Saka", "detail": "Normal Goal"},
        ],
    }


def _arsenal_late_lead_lost() -> dict:
    """Arsenal 1-1: scores early, opponent equalizes after 75'."""
    return {
        "fixture_id": 55555,
        "date": "2025-03-01T15:00:00",
        "competition": "Premier League",
        "home_team": "Arsenal",
        "away_team": "Tottenham",
        "home_score": 1,
        "away_score": 1,
        "home_xg": 1.5,
        "away_xg": 0.8,
        "home_stats": {
            "Ball Possession": "58%",
            "Total Shots": 12,
            "Shots on Goal": 4,
            "Passes %": "88%",
            "Corner Kicks": 5,
            "Fouls": 10,
        },
        "away_stats": {
            "Ball Possession": "42%",
            "Total Shots": 8,
            "Shots on Goal": 3,
            "Passes %": "83%",
            "Corner Kicks": 3,
            "Fouls": 12,
        },
        "events": [
            {"minute": 20, "type": "Goal", "team": "home", "player": "Saliba", "detail": "Normal Goal"},
            {"minute": 82, "type": "Goal", "team": "away", "player": "Son", "detail": "Normal Goal"},
        ],
    }


def _arsenal_dominant_xg_no_win() -> dict:
    """Arsenal 0-0 draw but dominant xG (2.1 vs 0.3)."""
    return {
        "fixture_id": 44444,
        "date": "2025-01-20T15:00:00",
        "competition": "Premier League",
        "home_team": "Arsenal",
        "away_team": "Newcastle",
        "home_score": 0,
        "away_score": 0,
        "home_xg": 2.1,
        "away_xg": 0.3,
        "home_stats": {
            "Ball Possession": "68%",
            "Total Shots": 20,
            "Shots on Goal": 6,
            "Passes %": "92%",
            "Corner Kicks": 10,
            "Fouls": 7,
        },
        "away_stats": {
            "Ball Possession": "32%",
            "Total Shots": 4,
            "Shots on Goal": 1,
            "Passes %": "75%",
            "Corner Kicks": 2,
            "Fouls": 15,
        },
        "events": [],
    }


def _arsenal_won_without_xg_edge() -> dict:
    """Arsenal 1-0 win despite lower xG (0.5 vs 0.9)."""
    return {
        "fixture_id": 33333,
        "date": "2025-02-28T15:00:00",
        "competition": "Premier League",
        "home_team": "Wolves",
        "away_team": "Arsenal",
        "home_score": 0,
        "away_score": 1,
        "home_xg": 0.9,
        "away_xg": 0.5,
        "home_stats": {
            "Ball Possession": "52%",
            "Total Shots": 10,
            "Shots on Goal": 2,
            "Passes %": "84%",
            "Corner Kicks": 4,
            "Fouls": 11,
        },
        "away_stats": {
            "Ball Possession": "48%",
            "Total Shots": 7,
            "Shots on Goal": 2,
            "Passes %": "82%",
            "Corner Kicks": 3,
            "Fouls": 9,
        },
        "events": [
            {"minute": 78, "type": "Goal", "team": "away", "player": "Saka", "detail": "Normal Goal"},
        ],
    }


def _arsenal_sub_while_trailing() -> dict:
    """Arsenal subs while trailing 0-1, then equalizes."""
    return {
        "fixture_id": 22222,
        "date": "2025-03-20T20:00:00",
        "competition": "Premier League",
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "home_score": 1,
        "away_score": 1,
        "home_xg": 1.3,
        "away_xg": 0.6,
        "home_stats": {
            "Ball Possession": "60%",
            "Total Shots": 13,
            "Shots on Goal": 5,
            "Passes %": "89%",
            "Corner Kicks": 7,
            "Fouls": 8,
        },
        "away_stats": {
            "Ball Possession": "40%",
            "Total Shots": 6,
            "Shots on Goal": 2,
            "Passes %": "80%",
            "Corner Kicks": 2,
            "Fouls": 13,
        },
        "events": [
            {"minute": 30, "type": "Goal", "team": "away", "player": "Palmer", "detail": "Normal Goal"},
            {"minute": 60, "type": "subst", "team": "home", "player": "Martinelli", "detail": "Tactical"},
            {"minute": 75, "type": "Goal", "team": "home", "player": "Martinelli", "detail": "Normal Goal"},
        ],
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

    def test_v2_fields_in_to_dict(self):
        """v2 fields should be present in to_dict output."""
        d = MatchFeatures().to_dict()
        assert "match_duration_minutes" in d
        assert "arsenal_goal_minutes" in d
        assert "first_goal_minute" in d
        assert "max_lead" in d
        assert "xg_overperformance_for" in d
        assert "first_sub_score_state" in d
        assert "opponent_xg_per_shot" in d


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


# ── v2 Tests ──────────────────────────────────────────────────────────


class TestV2GoalTiming:
    """Goal timing and score state features."""

    def test_scored_first(self):
        """Arsenal scored first in 3-2 Bournemouth (Saka 12')."""
        f = FeatureExtractor().extract(_arsenal_3_2_bournemouth())
        assert f.arsenal_scored_first is True
        assert f.arsenal_conceded_first is False
        assert f.first_goal_team == "arsenal"
        assert f.first_goal_minute == 12

    def test_conceded_first(self):
        """Arsenal conceded first in comeback match (Salah 10')."""
        f = FeatureExtractor().extract(_arsenal_comeback_from_behind())
        assert f.arsenal_scored_first is False
        assert f.arsenal_conceded_first is True
        assert f.first_goal_team == "opponent"
        assert f.first_goal_minute == 10

    def test_no_goals(self):
        """No goals → no first goal info."""
        f = FeatureExtractor().extract(_empty_match())
        assert f.first_goal_team is None
        assert f.first_goal_minute is None
        assert f.arsenal_scored_first is None
        assert f.arsenal_conceded_first is None

    def test_goal_minutes_tracked(self):
        """Goal minutes should be tracked separately."""
        f = FeatureExtractor().extract(_arsenal_3_2_bournemouth())
        assert f.arsenal_goal_minutes == [12, 80, 85]
        assert f.opponent_goal_minutes == [45, 90]

    def test_comeback_from_behind(self):
        """Comeback: trailed, then led, then won."""
        f = FeatureExtractor().extract(_arsenal_comeback_from_behind())
        assert f.arsenal_led_at_any_point is True
        assert f.arsenal_trailed_at_any_point is True
        assert f.lead_change_count >= 2  # 0-1→1-1, 1-2→2-2, 2-2→3-2

    def test_minutes_leading_trailing(self):
        """Time spent in each state for 3-2 Bournemouth."""
        f = FeatureExtractor().extract(_arsenal_3_2_bournemouth())
        # Timeline: 0-0(0-12), 1-0(12-45), 1-1(45-80), 2-1(80-85), 3-1(85-90), 3-2(90-90)
        # Leading: 1-0: 12-45=33, 2-1: 80-85=5, 3-1: 85-90=5 = 43
        assert f.minutes_leading == 43
        assert f.minutes_trailing == 0  # Arsenal never trailed
        # Level: 0-0: 0-12=12, 1-1: 45-80=35 = 47
        assert f.minutes_level == 47

    def test_goals_after_75(self):
        """Goals after 75th minute."""
        f = FeatureExtractor().extract(_arsenal_3_2_bournemouth())
        assert f.goals_for_after_75 == 2  # Nketiah 80', Havertz 85'
        assert f.goals_against_after_75 == 1  # Tavernier 90'


class TestV2LeadProtection:
    """Lead protection features."""

    def test_protected_lead(self):
        """Arsenal 1-0 Burnley: lead protected."""
        f = FeatureExtractor().extract(_arsenal_protects_early_lead())
        assert f.final_state_from_first_lead == "protected"
        assert f.lead_lost_count == 0
        assert f.max_lead == 1
        assert f.first_lead_minute == 15
        assert f.last_lead_minute == 15

    def test_lost_lead(self):
        """Arsenal 1-1 Tottenham: early lead lost late."""
        f = FeatureExtractor().extract(_arsenal_late_lead_lost())
        assert f.final_state_from_first_lead == "lost"
        assert f.lead_lost_count == 1
        assert f.late_lead_lost is True
        assert f.late_goals_conceded_while_leading == 1

    def test_never_led(self):
        """Arsenal 0-0: never led."""
        f = FeatureExtractor().extract(_empty_match())
        assert f.final_state_from_first_lead == "never_led"
        assert f.lead_lost_count == 0
        assert f.max_lead == 0

    def test_max_deficit(self):
        """Comeback match: max deficit should be 1."""
        f = FeatureExtractor().extract(_arsenal_comeback_from_behind())
        assert f.max_deficit == 1
        assert f.max_lead == 1

    def test_goals_conceded_while_leading(self):
        """3-2 Bournemouth: Arsenal conceded 2 goals while leading (45' and 90')."""
        f = FeatureExtractor().extract(_arsenal_3_2_bournemouth())
        assert f.goals_conceded_while_leading == 2

    def test_led_after_75(self):
        """3-2 Bournemouth: Arsenal led after 75' (80', 85' goals)."""
        f = FeatureExtractor().extract(_arsenal_3_2_bournemouth())
        assert f.led_after_75 is True

    def test_late_lead_protected(self):
        """1-0 Burnley: late lead protected (led after 75', not lost)."""
        f = FeatureExtractor().extract(_arsenal_protects_early_lead())
        assert f.led_after_75 is True
        assert f.late_lead_protected is True


class TestV2xGConversion:
    """xG conversion features."""

    def test_xg_overperformance(self):
        """Arsenal 3-2 with xG 2.4 vs 1.1: overperformed."""
        f = FeatureExtractor().extract(_arsenal_3_2_with_xg())
        assert f.xg_overperformance_for == pytest.approx(0.6, abs=0.01)
        assert f.xg_overperformance_against == pytest.approx(0.9, abs=0.01)

    def test_xg_result_gap(self):
        """Score margin 1, xG delta 1.3 → result gap -0.3."""
        f = FeatureExtractor().extract(_arsenal_3_2_with_xg())
        expected_gap = f.score_margin - (f.xg_for - f.xg_against)
        assert f.xg_result_gap == pytest.approx(expected_gap, abs=0.01)

    def test_dominant_xg_no_win(self):
        """Arsenal 0-0 but xG 2.1 vs 0.3: dominant but no win."""
        f = FeatureExtractor().extract(_arsenal_dominant_xg_no_win())
        assert f.dominant_xg_no_win is True
        assert f.won_without_xg_edge is False

    def test_won_without_xg_edge(self):
        """Arsenal 1-0 but xG 0.5 vs 0.9: won without xG edge."""
        f = FeatureExtractor().extract(_arsenal_won_without_xg_edge())
        assert f.won_without_xg_edge is True
        assert f.dominant_xg_no_win is False

    def test_missing_xg(self):
        """No xG → Optional fields None, bool fields False."""
        f = FeatureExtractor().extract(_arsenal_3_2_bournemouth())
        assert f.xg_overperformance_for is None
        assert f.xg_overperformance_against is None
        assert f.xg_result_gap is None
        assert f.dominant_xg_no_win is False
        assert f.won_without_xg_edge is False


class TestV2SubstitutionScoreState:
    """Substitution score state features."""

    def test_subbed_while_leading(self):
        """3-2 Bournemouth: Arsenal level 1-1 when Nketiah comes on (65')."""
        f = FeatureExtractor().extract(_arsenal_3_2_bournemouth())
        assert f.first_sub_minute == 65
        assert f.first_sub_score_state == "level"
        assert f.subbed_while_level is True
        assert f.subbed_while_leading is False
        assert f.subbed_while_trailing is False

    def test_subbed_while_trailing(self):
        """Arsenal subbed while trailing 0-1 vs Chelsea."""
        f = FeatureExtractor().extract(_arsenal_sub_while_trailing())
        assert f.first_sub_minute == 60
        assert f.first_sub_score_state == "trailing"
        assert f.subbed_while_trailing is True
        assert f.subbed_while_leading is False

    def test_subbed_while_level(self):
        """Arsenal subbed while level in a 0-0 match."""
        m = _empty_match()
        m["events"] = [
            {"minute": 60, "type": "subst", "team": "home", "player": "Nketiah", "detail": "Tactical"},
        ]
        f = FeatureExtractor().extract(m)
        # No goals, so score_state_timeline is empty → state is None
        assert f.first_sub_score_state is None

    def test_no_subs(self):
        """No subs → None/False/0 defaults."""
        f = FeatureExtractor().extract(_empty_match())
        assert f.first_sub_minute is None
        assert f.first_sub_score_margin is None
        assert f.first_sub_score_state is None
        assert f.subbed_while_leading is False
        assert f.subbed_while_level is False
        assert f.subbed_while_trailing is False
        assert f.goals_for_after_first_sub == 0
        assert f.goals_against_after_first_sub == 0
        assert f.net_goals_after_first_sub == 0

    def test_net_goals_after_first_sub(self):
        """3-2 Bournemouth: first sub at 65', Arsenal scored 2, conceded 1 after."""
        f = FeatureExtractor().extract(_arsenal_3_2_bournemouth())
        assert f.goals_for_after_first_sub == 2
        assert f.goals_against_after_first_sub == 1
        assert f.net_goals_after_first_sub == 1

    def test_substitution_windows_extended(self):
        """Windows should have score state info."""
        f = FeatureExtractor().extract(_arsenal_3_2_bournemouth())
        w = f.substitution_windows[0]
        assert "score_margin_at_sub" in w
        assert "score_state_at_sub" in w
        assert "goals_for_after_sub" in w
        assert "goals_against_after_sub" in w
        assert "net_goals_after_sub" in w


class TestV2OpponentShotQuality:
    """Opponent shot quality features."""

    def test_xg_per_shot(self):
        """xG per shot calculation."""
        f = FeatureExtractor().extract(_arsenal_3_2_with_xg())
        # Arsenal: 2.4 xG / 18 shots = 0.133
        assert f.arsenal_xg_per_shot == pytest.approx(2.4 / 18, abs=0.01)
        # Opponent: 1.1 xG / 11 shots = 0.1
        assert f.opponent_xg_per_shot == pytest.approx(1.1 / 11, abs=0.01)

    def test_xg_per_shot_on_target(self):
        """xG per shot on target calculation."""
        f = FeatureExtractor().extract(_arsenal_3_2_with_xg())
        # Arsenal: 2.4 / 7 = 0.343
        assert f.arsenal_xg_per_shot_on_target == pytest.approx(2.4 / 7, abs=0.01)
        # Opponent: 1.1 / 4 = 0.275
        assert f.opponent_xg_per_shot_on_target == pytest.approx(1.1 / 4, abs=0.01)

    def test_opponent_high_quality_chances(self):
        """Opponent xG/shot > 0.12 → high quality."""
        # Burnley: 0.4 xG / 4 shots = 0.1 per shot — not high quality
        f = FeatureExtractor().extract(_arsenal_protects_early_lead())
        assert f.opponent_high_quality_chances is False

    def test_opponent_high_quality_chances_true(self):
        """Liverpool: 1.5 xG / 12 shots = 0.125 — high quality."""
        f = FeatureExtractor().extract(_arsenal_comeback_from_behind())
        assert f.opponent_xg_per_shot == pytest.approx(1.5 / 12, abs=0.01)
        assert f.opponent_high_quality_chances is True

    def test_opponent_low_volume_high_quality(self):
        """Few shots but high quality → low_volume_high_quality."""
        # Create match where opponent has few shots but high xG/shot
        m = _arsenal_protects_early_lead()
        m["away_xg"] = 1.0  # 1.0 / 4 = 0.25 > 0.12, 4 <= 8
        f = FeatureExtractor().extract(m)
        assert f.opponent_low_volume_high_quality is True

    def test_missing_xg_shot_quality(self):
        """No xG → shot quality fields None/False."""
        f = FeatureExtractor().extract(_arsenal_3_2_bournemouth())
        assert f.arsenal_xg_per_shot is None
        assert f.opponent_xg_per_shot is None
        assert f.arsenal_xg_per_shot_on_target is None
        assert f.opponent_xg_per_shot_on_target is None
        assert f.opponent_high_quality_chances is False
        assert f.opponent_low_volume_high_quality is False


class TestV2MissingDataHandling:
    """v2 missing data rules."""

    def test_goal_events_missing_when_non_zero_score_no_events(self):
        """Non-0-0 score but no goal events → goal_events in missing_data."""
        m = _empty_match()
        m["home_score"] = 1
        m["away_score"] = 0
        f = FeatureExtractor().extract(m)
        assert "goal_events" in f.missing_data

    def test_goal_events_not_missing_when_events_present(self):
        """Goal events present → goal_events not in missing_data."""
        f = FeatureExtractor().extract(_arsenal_3_2_bournemouth())
        assert "goal_events" not in f.missing_data

    def test_goal_events_not_missing_for_0_0(self):
        """0-0 with no events → goal_events not in missing_data."""
        f = FeatureExtractor().extract(_empty_match())
        assert "goal_events" not in f.missing_data


class TestV2Determinism:
    """v2 features must be deterministic."""

    def test_deterministic_v2_fields(self):
        m = _arsenal_3_2_bournemouth()
        ext = FeatureExtractor()
        f1 = ext.extract(m)
        f2 = ext.extract(m)
        d1 = f1.to_dict()
        d2 = f2.to_dict()
        assert d1 == d2

    def test_deterministic_comeback(self):
        m = _arsenal_comeback_from_behind()
        ext = FeatureExtractor()
        f1 = ext.extract(m)
        f2 = ext.extract(m)
        assert f1.to_dict() == f2.to_dict()

    def test_deterministic_with_xg(self):
        m = _arsenal_3_2_with_xg()
        ext = FeatureExtractor()
        f1 = ext.extract(m)
        f2 = ext.extract(m)
        assert f1.to_dict() == f2.to_dict()
