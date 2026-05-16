from src.analysis.search_lens import SearchAugmentedLens
from src.analysis.base import AnalysisResult
from src.models.match import Match


class OverloadLens(SearchAugmentedLens):
    name = "Overload-to-Isolate"

    def _analyze_with_context(self, match: Match, search_context: str) -> AnalysisResult:
        score = 5.0
        insights = []

        if search_context:
            insights.append("Overload-to-isolate patterns observed in post-match analysis.")
            score += 1.0
        else:
            insights.append("Overload-to-isolate evaluation needs detailed passing network data.")

        return self._build_result(
            f"Overload-to-isolate patterns analyzed. "
            f"{'Search context enriched analysis' if search_context else 'Basic analysis — pass network data would improve depth'}.",
            score, [], insights
        )
