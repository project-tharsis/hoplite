import re, json
import requests

class UnderstatClient:
    BASE_URL = "https://understat.com"
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "Mozilla/5.0"
    
    def get_league_matches(self, league: str = "EPL", season: str = "2024") -> list[dict]:
        """Fetch all match xG data for a league season."""
        url = f"{self.BASE_URL}/league/{league}/{season}"
        resp = self.session.get(url)
        resp.raise_for_status()
        return parse_match_data(resp.text)


def parse_match_data(html: str) -> list[dict]:
    """Extract matchesData JSON from Understat HTML."""
    pattern = r"var matchesData = JSON\.parse\('(.+?)'\);"
    match = re.search(pattern, html)
    if not match:
        return []
    
    raw_json = match.group(1)
    # Handle escaped characters
    raw_json = raw_json.replace("\\'", "'")
    data = json.loads(raw_json)
    
    matches = []
    for match_id, m in data.items():
        matches.append({
            "match_id": match_id,
            "home_team": m["h"]["title"],
            "away_team": m["a"]["title"],
            "home_xg": float(m["xG"]["h"]),
            "away_xg": float(m["xG"]["a"]),
            "home_goals": int(m["goals"]["h"]),
            "away_goals": int(m["goals"]["a"]),
        })
    return matches
