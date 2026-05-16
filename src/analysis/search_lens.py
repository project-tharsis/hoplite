from src.analysis.base import TacticalLens, AnalysisResult
from src.models.match import Match
from src.data.search_source import build_match_report_query, build_trend_query


class SearchAugmentedLens(TacticalLens):
    """Lens that supplements match data with Brave search results."""

    search_queries: list[str] = []

    def _build_search_context(self, match: Match, context: dict = None) -> str:
        if context and "search_results" in context:
            return "\n".join(context["search_results"])
        return ""

    def analyze(self, match: Match, context: dict = None) -> AnalysisResult:
        search_context = self._build_search_context(match, context)
        return self._analyze_with_context(match, search_context)

    def _analyze_with_context(self, match: Match, search_context: str) -> AnalysisResult:
        raise NotImplementedError
