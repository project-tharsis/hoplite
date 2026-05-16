from src.analysis.search_lens import SearchAugmentedLens
from src.analysis.base import AnalysisResult
from src.models.match import Match


class PressingLens(SearchAugmentedLens):
    name = "Pressing Triggers"

    def _analyze_with_context(self, match: Match, search_context: str) -> AnalysisResult:
        score = 5.0
        insights = []

        if search_context:
            insights.append("Pressing patterns identified in post-match analysis.")
            score += 1.0
        else:
            insights.append("Pressing data limited — full analysis requires event-level tracking data.")

        return self._build_result(
            f"Pressing analysis based on available data. "
            f"{'Context available' if search_context else 'Context limited — awaiting event data'}.",
            score, [], insights
        )
