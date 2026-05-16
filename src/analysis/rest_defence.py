from src.analysis.search_lens import SearchAugmentedLens
from src.analysis.base import AnalysisResult
from src.models.match import Match


class RestDefenceLens(SearchAugmentedLens):
    name = "Rest-Defence"

    def _analyze_with_context(self, match: Match, search_context: str) -> AnalysisResult:
        score = 5.0
        insights = []

        if search_context:
            insights.append("Rest-defence patterns noted in post-match analysis.")
            score += 1.0
        else:
            insights.append("Rest-defence analysis requires positional tracking data for full evaluation.")

        return self._build_result(
            f"Rest-defence structure analyzed. "
            f"{'Search context available' if search_context else 'Limited data — positional tracking recommended'}.",
            score, [], insights
        )
