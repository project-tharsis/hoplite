from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional
from src.evaluation.predictor import ArtetaPredictor, PredictedPlan
from src.evaluation.knowledge import KnowledgeBase
from src.models.match import Match

@dataclass
class MatchReport:
    """Pure data container. No judgment — LLM does all analysis."""
    match: Match
    predicted_plan: PredictedPlan
    stats: dict = field(default_factory=dict)       # from extract_match_stats
    key_events: list = field(default_factory=list)  # from extract_key_events
    context: dict = field(default_factory=dict)     # from extract_context
    set_pieces: dict = field(default_factory=dict)  # from extract_set_piece_goals
    subs: list = field(default_factory=list)        # from extract_sub_impact
    # LLM-produced fields (filled after narrative generation)
    narrative: str = ""
    model_signals: dict = field(default_factory=dict)  # {"1": "🟢", "2": "🟡", ...}
    dimension_signals: dict = field(default_factory=dict)  # {"execution": "🟢", ...}

    @property
    def one_line_summary(self) -> str:
        """Simple scoreline + context. No judgment."""
        opponent = self.match.away_team if self.match.arsenal_is_home else self.match.home_team
        return f"Arsenal {self.match.arsenal_score}-{self.match.opponent_score} {opponent} ({self.match.competition})"

    def to_dict(self) -> dict:
        return {
            "match": {
                "fixture_id": self.match.fixture_id,
                "date": self.match.date.isoformat(),
                "competition": self.match.competition,
                "home_team": self.match.home_team,
                "away_team": self.match.away_team,
                "home_score": self.match.home_score,
                "away_score": self.match.away_score,
                "arsenal_score": self.match.arsenal_score,
                "opponent_score": self.match.opponent_score,
                "result": self.match.result,
            },
            "predicted_plan": {
                "focus_areas": self.predicted_plan.focus_areas,
                "likely_approach": self.predicted_plan.likely_approach,
                "key_battles": self.predicted_plan.key_battles,
                "expected_subs": self.predicted_plan.expected_subs,
            },
            "context": self.context,
            "stats": self.stats,
            "key_events": self.key_events,
            "set_pieces": self.set_pieces,
            "sub_impact": self.subs,
            "one_line_summary": self.one_line_summary,
            # LLM-produced fields
            "narrative": self.narrative,
            "model_signals": self.model_signals,
            "dimension_signals": self.dimension_signals,
        }


class ReportOrchestrator:
    """Assembles report from raw data. Passes to KB. No analysis."""
    
    def __init__(self, kb_path: str = None):
        if kb_path is None:
            kb_path = str(Path(__file__).resolve().parent.parent.parent / "data" / "knowledge.json")
        self.predictor = ArtetaPredictor()
        self.kb = KnowledgeBase(kb_path)
    
    def assemble(self, match: Match, stats: dict, events: list,
                 context: dict, set_pieces: dict, subs: list) -> MatchReport:
        """Assemble pure data report. Predict plan from context."""
        predicted_plan = self.predictor.predict(context or {})
        return MatchReport(
            match=match,
            predicted_plan=predicted_plan,
            stats=stats,
            key_events=events,
            context=context,
            set_pieces=set_pieces,
            subs=subs,
        )
    
    def save_to_kb(self, report: MatchReport, pre_context: dict, 
                   model_signals: dict = None, dimension_signals: dict = None):
        """Save match entry to knowledge base."""
        opponent = report.match.away_team if report.match.arsenal_is_home else report.match.home_team
        entry = {
            "match_id": str(report.match.fixture_id),
            "timestamp": report.match.date.isoformat(),
            "opponent": opponent,
            "score": f"{report.match.arsenal_score}-{report.match.opponent_score}",
            "result": report.match.result,
            "competition": report.match.competition,
            "pre_match_context": pre_context or {},
            "predicted_plan": {
                "focus_areas": report.predicted_plan.focus_areas,
                "likely_approach": report.predicted_plan.likely_approach,
                "key_battles": report.predicted_plan.key_battles,
                "expected_subs": report.predicted_plan.expected_subs,
            },
            "evaluation": {
                "model_signals": model_signals or {},
                "dimension_signals": dimension_signals or {},
            }
        }
        self.kb.save_entry(entry)
