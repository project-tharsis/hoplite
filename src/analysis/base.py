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
