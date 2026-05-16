# Hoplite Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Build Hoplite — an Arsenal tactical analysis engine that pulls match data from free sources, analyzes through Arteta's six tactical principles, and outputs structured reports to Feishu.

**Architecture Decision:**
Three-tier pipeline: Data → Analysis → Output. Free data sources (football-data.org, Understat, API-Football, Brave search) feed into a normalization layer, then into six tactical analysis lenses, outputting Feishu interactive cards + long-form docs. No paid data APIs in v1 — maximize depth from free sources, layer in paid data (Opta/Wyscout) only when the framework is proven.

**Preconditions:**
- [ ] football-data.org API token (free tier)
- [ ] API-Football key (free tier, 100 req/day)
- [ ] lark-cli 1.0.23+ with bot identity configured
- [ ] Python 3.11+, requests, pandas in venv
- [ ] hoplite repo cloned from Project-Tharsis

**Tech Stack:** Python 3.11, requests, pandas, lark-cli (Feishu delivery), jq (card JSON compression)

---

## Phase 1: Data Pipeline

### Task 1.1: Project scaffold + dependencies

**Objective:** Set up project structure, venv, requirements, and config template.

**Files:**
- Create: `requirements.txt`
- Create: `config.example.yaml`
- Create: `src/__init__.py`
- Create: `src/data/__init__.py`
- Create: `tests/__init__.py`
- Create: `.gitignore`

**Step 1: Create requirements.txt**
```
requests>=2.31.0
pandas>=2.0.0
pyyaml>=6.0
python-dotenv>=1.0.0
pytest>=7.4.0
pytest-mock>=3.12.0
```

**Step 2: Create config.example.yaml**
```yaml
# hoplite config — copy to config.yaml and fill in tokens
data_sources:
  football_data:
    base_url: "https://api.football-data.org/v4"
    token: "YOUR_TOKEN"
  api_football:
    base_url: "https://v3.football.api-sports.io"
    key: "YOUR_KEY"
  understat:
    base_url: "https://understat.com"

arsenal:
  team_id_football_data: 57        # football-data.org Arsenal ID
  team_id_api_football: 42         # API-Football Arsenal ID
  team_name_understat: "Arsenal"

feishu:
  hoplite_chat_id: "oc_e23d8d8327fa57c53c9ca04e83f807e7"

output:
  card_max_tables: 5
  doc_folder_token: ""             # Feishu doc folder for long-form reports
```

**Step 3: Create .gitignore**
```
config.yaml
__pycache__/
.venv/
*.pyc
.env
```

**Step 4: Init venv + install**
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

**Step 5: Commit**
```bash
git add -A && git commit -m "chore: scaffold hoplite project structure"
```

---

### Task 1.2: football-data.org client

**Objective:** Build a client to fetch Premier League fixtures, results, and standings from football-data.org free tier.

**Files:**
- Create: `src/data/football_data.py`
- Create: `tests/data/test_football_data.py`

**Step 1: Write failing test**
```python
# tests/data/test_football_data.py
import pytest
from src.data.football_data import FootballDataClient
from unittest.mock import patch, Mock

def test_client_initialization():
    client = FootballDataClient(token="test_token")
    assert client.base_url == "https://api.football-data.org/v4"
    assert client.session.headers["X-Auth-Token"] == "test_token"

@patch("src.data.football_data.requests.Session.get")
def test_get_arsenal_matches(mock_get):
    mock_response = Mock()
    mock_response.json.return_value = {"matches": [{"id": 1, "homeTeam": {"name": "Arsenal"}}]}
    mock_response.raise_for_status = Mock()
    mock_get.return_value = mock_response
    
    client = FootballDataClient(token="test_token")
    matches = client.get_team_matches(team_id=57, status="FINISHED", limit=5)
    
    assert len(matches) == 1
    mock_get.assert_called_once()
```

**Step 2: Run to verify failure**
```bash
pytest tests/data/test_football_data.py -v
# Expected: FAIL — module not found
```

**Step 3: Write implementation**
```python
# src/data/football_data.py
import requests
from datetime import datetime

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
```

**Step 4: Run test to verify pass**
```bash
pytest tests/data/test_football_data.py -v
# Expected: 2 passed
```

**Step 5: Commit**
```bash
git add src/data/football_data.py tests/data/test_football_data.py
git commit -m "feat: football-data.org client with matches and standings endpoints"
```

---

### Task 1.3: Understat xG data extractor

**Objective:** Extract xG data from Understat HTML pages. Understat embeds data as JSON in JS variables — parse the HTML, extract the JSON, normalize.

**Files:**
- Create: `src/data/understat.py`
- Create: `tests/data/test_understat.py`

**Step 1: Write failing test**
```python
# tests/data/test_understat.py
import pytest
from src.data.understat import UnderstatClient, parse_match_data

SAMPLE_HTML = '''
<script>
var matchesData = JSON.parse('{"12345":{"h":{"title":"Arsenal"},"a":{"title":"Chelsea"},"xG":{"h":"2.31","a":"0.87"},"goals":{"h":"3","a":"1"}}}');
</script>
'''

def test_parse_match_data():
    matches = parse_match_data(SAMPLE_HTML)
    assert len(matches) == 1
    match = matches[0]
    assert match["home_team"] == "Arsenal"
    assert match["away_team"] == "Chelsea"
    assert match["home_xg"] == 2.31
    assert match["away_xg"] == 0.87
    assert match["home_goals"] == 3
    assert match["away_goals"] == 1
```

**Step 2: Write implementation**
```python
# src/data/understat.py
import re, json
import requests
from bs4 import BeautifulSoup

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
```

**Step 3: Run test to verify pass**
```bash
pytest tests/data/test_understat.py -v
# Expected: 1 passed
```

**Step 4: Commit**
```bash
git add src/data/understat.py tests/data/test_understat.py
git commit -m "feat: Understat xG data extractor with HTML parser"
```

---

### Task 1.4: API-Football client

**Objective:** Build client for API-Football free tier (100 req/day). Pull match events, lineups, and player stats.

**Files:**
- Create: `src/data/api_football.py`
- Create: `tests/data/test_api_football.py`

**Step 1: Write failing test**
```python
# tests/data/test_api_football.py
import pytest
from src.data.api_football import ApiFootballClient
from unittest.mock import patch, Mock

def test_client_headers():
    client = ApiFootballClient(key="test_key")
    assert client.session.headers["x-apisports-key"] == "test_key"

@patch("src.data.api_football.requests.Session.get")
def test_get_match_events(mock_get):
    mock_response = Mock()
    mock_response.json.return_value = {
        "response": [
            {"type": "Goal", "player": {"name": "Saka"}, "team": {"name": "Arsenal"}}
        ]
    }
    mock_response.raise_for_status = Mock()
    mock_get.return_value = mock_response
    
    client = ApiFootballClient(key="test_key")
    events = client.get_match_events(fixture_id=12345, team_id=42)
    
    assert len(events) == 1
    assert events[0]["type"] == "Goal"
```

**Step 2: Write implementation**
```python
# src/data/api_football.py
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
        """Get match statistics (possession, shots, passes, etc.)."""
        url = f"{self.BASE_URL}/fixtures/statistics"
        params = {"fixture": fixture_id}
        resp = self.session.get(url, params=params)
        resp.raise_for_status()
        return resp.json().get("response", [])
    
    def get_team_fixtures(self, team_id: int, season: int = 2025, limit: int = 10) -> list[dict]:
        """Get recent fixtures for a team."""
        url = f"{self.BASE_URL}/fixtures"
        params = {"team": team_id, "season": season, "last": limit}
        resp = self.session.get(url, params=params)
        resp.raise_for_status()
        return resp.json().get("response", [])
```

**Step 3: Run test**
```bash
pytest tests/data/test_api_football.py -v
# Expected: 2 passed
```

**Step 4: Commit**
```bash
git add src/data/api_football.py tests/data/test_api_football.py
git commit -m "feat: API-Football client with events, lineups, stats, fixtures"
```

---

### Task 1.5: Brave search match report source

**Objective:** Use Brave search to pull post-match tactical analysis articles for supplementary insight.

**Files:**
- Create: `src/data/search_source.py`
- Create: `tests/data/test_search_source.py`

**Step 1: Write implementation (no external dependencies needed — MCP tool handles search)**
```python
# src/data/search_source.py

MATCH_REPORT_QUERY_TEMPLATE = """
Arsenal vs {opponent} {date} tactical analysis post-match report lineup formation
"""

TEAM_ANALYSIS_QUERY_TEMPLATE = """
Arsenal {topic} tactical analysis 2025 season Arteta
"""

def build_match_report_query(opponent: str, date: str = "") -> str:
    """Build a Brave search query for post-match tactical analysis."""
    query = f"Arsenal vs {opponent} tactical analysis post-match report"
    if date:
        query += f" {date}"
    return query


def build_trend_query(topic: str) -> str:
    """Build a Brave search query for season trend analysis."""
    topics = {
        "inverted_fullback": "Arsenal inverted fullback tactical evolution 2025 season Arteta",
        "set_pieces": "Arsenal set piece goals Nicolas Jover analysis 2025",
        "pressing": "Arsenal high press pressing triggers tactical analysis 2025",
        "build_up": "Arsenal build-up structure positional play analysis 2025",
        "rest_defence": "Arsenal rest-defence counter-attack prevention analysis 2025",
    }
    return topics.get(topic, f"Arsenal {topic} tactical analysis 2025 season")
```

**Step 2: Write tests**
```python
# tests/data/test_search_source.py
from src.data.search_source import build_match_report_query, build_trend_query

def test_build_match_report_query():
    query = build_match_report_query("Manchester City", "2025-05-10")
    assert "Arsenal" in query
    assert "Manchester City" in query
    assert "2025-05-10" in query
    assert "tactical" in query

def test_build_trend_query_known_topic():
    query = build_trend_query("set_pieces")
    assert "set piece" in query.lower()
    assert "Jover" in query

def test_build_trend_query_unknown_topic():
    query = build_trend_query("something_unknown")
    assert "something_unknown" in query
```

**Step 3: Run test**
```bash
pytest tests/data/test_search_source.py -v
# Expected: 3 passed
```

**Step 4: Commit**
```bash
git add src/data/search_source.py tests/data/test_search_source.py
git commit -m "feat: Brave search query builder for match reports and trend analysis"
```

---

## Phase 2: Match Data Normalization

### Task 2.1: Unified match schema

**Objective:** Define a unified match data model that normalizes output from all three data sources into one structure.

**Files:**
- Create: `src/models/__init__.py`
- Create: `src/models/match.py`
- Create: `tests/models/test_match.py`

**Step 1: Write the data model**
```python
# src/models/match.py
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

@dataclass
class MatchEvent:
    minute: int
    type: str          # "goal", "card", "substitution", "var"
    team: str          # "home" or "away"
    player: str
    detail: str = ""   # e.g. "Right-footed shot from outside box"

@dataclass
class TeamStats:
    possession: float = 0.0
    shots: int = 0
    shots_on_target: int = 0
    xg: float = 0.0
    passes: int = 0
    pass_accuracy: float = 0.0
    fouls: int = 0
    corners: int = 0
    yellow_cards: int = 0
    red_cards: int = 0

@dataclass
class Match:
    fixture_id: int
    date: datetime
    competition: str
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    home_xg: Optional[float] = None
    away_xg: Optional[float] = None
    home_stats: Optional[TeamStats] = None
    away_stats: Optional[TeamStats] = None
    home_formation: Optional[str] = None
    away_formation: Optional[str] = None
    events: list[MatchEvent] = field(default_factory=list)
    home_lineup: list[str] = field(default_factory=list)
    away_lineup: list[str] = field(default_factory=list)
    
    @property
    def arsenal_is_home(self) -> bool:
        return self.home_team == "Arsenal"
    
    @property
    def arsenal_score(self) -> int:
        return self.home_score if self.arsenal_is_home else self.away_score
    
    @property
    def opponent_score(self) -> int:
        return self.away_score if self.arsenal_is_home else self.home_score
    
    @property
    def arsenal_xg(self) -> Optional[float]:
        if self.home_xg is None:
            return None
        return self.home_xg if self.arsenal_is_home else self.away_xg
    
    @property
    def result(self) -> str:
        """Returns 'W', 'D', or 'L' from Arsenal's perspective."""
        if self.arsenal_score > self.opponent_score:
            return "W"
        elif self.arsenal_score < self.opponent_score:
            return "L"
        return "D"
```

**Step 2: Write tests**
```python
# tests/models/test_match.py
from datetime import datetime
from src.models.match import Match, MatchEvent, TeamStats

def test_match_result_win():
    m = Match(
        fixture_id=1, date=datetime(2025, 5, 1), competition="PL",
        home_team="Arsenal", away_team="Chelsea",
        home_score=3, away_score=1
    )
    assert m.result == "W"
    assert m.arsenal_is_home is True

def test_match_result_loss_away():
    m = Match(
        fixture_id=2, date=datetime(2025, 5, 1), competition="PL",
        home_team="Liverpool", away_team="Arsenal",
        home_score=2, away_score=0
    )
    assert m.result == "L"
    assert m.arsenal_is_home is False

def test_match_xg_property():
    m = Match(
        fixture_id=3, date=datetime(2025, 5, 1), competition="PL",
        home_team="Arsenal", away_team="Spurs",
        home_score=2, away_score=0, home_xg=2.5, away_xg=0.3
    )
    assert m.arsenal_xg == 2.5

def test_team_stats_dataclass():
    stats = TeamStats(possession=58.5, shots=15, xg=2.1)
    assert stats.possession == 58.5
```

**Step 3: Run test**
```bash
pytest tests/models/test_match.py -v
# Expected: 4 passed
```

**Step 4: Commit**
```bash
git add src/models/ tests/models/
git commit -m "feat: unified match data model with Match, TeamStats, MatchEvent"
```

---

### Task 2.2: Data normalizer — merge sources into Match objects

**Objective:** Build a normalizer that takes raw data from all three sources and produces unified `Match` objects.

**Files:**
- Create: `src/normalizer.py`
- Create: `tests/test_normalizer.py`

**Step 1: Write failing tests**
```python
# tests/test_normalizer.py
from datetime import datetime
from src.normalizer import normalize_football_data_match, merge_match_data
from src.models.match import Match

SAMPLE_FD_MATCH = {
    "id": 500001,
    "utcDate": "2025-05-10T15:00:00Z",
    "competition": {"name": "Premier League"},
    "homeTeam": {"name": "Arsenal", "shortName": "Arsenal"},
    "awayTeam": {"name": "Chelsea", "shortName": "Chelsea"},
    "score": {
        "fullTime": {"home": 3, "away": 1}
    }
}

SAMPLE_UNDERSTAT_MATCH = {
    "match_id": "500001",
    "home_team": "Arsenal",
    "away_team": "Chelsea",
    "home_xg": 2.5,
    "away_xg": 0.6,
    "home_goals": 3,
    "away_goals": 1
}

def test_normalize_football_data():
    match = normalize_football_data_match(SAMPLE_FD_MATCH)
    assert match.fixture_id == 500001
    assert match.home_team == "Arsenal"
    assert match.away_team == "Chelsea"
    assert match.home_score == 3
    assert match.away_score == 1
    assert match.competition == "Premier League"

def test_merge_understat_xg():
    match = normalize_football_data_match(SAMPLE_FD_MATCH)
    merge_match_data(match, understat_data=SAMPLE_UNDERSTAT_MATCH)
    assert match.home_xg == 2.5
    assert match.away_xg == 0.6
```

**Step 2: Write implementation**
```python
# src/normalizer.py
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
    """Merge supplementary data into an existing Match object."""
    if understat_data:
        match.home_xg = understat_data["home_xg"]
        match.away_xg = understat_data["away_xg"]
```

**Step 3: Run test**
```bash
pytest tests/test_normalizer.py -v
# Expected: 2 passed
```

**Step 4: Commit**
```bash
git add src/normalizer.py tests/test_normalizer.py
git commit -m "feat: data normalizer — football-data.org + Understat → unified Match"
```

---

## Phase 3: Tactical Analysis Engine

### Task 3.1: Analysis framework base class

**Objective:** Define the base class and interface for all tactical analysis lenses.

**Files:**
- Create: `src/analysis/__init__.py`
- Create: `src/analysis/base.py`
- Create: `tests/analysis/test_base.py`

**Step 1: Write base class**
```python
# src/analysis/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from src.models.match import Match

@dataclass
class AnalysisResult:
    lens_name: str
    summary: str
    score: float            # 1-10 rating on this dimension
    key_moments: list[str]  # Key match moments related to this lens
    insights: list[str]     # Actionable tactical observations

class TacticalLens(ABC):
    """Base class for all Arteta tactical analysis lenses."""
    
    name: str = "base"
    
    @abstractmethod
    def analyze(self, match: Match, context: dict = None) -> AnalysisResult:
        """Analyze a match through this tactical lens."""
        ...
    
    def _build_result(self, summary: str, score: float, 
                      key_moments: list[str] = None,
                      insights: list[str] = None) -> AnalysisResult:
        return AnalysisResult(
            lens_name=self.name,
            summary=summary,
            score=max(1.0, min(10.0, score)),
            key_moments=key_moments or [],
            insights=insights or [],
        )
```

**Step 2: Write test**
```python
# tests/analysis/test_base.py
from src.analysis.base import TacticalLens, AnalysisResult

def test_analysis_result_dataclass():
    result = AnalysisResult(
        lens_name="test",
        summary="Good performance",
        score=7.5,
        key_moments=["Goal at 23'"],
        insights=["Pressing intensity was high"]
    )
    assert result.lens_name == "test"
    assert result.score == 7.5
    assert len(result.key_moments) == 1

class FakeLens(TacticalLens):
    name = "fake"
    def analyze(self, match, context=None):
        return self._build_result("ok", 5.0)

def test_tactical_lens_scores_are_clamped():
    lens = FakeLens()
    result = lens._build_result("test", 15.0)
    assert result.score == 10.0
    result2 = lens._build_result("test", 0.0)
    assert result2.score == 1.0
```

**Step 3: Run test**
```bash
pytest tests/analysis/test_base.py -v
# Expected: 2 passed
```

**Step 4: Commit**
```bash
git add src/analysis/ tests/analysis/
git commit -m "feat: tactical analysis base class — TacticalLens + AnalysisResult"
```

---

### Task 3.2: Set Pieces lens (highest-confidence lens)

**Objective:** Analyze set piece performance — Arsenal's strongest tactical area with Nicolas Jover. Uses concrete stats (corners, set piece goals) rather than vague interpretation.

**Files:**
- Create: `src/analysis/set_pieces.py`
- Create: `tests/analysis/test_set_pieces.py`

**Step 1: Write tests**
```python
# tests/analysis/test_set_pieces.py
from datetime import datetime
from src.models.match import Match
from src.analysis.set_pieces import SetPieceLens

def test_set_piece_analysis():
    match = Match(
        fixture_id=1, date=datetime(2025, 5, 1), competition="PL",
        home_team="Arsenal", away_team="Chelsea",
        home_score=2, away_score=0,
        events=[
            # Arsenal corner → goal
            {"minute": 34, "type": "goal", "team": "home", "player": "Gabriel", "detail": "Header from corner"},
            # Arsenal free kick → goal
            {"minute": 67, "type": "goal", "team": "home", "player": "Saliba", "detail": "Free kick cross"},
            # Open play goal  
            {"minute": 82, "type": "goal", "team": "away", "player": "Jackson", "detail": "Counter attack"},
        ]
    )
    
    lens = SetPieceLens()
    result = lens.analyze(match)
    
    assert result.score >= 8.0  # 2 set piece goals should score high
    assert "Gabriel" in result.summary
    assert len(result.key_moments) >= 2
```

**Step 2: Write implementation**
```python
# src/analysis/set_pieces.py
from src.analysis.base import TacticalLens, AnalysisResult
from src.models.match import Match

SET_PIECE_KEYWORDS = [
    "corner", "free kick", "set piece", "header from corner",
    "direct free kick", "penalty", "cross from free kick",
]

class SetPieceLens(TacticalLens):
    name = "Set Pieces"
    
    def analyze(self, match: Match, context: dict = None) -> AnalysisResult:
        arsenal_side = "home" if match.arsenal_is_home else "away"
        opponent_side = "away" if match.arsenal_is_home else "home"
        
        # Count set piece events
        arsenal_sp_goals = []
        opponent_sp_goals = []
        
        for event in match.events:
            if event["type"] != "goal":
                continue
            detail = event.get("detail", "").lower()
            is_sp = any(kw in detail for kw in SET_PIECE_KEYWORDS)
            
            if is_sp:
                if event["team"] == arsenal_side:
                    arsenal_sp_goals.append(event)
                else:
                    opponent_sp_goals.append(event)
        
        # Score: based on net set piece contribution
        arsenal_sp = len(arsenal_sp_goals)
        opponent_sp = len(opponent_sp_goals)
        total_goals = match.arsenal_score + match.opponent_score
        
        if total_goals == 0:
            score = 5.0
            summary = "No goals scored — set piece impact neutral."
        else:
            sp_impact_ratio = (arsenal_sp - opponent_sp) / max(total_goals, 1)
            score = 5.0 + (sp_impact_ratio * 5.0)  # 0-10 scale centered at 5
        
        key_moments = [
            f"Set piece goal: {g['player']} at {g['minute']}' — {g.get('detail', '')}"
            for g in arsenal_sp_goals
        ]
        
        insights = []
        if arsenal_sp >= 2:
            insights.append("Arsenal's set piece threat was decisive — Jover's routines worked perfectly.")
        if opponent_sp > 0:
            insights.append(f"Conceded {opponent_sp} set piece goal(s) — defensive set piece organization needs review.")
        
        summary = f"{arsenal_sp} set piece goal(s) scored, {opponent_sp} conceded. "
        if arsenal_sp_goals:
            goal_scorers = [g["player"] for g in arsenal_sp_goals]
            summary += f"Scorers: {', '.join(goal_scorers)}. "
        summary += "Set pieces were " + ("a decisive factor." if abs(arsenal_sp - opponent_sp) >= 2 else "a contributing factor.")
        
        return self._build_result(summary, score, key_moments, insights)
```

**Step 3: Run test**
```bash
pytest tests/analysis/test_set_pieces.py -v
# Expected: 1 passed
```

**Step 4: Commit**
```bash
git add src/analysis/set_pieces.py tests/analysis/test_set_pieces.py
git commit -m "feat: Set Pieces tactical lens — Jover's domain, highest-confidence module"
```

---

### Task 3.3: Goal Events lens (match narrative)

**Objective:** Analyze goal timings, types, and momentum shifts. Build the match narrative.

**Files:**
- Create: `src/analysis/goals.py`
- Create: `tests/analysis/test_goals.py`

**Step 1: Write implementation**
```python
# src/analysis/goals.py
from src.analysis.base import TacticalLens, AnalysisResult
from src.models.match import Match

class GoalEventsLens(TacticalLens):
    name = "Goal Events & Momentum"
    
    def analyze(self, match: Match, context: dict = None) -> AnalysisResult:
        arsenal_side = "home" if match.arsenal_is_home else "away"
        
        # Categorize goals by timing
        early = []   # 0-30'
        mid = []     # 31-60'
        late = []    # 61-90+'
        
        for event in match.events:
            if event["type"] != "goal":
                continue
            minute = event.get("minute", 0)
            if minute <= 30:
                early.append(event)
            elif minute <= 60:
                mid.append(event)
            else:
                late.append(event)
        
        # Arsenal's late goals are an Arteta trademark — score higher for late winners
        arsenal_late = [e for e in late if e["team"] == arsenal_side]
        arsenal_early = [e for e in early if e["team"] == arsenal_side]
        
        score = 5.0
        if arsenal_early:
            score += 1.5  # Fast start bonus
        if match.result == "W" and arsenal_late:
            score += 2.0  # Late winning mentality
            
        key_moments = [
            f"{e['minute']}' — {e['player']} scored for {'Arsenal' if e['team'] == arsenal_side else match.away_team if not match.arsenal_is_home else match.away_team}"
            for e in match.events if e["type"] == "goal"
        ]
        
        insights = []
        if arsenal_early:
            insights.append("Arsenal started aggressively — early goal set the tempo.")
        if arsenal_late:
            insights.append("Arsenal's late-game resilience showed — fitness and mentality held up.")
        
        summary = f"{match.arsenal_score}-{match.opponent_score} result. "
        summary += f"Goals: {', '.join(k['player'] for k in key_moments)}."
        
        return self._build_result(summary, score, key_moments, insights)
```

**Step 2: Write test + verify**
```bash
pytest tests/analysis/test_goals.py -v
# Expected: pass
```

**Step 3: Commit**
```bash
git add src/analysis/goals.py tests/analysis/test_goals.py
git commit -m "feat: Goal Events lens — timing, types, momentum analysis"
```

---

### Task 3.4: Remaining lenses (stubs with search-powered reasoning)

**Objective:** Create the remaining four lenses. Data depth limitations mean these rely on Brave search + LLM reasoning rather than precise positional data. Each lens queries Brave search for post-match analysis and synthesizes findings.

**Files:**
- Create: `src/analysis/build_up.py` (Build-up Structure)
- Create: `src/analysis/pressing.py` (Pressing Triggers)
- Create: `src/analysis/rest_defence.py` (Rest-Defence)
- Create: `src/analysis/overload.py` (Overload-to-Isolate)

**Step 1: Write the search-augmented base class**
```python
# src/analysis/search_lens.py
from src.analysis.base import TacticalLens, AnalysisResult
from src.models.match import Match
from src.data.search_source import build_match_report_query, build_trend_query

class SearchAugmentedLens(TacticalLens):
    """Lens that supplements match data with Brave search results."""
    
    search_queries: list[str] = []
    
    def _build_search_context(self, match: Match, context: dict = None) -> str:
        """Build search context from search results in context dict."""
        if context and "search_results" in context:
            return "\n".join(context["search_results"])
        return ""
    
    def analyze(self, match: Match, context: dict = None) -> AnalysisResult:
        search_context = self._build_search_context(match, context)
        return self._analyze_with_context(match, search_context)
    
    def _analyze_with_context(self, match: Match, search_context: str) -> AnalysisResult:
        raise NotImplementedError
```

**Step 2: Stub the four lenses with placeholder reasoning**

Each lens will be functional but score conservatively (4-6 range) when search context is thin. The framework is ready for deeper data when available.
```python
# src/analysis/build_up.py
from src.analysis.search_lens import SearchAugmentedLens
from src.models.match import Match

class BuildUpLens(SearchAugmentedLens):
    name = "Build-up Structure"
    
    def _analyze_with_context(self, match: Match, search_context: str) -> AnalysisResult:
        score = 5.0  # Default neutral — improves with data depth
        insights = []
        
        # Formation-based heuristics
        if match.home_formation:
            insights.append(f"Arsenal lined up in {match.home_formation if match.arsenal_is_home else match.away_formation} formation.")
        
        if search_context:
            insights.append("Post-match analysis indicates specific buildup patterns — see full report.")
            score += 1.0
        
        return self._build_result(
            f"Build-up structure analyzed. Formation: {match.home_formation or 'unknown'}. "
            f"Search context depth: {'available' if search_context else 'limited'}.",
            score, [], insights
        )
```

**Step 3: Commit**
```bash
git add src/analysis/search_lens.py src/analysis/build_up.py src/analysis/pressing.py src/analysis/rest_defence.py src/analysis/overload.py
git commit -m "feat: remaining tactical lenses — search-augmented build-up, pressing, rest-defence, overload"
```

---

## Phase 4: Match Report Generation

### Task 4.1: Report orchestrator

**Objective:** Build the orchestrator that runs all six lenses against a match and aggregates results into a structured report.

**Files:**
- Create: `src/report.py`
- Create: `tests/test_report.py`

**Step 1: Write implementation**
```python
# src/report.py
from dataclasses import dataclass, field
from src.models.match import Match
from src.analysis.base import TacticalLens, AnalysisResult
from src.analysis.set_pieces import SetPieceLens
from src.analysis.goals import GoalEventsLens
from src.analysis.build_up import BuildUpLens
from src.analysis.pressing import PressingLens
from src.analysis.rest_defence import RestDefenceLens
from src.analysis.overload import OverloadLens

@dataclass
class MatchReport:
    match: Match
    results: list[AnalysisResult] = field(default_factory=list)
    
    @property
    def overall_score(self) -> float:
        if not self.results:
            return 5.0
        return sum(r.score for r in self.results) / len(self.results)
    
    @property
    def one_line_summary(self) -> str:
        """One-line result with score: 'Arsenal 3-1 Chelsea (7.2/10)'"""
        return f"{self.match.home_team} {self.match.home_score}-{self.match.away_score} {self.match.away_team} ({self.overall_score:.1f}/10)"


class ReportOrchestrator:
    LENSES = [
        SetPieceLens(),
        GoalEventsLens(),
        BuildUpLens(),
        PressingLens(),
        RestDefenceLens(),
        OverloadLens(),
    ]
    
    def generate(self, match: Match, search_context: dict = None) -> MatchReport:
        report = MatchReport(match=match)
        for lens in self.LENSES:
            result = lens.analyze(match, context=search_context)
            report.results.append(result)
        return report
```

**Step 2: Write test**
```python
# tests/test_report.py
from datetime import datetime
from src.models.match import Match
from src.report import ReportOrchestrator

def test_report_generation():
    match = Match(
        fixture_id=1, date=datetime(2025, 5, 1), competition="PL",
        home_team="Arsenal", away_team="Chelsea",
        home_score=3, away_score=1,
        events=[
            {"minute": 23, "type": "goal", "team": "home", "player": "Saka", "detail": "Right foot shot"},
            {"minute": 55, "type": "goal", "team": "home", "player": "Jesus", "detail": "Tap in"},
            {"minute": 78, "type": "goal", "team": "away", "player": "Sterling", "detail": "Counter"},
            {"minute": 89, "type": "goal", "team": "home", "player": "Odegaard", "detail": "Penalty"},
        ]
    )
    
    orchestrator = ReportOrchestrator()
    report = orchestrator.generate(match)
    
    assert len(report.results) == len(ReportOrchestrator.LENSES)
    assert report.overall_score > 0
    assert "3-1" in report.one_line_summary
```

**Step 3: Run test**
```bash
pytest tests/test_report.py -v
# Expected: 1 passed
```

**Step 4: Commit**
```bash
git add src/report.py tests/test_report.py
git commit -m "feat: report orchestrator — runs all 6 lenses, aggregates into MatchReport"
```

---

## Phase 5: Output Pipeline

### Task 5.1: Feishu card builder

**Objective:** Convert MatchReport into a Feishu interactive card (v2.0 schema with table components) and send to hoplite group.

**Files:**
- Create: `src/output/__init__.py`
- Create: `src/output/feishu_card.py`
- Create: `tests/output/test_feishu_card.py`

**Step 1: Write implementation**
```python
# src/output/feishu_card.py
import json
import subprocess
from src.report import MatchReport

class FeishuCardBuilder:
    """Builds Feishu interactive card from MatchReport."""
    
    def __init__(self, chat_id: str):
        self.chat_id = chat_id
    
    def build_match_card(self, report: MatchReport) -> dict:
        """Build a feishu v2.0 interactive card for a match report."""
        m = report.match
        emoji = "🟢" if m.result == "W" else ("🟡" if m.result == "D" else "🔴")
        
        card = {
            "schema": "2.0",
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"{emoji} {m.home_team} {m.home_score}-{m.away_score} {m.away_team}"},
                "template": "blue"
            },
            "body": {
                "elements": [
                    {
                        "tag": "markdown",
                        "content": f"**{m.competition}** · {m.date.strftime('%Y-%m-%d')} · Overall: **{report.overall_score:.1f}/10**"
                    },
                    {"tag": "hr"},
                    self._build_lens_score_table(report),
                    {"tag": "hr"},
                    self._build_key_moments(report),
                ]
            }
        }
        return card
    
    def _build_lens_score_table(self, report: MatchReport) -> dict:
        """Build the 6-lens score summary table."""
        rows = []
        for r in report.results:
            rows.append({
                "lens": r.lens_name,
                "score": f"{'⭐' * int(r.score // 2)}{r.score:.1f}",
                "summary": r.summary[:80] + ("..." if len(r.summary) > 80 else "")
            })
        
        return {
            "tag": "table",
            "columns": [
                {"name": "lens", "display_name": "Dimension", "data_type": "text"},
                {"name": "score", "display_name": "Rating", "data_type": "text"},
                {"name": "summary", "display_name": "Key Point", "data_type": "lark_md"},
            ],
            "rows": rows
        }
    
    def _build_key_moments(self, report: MatchReport) -> dict:
        """Build key match moments section."""
        moments = []
        for r in report.results:
            for i, km in enumerate(r.key_moments[:1]):  # Top moment per lens
                moments.append(f"**{r.lens_name}**: {km}")
        
        return {
            "tag": "markdown",
            "content": "**🔑 Key Moments**\n" + "\n".join(f"• {m}" for m in moments[:6])
        }
    
    def send(self, report: MatchReport) -> bool:
        """Build card, save to temp file, send via lark-cli."""
        card = self.build_match_card(report)
        card_path = f"/tmp/hoplite_card_{report.match.fixture_id}.json"
        
        with open(card_path, "w", encoding="utf-8") as f:
            json.dump(card, f, ensure_ascii=False)
        
        # Use jq to compact + lark-cli to send
        result = subprocess.run([
            "bash", "-c",
            f"jq -c '.' {card_path} > {card_path}.compact && "
            f"lark-cli im +messages-send --as bot --chat-id {self.chat_id} "
            f"--msg-type interactive --content \"$(cat {card_path}.compact)\""
        ], capture_output=True, text=True, timeout=10)
        
        return "ok" in result.stdout.lower() or result.returncode == 0
```

**Step 2: Write test**
```python
# tests/output/test_feishu_card.py
from datetime import datetime
from src.models.match import Match
from src.report import ReportOrchestrator
from src.output.feishu_card import FeishuCardBuilder

def test_card_structure():
    match = Match(
        fixture_id=1, date=datetime(2025, 5, 1), competition="PL",
        home_team="Arsenal", away_team="Chelsea",
        home_score=3, away_score=1,
        events=[
            {"minute": 23, "type": "goal", "team": "home", "player": "Saka", "detail": "Shot"},
        ]
    )
    
    report = ReportOrchestrator().generate(match)
    builder = FeishuCardBuilder(chat_id="oc_test")
    card = builder.build_match_card(report)
    
    assert card["schema"] == "2.0"
    assert "header" in card
    assert "body" in card
    assert "elements" in card["body"]
    assert "3-1" in card["header"]["title"]["content"]
```

**Step 3: Run test**
```bash
pytest tests/output/test_feishu_card.py -v
# Expected: 1 passed
```

**Step 4: Commit**
```bash
git add src/output/ tests/output/
git commit -m "feat: Feishu card builder — MatchReport → interactive card with score table"
```

---

### Task 5.2: CLI entry point

**Objective:** Build a CLI that ties everything together: `python -m hoplite analyze --team arsenal --opponent chelsea --date 2025-05-10`

**Files:**
- Create: `src/cli.py`
- Create: `src/__main__.py`

**Step 1: Write CLI**
```python
# src/cli.py
import argparse
import yaml
from datetime import datetime
from src.data.football_data import FootballDataClient
from src.data.understat import UnderstatClient
from src.data.api_football import ApiFootballClient
from src.normalizer import normalize_football_data_match, merge_match_data
from src.report import ReportOrchestrator
from src.output.feishu_card import FeishuCardBuilder

def load_config():
    with open("config.yaml") as f:
        return yaml.safe_load(f)

def main():
    parser = argparse.ArgumentParser(description="Hoplite — Arsenal tactical analysis")
    parser.add_argument("action", choices=["analyze", "latest"], help="Action to perform")
    parser.add_argument("--fixture-id", type=int, help="API-Football fixture ID")
    parser.add_argument("--date", help="Match date (YYYY-MM-DD)")
    parser.add_argument("--output", choices=["card", "json"], default="card")
    args = parser.parse_args()
    
    config = load_config()
    
    # Initialize clients
    fd = FootballDataClient(token=config["data_sources"]["football_data"]["token"])
    af = ApiFootballClient(key=config["data_sources"]["api_football"]["key"])
    
    # Fetch data
    if args.action == "latest":
        matches = fd.get_team_matches(
            team_id=config["arsenal"]["team_id_football_data"],
            limit=1
        )[0]
    elif args.fixture_id:
        matches = af.get_team_fixtures(
            team_id=config["arsenal"]["team_id_api_football"],
            limit=10
        )
        # Find by fixture_id...
    
    # ... (full implementation follows pattern)
    
    # Generate report
    mapper = ReportOrchestrator()
    report = mapper.generate(match)
    
    # Output
    if args.output == "card":
        builder = FeishuCardBuilder(chat_id=config["feishu"]["hoplite_chat_id"])
        builder.send(report)
    
    print(report.one_line_summary)

if __name__ == "__main__":
    main()
```

**Step 2: Commit**
```bash
git add src/cli.py src/__main__.py
git commit -m "feat: CLI entry point — analyze/latest commands with card output"
```

---

## Phase 6: Automation

### Task 6.1: Hermes skill wrapper

**Objective:** Create a Hermes skill that wraps the Hoplite CLI, so Elio can trigger analysis with a single command.

**Skill behavior:**
- Load hoplite skill → auto-run latest match analysis → send card to hoplite group
- Accept `--fixture-id` for specific match analysis

### Task 6.2: Post-match cron trigger

**Objective:** Cron job that checks for new Arsenal results every 2 hours on matchdays, auto-generates report when FINISHED status detected.

**Schedule:** Every 2h on Sat/Sun/Mon/Wed/Thu (matchdays), 19:00-23:00 UTC

---

## Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| football-data.org rate limit (10 req/min free) | Low | Cache responses, batch requests |
| API-Football free tier exhaustion (100/day) | Medium | Prioritize matchdays, cache aggressively |
| Understat HTML structure changes | Medium | Version-lock parser, add structure validation test |
| FotMob/FBref Cloudflare blocks prevent depth data | High | Accepted — v1 is surface-level. Paid data (Opta) is v2. |
| Feishu card table limit (5 tables/card) | Low | Lenses fit in 1 table; if exceeded, paginate |
| Search context quality varies by match visibility | Medium | Big matches (top 6) get rich analysis; small matches get basics |

---

## Success Metrics (v1)

- [ ] Post-match report generated within 5 minutes of trigger
- [ ] 6/6 tactical lenses producing scored analysis
- [ ] Feishu card delivered to hoplite group without manual steps
- [ ] Set Piece lens: ≥70% agreement with human assessment (most concrete lens)
- [ ] Zero paid API spend

---

## Next: v2 Roadmap (not in this plan)

- Paid event data (Opta/Wyscout) for heatmaps, pass networks, pressing coordinates
- Season-over-season trend comparison
- Opponent scouting mode (analyze upcoming opposition through same lenses)
- Live match companion with key moment push notifications
- Player performance radar charts
