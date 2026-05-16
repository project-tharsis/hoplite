import requests


class ApiFootballClient:
    BASE_URL = "https://v3.football.api-sports.io"

    def __init__(self, key: str):
        self.session = requests.Session()
        self.session.headers["x-apisports-key"] = key

    def get_match_events(self, fixture_id: int, team_id: int = None) -> list[dict]:
        """Get match events (goals, cards, subs)."""
        url = f"{self.BASE_URL}/fixtures/events"
        params = {"fixture": fixture_id}
        if team_id:
            params["team"] = team_id
        resp = self.session.get(url, params=params)
        resp.raise_for_status()
        return resp.json().get("response", [])

    def get_match_lineups(self, fixture_id: int) -> list[dict]:
        """Get starting lineups and formations."""
        url = f"{self.BASE_URL}/fixtures/lineups"
        params = {"fixture": fixture_id}
        resp = self.session.get(url, params=params)
        resp.raise_for_status()
        return resp.json().get("response", [])

    def get_match_stats(self, fixture_id: int) -> list[dict]:
        """Get match statistics (possession, shots, passes)."""
        url = f"{self.BASE_URL}/fixtures/statistics"
        params = {"fixture": fixture_id}
        resp = self.session.get(url, params=params)
        resp.raise_for_status()
        return resp.json().get("response", [])

    def get_team_fixtures(self, team_id: int, season: int = 2025, limit: int = 10,
                          from_date: str = None, to_date: str = None) -> list[dict]:
        """Get recent fixtures for a team."""
        url = f"{self.BASE_URL}/fixtures"
        params = {"team": team_id, "season": season}
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        if not from_date and not to_date:
            params["last"] = limit
        resp = self.session.get(url, params=params)
        resp.raise_for_status()
        return resp.json().get("response", [])
