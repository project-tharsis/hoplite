from datetime import datetime
from src.models.match import Match


def normalize_football_data_match(raw: dict) -> Match:
    """Convert football-data.org raw match to Match object."""
    return Match(
        fixture_id=raw["id"],
        date=datetime.fromisoformat(raw["utcDate"].replace("Z", "+00:00")),
        competition=raw["competition"]["name"],
        home_team=raw["homeTeam"]["name"],
        away_team=raw["awayTeam"]["name"],
        home_score=raw["score"]["fullTime"]["home"] or 0,
        away_score=raw["score"]["fullTime"]["away"] or 0,
    )


def merge_match_data(match: Match, understat_data: dict = None) -> None:
    """Merge supplementary data into an existing Match object. Modifies in place."""
    if understat_data:
        match.home_xg = understat_data["home_xg"]
        match.away_xg = understat_data["away_xg"]
