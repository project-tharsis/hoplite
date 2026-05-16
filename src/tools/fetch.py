"""Tool: fetch_match_data — pull latest match from football-data.org + Understat xG."""
import yaml
import json
from pathlib import Path
from src.data.football_data import FootballDataClient
from src.normalizer import normalize_football_data_match, merge_match_data


def match_to_json(match) -> dict:
    """Serialize Match to JSON-serializable dict."""
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
        "events": match.events,
        "home_lineup": match.home_lineup,
        "away_lineup": match.away_lineup,
        "result": match.result,
        "arsenal_is_home": match.arsenal_is_home,
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
    except Exception:
        pass  # Understat unreachable — xG stays None

    return match_to_json(match)


if __name__ == "__main__":
    result = fetch_match_data()
    print(json.dumps(result, indent=2, ensure_ascii=False))
