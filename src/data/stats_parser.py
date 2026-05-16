"""Parse API-Football fixture/statistics response into TeamStats dataclasses."""

from src.models.match import TeamStats


def parse_api_football_stats(
    stats_raw: list[dict],
    arsenal_team_id: int,
    arsenal_is_home: bool,
) -> tuple[TeamStats | None, TeamStats | None]:
    """Parse API-Football /fixtures/statistics response.

    Returns (home_stats, away_stats).
    """
    home_stats_raw: dict = {}
    away_stats_raw: dict = {}

    # API-Football returns two entries: one per team
    for team_stats in stats_raw:
        team_id = team_stats.get("team", {}).get("id")
        stats_list = team_stats.get("statistics", [])

        parsed: dict[str, float | int] = {}
        for stat in stats_list:
            stat_type = stat.get("type", "")
            value = stat.get("value")

            if stat_type == "Ball Possession":
                try:
                    parsed["possession"] = float(str(value).replace("%", ""))
                except (ValueError, TypeError):
                    parsed["possession"] = 0.0
            elif stat_type == "Total Shots":
                parsed["shots"] = int(value) if value else 0
            elif stat_type == "Shots on Goal":
                parsed["shots_on_target"] = int(value) if value else 0
            elif stat_type == "Total passes":
                parsed["passes"] = int(value) if value else 0
            elif stat_type == "Passes %":
                try:
                    parsed["pass_accuracy"] = float(str(value).replace("%", ""))
                except (ValueError, TypeError):
                    parsed["pass_accuracy"] = 0.0
            elif stat_type == "Fouls":
                parsed["fouls"] = int(value) if value else 0
            elif stat_type == "Corner Kicks":
                parsed["corners"] = int(value) if value else 0
            elif stat_type == "Yellow Cards":
                parsed["yellow_cards"] = int(value) if value else 0
            elif stat_type == "Red Cards":
                parsed["red_cards"] = int(value) if value else 0

        ts = TeamStats(
            possession=parsed.get("possession", 0.0),
            shots=parsed.get("shots", 0),
            shots_on_target=parsed.get("shots_on_target", 0),
            passes=parsed.get("passes", 0),
            pass_accuracy=parsed.get("pass_accuracy", 0.0),
            fouls=parsed.get("fouls", 0),
            corners=parsed.get("corners", 0),
            yellow_cards=parsed.get("yellow_cards", 0),
            red_cards=parsed.get("red_cards", 0),
        )

        if team_id == arsenal_team_id:
            if arsenal_is_home:
                home_stats_raw = parsed
            else:
                away_stats_raw = parsed
        else:
            if arsenal_is_home:
                away_stats_raw = parsed
            else:
                home_stats_raw = parsed

    def _make_stats(raw: dict) -> TeamStats | None:
        if not raw:
            return None
        return TeamStats(
            possession=float(raw.get("possession", 0.0)),
            shots=int(raw.get("shots", 0)),
            shots_on_target=int(raw.get("shots_on_target", 0)),
            passes=int(raw.get("passes", 0)),
            pass_accuracy=float(raw.get("pass_accuracy", 0.0)),
            fouls=int(raw.get("fouls", 0)),
            corners=int(raw.get("corners", 0)),
            yellow_cards=int(raw.get("yellow_cards", 0)),
            red_cards=int(raw.get("red_cards", 0)),
        )

    return _make_stats(home_stats_raw), _make_stats(away_stats_raw)
