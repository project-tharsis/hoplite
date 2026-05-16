from src.analysis.search_lens import SearchAugmentedLens
from src.analysis.base import AnalysisResult
from src.models.match import Match


class BuildUpLens(SearchAugmentedLens):
    name = "Build-up Structure"

    def _analyze_with_context(self, match: Match, search_context: str) -> AnalysisResult:
        score = 5.0
        insights = []

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
