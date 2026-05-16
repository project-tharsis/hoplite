from dataclasses import dataclass, field, asdict
from typing import Optional

from src.evaluation.mental_models import (
    MentalModelResult,
    CultureEvaluator,
    GameControlEvaluator,
    DefenceAsAttackEvaluator,
    MarginalGainsEvaluator,
    AddCapabilityEvaluator,
    RoleClarityEvaluator,
)
from src.evaluation.dimensions import (
    DimensionResult,
    PreMatchExecutionDimension,
    InMatchAdjustmentDimension,
    ResultSatisfactionDimension,
)
from src.evaluation.predictor import ArtetaPredictor, PredictedPlan
from src.evaluation.knowledge import KnowledgeBase
from src.models.match import Match


@dataclass
class MatchReport:
    match: Match
    predicted_plan: PredictedPlan
    mental_model_results: list[MentalModelResult] = field(default_factory=list)
    execution: Optional[DimensionResult] = None      # ① 赛前决策执行度
    adjustment: Optional[DimensionResult] = None      # ② 赛中调整合理性
    satisfaction: Optional[DimensionResult] = None    # ③ 结果满意度

    @property
    def overall_signal(self) -> str:
        # Simple voting: count 🟢 vs 🔴
        signals = [
            self.execution.signal if self.execution else '🟡',
            self.adjustment.signal if self.adjustment else '🟡',
            self.satisfaction.signal if self.satisfaction else '🟡',
        ]
        greens = signals.count('🟢')
        reds = signals.count('🔴')
        if greens >= 2:
            return '🟢'
        elif reds >= 2:
            return '🔴'
        return '🟡'

    @property
    def one_line_summary(self) -> str:
        # Chinese summary: e.g. "🟢 Arsenal 7-1 PSV — 执行到位，调整合理，大胜满意"
        opponent = self.match.away_team if self.match.arsenal_is_home else self.match.home_team
        score_line = f"{self.match.arsenal_score}-{self.match.opponent_score}"

        exec_label = self.execution.verdict if self.execution else "执行一般"
        adj_label = self.adjustment.verdict if self.adjustment else "调整一般"

        if self.match.result == "W" and self.match.arsenal_score - self.match.opponent_score >= 3:
            sat_label = "大胜满意"
        elif self.match.result == "W":
            sat_label = "取胜满意"
        elif self.match.result == "D":
            sat_label = "平局可接受"
        else:
            sat_label = "失利失望"

        return (
            f"{self.overall_signal} Arsenal {score_line} {opponent} — "
            f"{exec_label}，{adj_label}，{sat_label}"
        )

    def to_dict(self) -> dict:
        # Serializable for JSON output
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
            "mental_model_results": [
                {
                    "model_number": r.model_number,
                    "model_name": r.model_name,
                    "signal": r.signal,
                    "summary": r.summary,
                    "evidence": r.evidence,
                    "insights": r.insights,
                }
                for r in self.mental_model_results
            ],
            "execution": asdict(self.execution) if self.execution else None,
            "adjustment": asdict(self.adjustment) if self.adjustment else None,
            "satisfaction": asdict(self.satisfaction) if self.satisfaction else None,
            "overall_signal": self.overall_signal,
            "one_line_summary": self.one_line_summary,
        }


class ReportOrchestrator:
    EVALUATORS = [
        CultureEvaluator(),
        GameControlEvaluator(),
        DefenceAsAttackEvaluator(),
        MarginalGainsEvaluator(),
        AddCapabilityEvaluator(),
        RoleClarityEvaluator(),
    ]

    def __init__(self, kb_path: str = "/tmp/hoplite/data/knowledge.json"):
        self.predictor = ArtetaPredictor()
        self.execution_dim = PreMatchExecutionDimension()
        self.adjustment_dim = InMatchAdjustmentDimension()
        self.satisfaction_dim = ResultSatisfactionDimension()
        self.kb = KnowledgeBase(kb_path)

    def generate(self, match: Match,
                 pre_match_context: dict = None,
                 search_context: dict = None) -> MatchReport:
        # 1. Predict Arteta's plan
        predicted_plan = self.predictor.predict(pre_match_context or {})

        # 2. Run 6 mental model evaluators
        report = MatchReport(match=match, predicted_plan=predicted_plan)
        for evaluator in self.EVALUATORS:
            result = evaluator.evaluate(match, context=search_context)
            report.mental_model_results.append(result)

        # 3. Assess 3 dimensions
        plan_dict = {
            "focus_areas": predicted_plan.focus_areas,
            "likely_approach": predicted_plan.likely_approach,
            "key_battles": predicted_plan.key_battles,
            "expected_subs": predicted_plan.expected_subs,
        }
        report.execution = self.execution_dim.assess(match, plan_dict)
        report.adjustment = self.adjustment_dim.assess(match, plan_dict)
        report.satisfaction = self.satisfaction_dim.assess(match, pre_match_context or {})

        # 4. Save to knowledge base
        self._save_to_kb(report, pre_match_context or {})

        return report

    def _save_to_kb(self, report: MatchReport, pre_context: dict):
        opponent = report.match.away_team if report.match.arsenal_is_home else report.match.home_team
        entry = {
            "match_id": str(report.match.fixture_id),
            "timestamp": report.match.date.isoformat(),
            "opponent": opponent,
            "score": f"{report.match.arsenal_score}-{report.match.opponent_score}",
            "result": report.match.result,
            "competition": report.match.competition,
            "pre_match_context": pre_context,
            "predicted_plan": {
                "focus_areas": report.predicted_plan.focus_areas,
                "likely_approach": report.predicted_plan.likely_approach,
                "key_battles": report.predicted_plan.key_battles,
                "expected_subs": report.predicted_plan.expected_subs,
            },
            "evaluation": {
                "execution_signal": report.execution.signal if report.execution else "🟡",
                "adjustment_signal": report.adjustment.signal if report.adjustment else "🟡",
                "satisfaction_signal": report.satisfaction.signal if report.satisfaction else "🟡",
                "model_signals": {
                    str(r.model_number): r.signal for r in report.mental_model_results
                }
            }
        }
        self.kb.save_entry(entry)
