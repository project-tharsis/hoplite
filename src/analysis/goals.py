from src.analysis.base import TacticalLens, AnalysisResult
from src.models.match import Match


class GoalEventsLens(TacticalLens):
    name = "Goal Events & Momentum"

    def analyze(self, match: Match, context: dict = None) -> AnalysisResult:
        arsenal_side = "home" if match.arsenal_is_home else "away"
        opponent_name = match.away_team if match.arsenal_is_home else match.home_team

        early = []
        mid = []
        late = []

        for event in match.events:
            if event.get("type") != "goal":
                continue
            minute = event.get("minute", 0)
            if minute <= 30:
                early.append(event)
            elif minute <= 60:
                mid.append(event)
            else:
                late.append(event)

        arsenal_late = [e for e in late if e["team"] == arsenal_side]
        arsenal_early = [e for e in early if e["team"] == arsenal_side]

        score = 5.0
        if arsenal_early:
            score += 1.5
        if match.result == "W" and arsenal_late:
            score += 2.0

        goal_events = [e for e in match.events if e.get("type") == "goal"]
        key_moments = [
            f"{e['minute']}' — {e['player']} scored for {'Arsenal' if e['team'] == arsenal_side else opponent_name}"
            for e in goal_events
        ]

        insights = []
        if arsenal_early:
            insights.append("Arsenal started aggressively — early goal set the tempo.")
        if arsenal_late:
            insights.append("Arsenal's late-game resilience showed — fitness and mentality held up.")

        summary = f"{match.arsenal_score}-{match.opponent_score} result. "
        if goal_events:
            scorers = [e['player'] for e in goal_events[:3]]
            summary += f"Goals: {', '.join(scorers)}."

        return self._build_result(summary, score, key_moments, insights)
