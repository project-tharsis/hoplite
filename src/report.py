from dataclasses import dataclass, field
from src.models.match import Match
from src.analysis.base import AnalysisResult
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
