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
