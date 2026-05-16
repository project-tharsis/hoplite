from src.analysis.base import TacticalLens, AnalysisResult
from src.models.match import Match

SET_PIECE_KEYWORDS = [
    "corner", "free kick", "set piece", "header from corner",
    "direct free kick", "penalty", "cross from free kick",
]

class SetPieceLens(TacticalLens):
    name = "Set Pieces"
    
    def analyze(self, match: Match, context: dict = None) -> AnalysisResult:
        arsenal_side = "home" if match.arsenal_is_home else "away"
        opponent_side = "away" if match.arsenal_is_home else "home"
        
        arsenal_sp_goals = []
        opponent_sp_goals = []
        
        for event in match.events:
            if event["type"] != "goal":
                continue
            detail = event.get("detail", "").lower()
            is_sp = any(kw in detail for kw in SET_PIECE_KEYWORDS)
            
            if is_sp:
                if event["team"] == arsenal_side:
                    arsenal_sp_goals.append(event)
                else:
                    opponent_sp_goals.append(event)
        
        arsenal_sp = len(arsenal_sp_goals)
        opponent_sp = len(opponent_sp_goals)
        total_goals = match.arsenal_score + match.opponent_score
        
        if total_goals == 0:
            score = 5.0
            summary = "No goals scored — set piece impact neutral."
        else:
            sp_impact_ratio = (arsenal_sp - opponent_sp) / max(total_goals, 1)
            score = 5.0 + (sp_impact_ratio * 5.0)
        
        key_moments = [
            f"Set piece goal: {g['player']} at {g['minute']}' — {g.get('detail', '')}"
            for g in arsenal_sp_goals
        ]
        
        insights = []
        if arsenal_sp >= 2:
            insights.append("Arsenal's set piece threat was decisive — Jover's routines worked perfectly.")
        if opponent_sp > 0:
            insights.append(f"Conceded {opponent_sp} set piece goal(s) — defensive set piece organization needs review.")
        
        summary = f"{arsenal_sp} set piece goal(s) scored, {opponent_sp} conceded. "
        if arsenal_sp_goals:
            goal_scorers = [g["player"] for g in arsenal_sp_goals]
            summary += f"Scorers: {', '.join(goal_scorers)}. "
        summary += "Set pieces were " + ("a decisive factor." if abs(arsenal_sp - opponent_sp) >= 2 else "a contributing factor.")
        
        return self._build_result(summary, score, key_moments, insights)
