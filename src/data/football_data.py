import requests

class FootballDataClient:
    BASE_URL = "https://api.football-data.org/v4"
    
    def __init__(self, token: str):
        self.session = requests.Session()
        self.session.headers["X-Auth-Token"] = token
    
    def get_team_matches(self, team_id: int, status: str = "FINISHED", limit: int = 10) -> list[dict]:
        """Fetch recent matches for a team."""
        url = f"{self.BASE_URL}/teams/{team_id}/matches"
        params = {"status": status, "limit": limit}
        resp = self.session.get(url, params=params)
        resp.raise_for_status()
        return resp.json().get("matches", [])
    
    def get_standings(self, competition_id: str = "PL") -> list[dict]:
        """Fetch Premier League standings."""
        url = f"{self.BASE_URL}/competitions/{competition_id}/standings"
        resp = self.session.get(url)
        resp.raise_for_status()
        return resp.json().get("standings", [])
