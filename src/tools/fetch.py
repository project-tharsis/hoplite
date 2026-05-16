"""Tool: fetch_match_data — pull latest match from football-data.org + Understat xG."""
import yaml
import json
import sys
from pathlib import Path
from datetime import timedelta
from dataclasses import asdict
from src.data.football_data import FootballDataClient
from src.normalizer import normalize_football_data_match, merge_match_data


def match_to_json(match) -> dict:
    """Serialize Match to JSON-serializable dict."""
    events = []
    for ev in match.events:
        if hasattr(ev, "__dataclass_fields__"):
            events.append(asdict(ev))
        else:
            events.append(ev)
    return {
        "fixture_id": match.fixture_id,
        "date": match.date.isoformat(),
        "competition": match.competition,
        "home_team": match.home_team,
        "away_team": match.away_team,
        "home_score": match.home_score,
        "away_score": match.away_score,
        "home_xg": match.home_xg,
        "away_xg": match.away_xg,
        "home_formation": match.home_formation,
        "away_formation": match.away_formation,
        "events": events,
        "home_lineup": match.home_lineup,
        "away_lineup": match.away_lineup,
        "result": match.result,
        "arsenal_is_home": match.arsenal_is_home,
        "home_stats": asdict(match.home_stats) if match.home_stats else None,
        "away_stats": asdict(match.away_stats) if match.away_stats else None,
    }


def fetch_match_data(team: str = "Arsenal", status: str = "FINISHED", limit: int = 1) -> dict:
    """Fetch latest match for a team. Tries football-data.org + Understat xG."""
    config_path = Path(__file__).resolve().parent.parent.parent / "config.yaml"
    if not config_path.exists():
        return {"error": "config.yaml not found"}
    with open(config_path) as f:
        config = yaml.safe_load(f)

    # 1. football-data.org
    fd = FootballDataClient(token=config["data_sources"]["football_data"]["token"])
    raw_matches = fd.get_team_matches(
        team_id=config["arsenal"]["team_id_football_data"],
        status=status, limit=limit
    )
    if not raw_matches:
        return {"error": "No matches found"}

    raw = raw_matches[0]
    match = normalize_football_data_match(raw)

    # 2. Try Understat for xG
    try:
        from src.data.understat import UnderstatClient
        uc = UnderstatClient()
        understat_matches = uc.get_league_matches(season="2024")
        for um in understat_matches:
            if um["home_team"] in match.home_team and um["away_team"] in match.away_team:
                merge_match_data(match, understat_data=um)
                break
    except Exception as e:
        print(f"[WARN] Understat unavailable: {e}", file=sys.stderr)

    # 3. Try API-Football for events/lineups/stats
    try:
        from src.data.api_football import ApiFootballClient
        af = ApiFootballClient(key=config["data_sources"]["api_football"]["key"])

        # Find matching fixture: search by team + date
        match_date = match.date.strftime("%Y-%m-%d")
        from_date = (match.date - timedelta(days=1)).strftime("%Y-%m-%d")
        to_date = (match.date + timedelta(days=1)).strftime("%Y-%m-%d")

        season = match.date.year if match.date.month >= 8 else match.date.year - 1
        af_fixtures = af.get_team_fixtures(
            team_id=config["arsenal"]["team_id_api_football"],
            season=season, from_date=from_date, to_date=to_date
        )

        for af_fx in af_fixtures:
            af_date = af_fx["fixture"]["date"][:10]
            if af_date == match_date:
                fixture_id = af_fx["fixture"]["id"]

                # Get events
                events_raw = af.get_match_events(fixture_id=fixture_id)
                for ev in events_raw:
                    t = ev.get("time", {})
                    is_arsenal = ev["team"]["id"] == config["arsenal"]["team_id_api_football"]
                    team = "home" if (is_arsenal and match.arsenal_is_home) or (not is_arsenal and not match.arsenal_is_home) else "away"

                    detail = ev.get("detail", "")
                    comments = ev.get("comments", "") or ""

                    match.events.append({
                        "minute": t.get("elapsed", 0),
                        "type": ev.get("type", "").lower(),
                        "team": team,
                        "player": ev.get("player", {}).get("name", ""),
                        "detail": f"{detail} {comments}".strip(),
                    })

                # Get lineups
                lineups_raw = af.get_match_lineups(fixture_id=fixture_id)
                for lu in lineups_raw:
                    if lu["team"]["id"] == config["arsenal"]["team_id_api_football"]:
                        if match.arsenal_is_home:
                            match.home_formation = lu.get("formation")
                        else:
                            match.away_formation = lu.get("formation")
                    else:
                        if match.arsenal_is_home:
                            match.away_formation = lu.get("formation")
                        else:
                            match.home_formation = lu.get("formation")

                break  # Found the match
    except Exception as e:
        print(f"[WARN] API-Football unavailable: {e}", file=sys.stderr)

    return match_to_json(match)


if __name__ == "__main__":
    result = fetch_match_data()
    print(json.dumps(result, indent=2, ensure_ascii=False))
