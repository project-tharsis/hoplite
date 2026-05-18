"""Tests for event normalization and extract functions (Phase 1 refactor)."""
from __future__ import annotations

import pytest

from src.tools.extract import (
    normalize_event_type,
    extract_match_stats,
    extract_key_events,
    extract_sub_impact,
    extract_set_piece_goals,
)


# ── normalize_event_type ──────────────────────────────────────────────

class TestNormalizeEventType:
    """Canonical mapping from raw source types."""

    def test_subst_maps_to_substitution(self):
        assert normalize_event_type("subst") == "substitution"

    def test_substitution_passthrough(self):
        assert normalize_event_type("substitution") == "substitution"

    def test_goal_lowercase(self):
        assert normalize_event_type("goal") == "goal"

    def test_goal_titlecase(self):
        assert normalize_event_type("Goal") == "goal"

    def test_card_lowercase(self):
        assert normalize_event_type("card") == "card"

    def test_card_titlecase(self):
        assert normalize_event_type("Card") == "card"

    def test_unknown_type_maps_to_other(self):
        assert normalize_event_type("Var") == "other"
        assert normalize_event_type("injury") == "other"
        assert normalize_event_type("") == "other"
        assert normalize_event_type("something_new") == "other"

    def test_whitespace_not_normalized(self):
        """Whitespace-padded types should map to 'other' (not silently matched)."""
        assert normalize_event_type(" goal ") == "other"


# ── extract_key_events: normalized type + raw_type ────────────────────

class TestExtractKeyEventsNormalization:
    """extract_key_events should output canonical types and preserve raw."""

    MATCH_JSON = {
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "events": [
            {"minute": 12, "type": "Goal", "team": "home", "player": "Saka", "detail": "Normal Goal"},
            {"minute": 55, "type": "Card", "team": "away", "player": "Caicedo", "detail": "Yellow Card"},
            {"minute": 70, "type": "subst", "team": "home", "player": "Nketiah", "detail": "substitution"},
        ],
    }

    def test_goal_normalized(self):
        events = extract_key_events(self.MATCH_JSON)
        goal = events[0]
        assert goal["type"] == "goal"
        assert goal["raw_type"] == "Goal"

    def test_card_normalized(self):
        events = extract_key_events(self.MATCH_JSON)
        card = events[1]
        assert card["type"] == "card"
        assert card["raw_type"] == "Card"

    def test_subst_normalized(self):
        events = extract_key_events(self.MATCH_JSON)
        sub = events[2]
        assert sub["type"] == "substitution"
        assert sub["raw_type"] == "subst"


# ── extract_match_stats with raw event types ──────────────────────────

class TestExtractMatchStatsNormalization:
    """Goal/Card counts should work with API-Football raw types (Goal, Card)."""

    MATCH_JSON = {
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "home_score": 2,
        "away_score": 1,
        "events": [
            {"minute": 12, "type": "Goal", "team": "home", "player": "Saka"},
            {"minute": 55, "type": "Card", "team": "away", "player": "Caicedo", "detail": "Yellow Card"},
            {"minute": 80, "type": "Goal", "team": "away", "player": "Palmer"},
            {"minute": 90, "type": "Card", "team": "home", "player": "Rice", "detail": "Red Card"},
        ],
    }

    def test_goal_count_with_titlecase(self):
        stats = extract_match_stats(self.MATCH_JSON)
        assert stats["goals"]["arsenal"]["total"] == 1
        assert stats["goals"]["opponent"]["total"] == 1

    def test_card_count_with_titlecase(self):
        stats = extract_match_stats(self.MATCH_JSON)
        assert stats["cards"]["opponent"]["yellow"] == 1
        assert stats["cards"]["arsenal"]["red"] == 1


# ── extract_sub_impact: subst bug fix ────────────────────────────────

class TestExtractSubImpactSubstBug:
    """The core bug: API-Football uses 'subst', not 'substitution'."""

    def test_subst_recognized_as_substitution(self):
        """Events with type='subst' must be extracted as substitutions."""
        events = [
            {"minute": 70, "type": "subst", "player": "Nketiah", "detail": "", "is_arsenal": True},
            {"minute": 90, "type": "Goal", "player": "Nketiah", "detail": "", "is_arsenal": True},
        ]
        subs = extract_sub_impact(events)
        assert len(subs) == 1
        assert subs[0]["player"] == "Nketiah"
        assert subs[0]["minute"] == 70
        assert subs[0]["scored_after"] is True

    def test_substitution_still_recognized(self):
        """Backward compat: canonical 'substitution' type still works."""
        events = [
            {"minute": 70, "type": "substitution", "player": "Nketiah", "detail": "", "is_arsenal": True},
        ]
        subs = extract_sub_impact(events)
        assert len(subs) == 1
        assert subs[0]["player"] == "Nketiah"

    def test_sub_did_not_score(self):
        """Subbed-on player who didn't score gets scored_after=False."""
        events = [
            {"minute": 70, "type": "subst", "player": "Nketiah", "detail": "", "is_arsenal": True},
            {"minute": 60, "type": "goal", "player": "Saka", "detail": "", "is_arsenal": True},
        ]
        subs = extract_sub_impact(events)
        assert len(subs) == 1
        assert subs[0]["scored_after"] is False

    def test_no_subs_returns_empty(self):
        """Matches with no substitution events return empty list."""
        events = [
            {"minute": 12, "type": "goal", "player": "Saka", "detail": "", "is_arsenal": True},
        ]
        subs = extract_sub_impact(events)
        assert subs == []

    def test_already_normalized_events(self):
        """Events from extract_key_events (type='substitution') still work."""
        events = [
            {"minute": 70, "type": "substitution", "player": "Nketiah", "detail": "", "is_arsenal": True},
            {"minute": 85, "type": "goal", "player": "Nketiah", "detail": "", "is_arsenal": True},
        ]
        subs = extract_sub_impact(events)
        assert len(subs) == 1
        assert subs[0]["scored_after"] is True


# ── End-to-end: full pipeline with API-Football raw types ────────────

class TestEndToEndNormalization:
    """Full pipeline: raw API-Football types → analyze_match → non-empty sub_impact."""

    def test_analyze_match_subst_pipeline(self):
        """Arsenal 3-2 Bournemouth-style match with 'subst' events."""
        from src.tools.analyze import analyze_match
        match_json = {
            "fixture_id": 12345,
            "date": "2025-05-01T15:00:00",
            "competition": "Premier League",
            "home_team": "Arsenal",
            "away_team": "Bournemouth",
            "home_score": 3,
            "away_score": 2,
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
        result = analyze_match(match_json)
        assert result["ok"] is True
        report = result["report"]

        # sub_impact should be non-empty (the bug fix!)
        subs = report["sub_impact"]
        assert len(subs) == 2
        # Nketiah scored after being subbed on
        nketiah = [s for s in subs if s["player"] == "Nketiah"][0]
        assert nketiah["scored_after"] is True
        # Havertz scored after being subbed on
        havertz = [s for s in subs if s["player"] == "Havertz"][0]
        assert havertz["scored_after"] is True

    def test_analyze_match_goal_card_counts(self):
        """Goal/Card counts work with API-Football raw types."""
        from src.tools.analyze import analyze_match
        match_json = {
            "fixture_id": 12345,
            "date": "2025-05-01T15:00:00",
            "competition": "Premier League",
            "home_team": "Arsenal",
            "away_team": "Chelsea",
            "home_score": 2,
            "away_score": 0,
            "events": [
                {"minute": 23, "type": "Goal", "team": "home", "player": "Saka", "detail": "Normal Goal"},
                {"minute": 55, "type": "Card", "team": "away", "player": "Caicedo", "detail": "Yellow Card"},
                {"minute": 78, "type": "Goal", "team": "home", "player": "Rice", "detail": "Normal Goal"},
            ],
        }
        result = analyze_match(match_json)
        stats = result["report"]["stats"]
        assert stats["goals"]["arsenal"]["total"] == 2
        assert stats["cards"]["opponent"]["yellow"] == 1
