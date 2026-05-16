from dataclasses import dataclass
from typing import Optional
from src.models.match import Match, MatchEvent, TeamStats


@dataclass
class MentalModelResult:
    model_number: int
    model_name: str
    signal: str  # '🟢' | '🟡' | '🔴'
    summary: str
    evidence: list[str]
    insights: list[str]


class BaseEvaluator:
    model_number: int = 0
    model_name: str = ""

    def evaluate(self, match: Match, context: Optional[dict] = None) -> MentalModelResult:
        raise NotImplementedError

    def _arsenal_stats(self, match: Match) -> Optional[TeamStats]:
        return match.home_stats if match.arsenal_is_home else match.away_stats

    def _opponent_stats(self, match: Match) -> Optional[TeamStats]:
        return match.away_stats if match.arsenal_is_home else match.home_stats

    def _arsenal_events(self, match: Match) -> list[MatchEvent]:
        side = "home" if match.arsenal_is_home else "away"
        return [e for e in match.events if e.team == side]

    def _opponent_events(self, match: Match) -> list[MatchEvent]:
        side = "away" if match.arsenal_is_home else "home"
        return [e for e in match.events if e.team == side]


class CultureEvaluator(BaseEvaluator):
    model_number = 1
    model_name = "文化是战术的操作系统"

    def evaluate(self, match: Match, context: Optional[dict] = None) -> MentalModelResult:
        signal = "🟡"
        evidence: list[str] = []
        insights: list[str] = []

        arsenal_stats = self._arsenal_stats(match)
        opponent_stats = self._opponent_stats(match)
        arsenal_events = self._arsenal_events(match)

        # Discipline signals
        yellows = sum(1 for e in arsenal_events if e.type == "card" and "yellow" in e.detail.lower())
        reds = sum(1 for e in arsenal_events if e.type == "card" and "red" in e.detail.lower())
        early_cards = sum(
            1 for e in arsenal_events
            if e.type == "card" and e.minute <= 30
        )

        if arsenal_stats:
            fouls = arsenal_stats.fouls
            evidence.append(f"Arsenal committed {fouls} fouls and received {yellows} yellow card(s).")
        else:
            evidence.append(f"Arsenal received {yellows} yellow card(s) — stats unavailable for foul count.")

        if reds > 0:
            evidence.append(f"Red card shown to Arsenal player — significant discipline breach.")
            signal = "🔴"
        elif early_cards >= 2:
            evidence.append(f"{early_cards} yellow cards before 30' — discipline and emotional control lacking early.")
            signal = "🔴"
        elif yellows == 0 and arsenal_stats and arsenal_stats.fouls <= 8:
            evidence.append("Clean disciplinary record with controlled aggression — standards held.")
            signal = "🟢"
        elif yellows <= 1:
            evidence.append("Minimal card exposure — discipline largely intact.")
            if signal == "🟡":
                signal = "🟢"

        # Accountability via result resilience
        if match.result == "W" and (yellows > 0 or (arsenal_stats and arsenal_stats.fouls > 12)):
            evidence.append("Won despite physical intensity — energy and commitment evident.")
            insights.append("Culture held under pressure: players fought for the result.")
        elif match.result == "L" and yellows >= 2:
            evidence.append("Defeat compounded by ill-discipline — standards slipped when it mattered.")
            insights.append("Review emotional control protocols; early cards disrupted tactical plan.")

        if not insights:
            if signal == "🟢":
                insights.append("Daily standards translated to matchday discipline — tactics can build on this foundation.")
            elif signal == "🔴":
                insights.append("Discipline issues suggest cultural standards need reinforcement before tactical adjustments.")
            else:
                insights.append("Mixed signals on culture — some discipline moments, but nothing catastrophic.")

        summary = (
            f"Culture {'strong' if signal == '🟢' else 'concerning' if signal == '🔴' else 'mixed'} — "
            f"{yellows} yellow(s), {reds} red(s). "
            f"Standards {'held' if signal == '🟢' else 'need review' if signal == '🔴' else 'inconsistent'}."
        )

        return MentalModelResult(
            model_number=self.model_number,
            model_name=self.model_name,
            signal=signal,
            summary=summary,
            evidence=evidence,
            insights=insights,
        )


class GameControlEvaluator(BaseEvaluator):
    model_number = 2
    model_name = "控制比赛发生在哪里"

    def evaluate(self, match: Match, context: Optional[dict] = None) -> MentalModelResult:
        signal = "🟡"
        evidence: list[str] = []
        insights: list[str] = []

        arsenal_stats = self._arsenal_stats(match)
        opponent_stats = self._opponent_stats(match)

        if arsenal_stats and opponent_stats:
            poss = arsenal_stats.possession
            shots = arsenal_stats.shots
            opp_shots = opponent_stats.shots
            sot = arsenal_stats.shots_on_target
            opp_sot = opponent_stats.shots_on_target
            xg = match.arsenal_xg
            opp_xg = match.away_xg if match.arsenal_is_home else match.home_xg
            corners = arsenal_stats.corners
            opp_corners = opponent_stats.corners
            pass_acc = arsenal_stats.pass_accuracy

            evidence.append(f"Possession: {poss:.1f}% — Arsenal {'dominated the ball' if poss > 55 else 'shared possession' if poss > 45 else 'played mainly without the ball'}.")
            evidence.append(f"Shots: {shots} vs {opp_shots} (SoT: {sot} vs {opp_sot}) — territory {'favoured Arsenal' if shots > opp_shots else 'even' if shots == opp_shots else 'favoured opponent'}.")

            if xg is not None and opp_xg is not None:
                evidence.append(f"xG: {xg:.2f} vs {opp_xg:.2f} — chance quality {'superior' if xg > opp_xg else 'even' if xg == opp_xg else 'inferior'}.")

            evidence.append(f"Corners: {corners} vs {opp_corners} — {'sustained pressure' if corners > opp_corners else 'pressure even' if corners == opp_corners else 'territory ceded'}.")
            evidence.append(f"Pass accuracy: {pass_acc:.1f}% — rhythm {'controlled' if pass_acc > 82 else 'disrupted' if pass_acc < 75 else 'moderate'}.")

            score = 0
            if poss > 55:
                score += 1
            elif poss < 45:
                score -= 1
            if shots > opp_shots:
                score += 1
            elif shots < opp_shots:
                score -= 1
            if xg is not None and opp_xg is not None:
                if xg > opp_xg:
                    score += 1
                elif xg < opp_xg:
                    score -= 1
            if pass_acc > 82:
                score += 1
            elif pass_acc < 74:
                score -= 1
            if corners > opp_corners:
                score += 1
            elif corners < opp_corners:
                score -= 1

            if score >= 2:
                signal = "🟢"
            elif score <= -2:
                signal = "🔴"
        else:
            evidence.append("Team stats unavailable — control assessment limited to result and events.")
            if match.result == "W":
                signal = "🟢"
            elif match.result == "L":
                signal = "🔴"

        if match.result == "W":
            insights.append("Arsenal dictated where the game was played and converted control into result.")
        elif match.result == "D":
            insights.append("Control fragmented — Arsenal couldn't impose rhythm for 90 minutes.")
        else:
            insights.append("Opponent dictated territory and tempo — Arsenal played in uncomfortable zones.")

        summary = (
            f"Game control {'established' if signal == '🟢' else 'lost' if signal == '🔴' else 'mixed'} — "
            f"Arsenal {'imposed their rhythm' if signal == '🟢' else 'struggled to find zones' if signal == '🔴' else 'had moments but not sustained dominance'}."
        )

        return MentalModelResult(
            model_number=self.model_number,
            model_name=self.model_name,
            signal=signal,
            summary=summary,
            evidence=evidence,
            insights=insights,
        )


class DefenceAsAttackEvaluator(BaseEvaluator):
    model_number = 3
    model_name = "防守也是进攻身份"

    def evaluate(self, match: Match, context: Optional[dict] = None) -> MentalModelResult:
        signal = "🟡"
        evidence: list[str] = []
        insights: list[str] = []

        arsenal_stats = self._arsenal_stats(match)
        opponent_stats = self._opponent_stats(match)
        arsenal_events = self._arsenal_events(match)
        opponent_events = self._opponent_events(match)

        goals_conceded = match.opponent_score
        opp_shots = opponent_stats.shots if opponent_stats else None
        opp_sot = opponent_stats.shots_on_target if opponent_stats else None
        arsenal_xg = match.arsenal_xg
        opp_xg = match.away_xg if match.arsenal_is_home else match.home_xg

        # Defensive solidity
        if goals_conceded == 0:
            evidence.append("Clean sheet — defensive foundation gave platform to attack.")
            signal = "🟢"
        elif goals_conceded == 1:
            evidence.append("Conceded once — defence largely held, one breach.")
        else:
            evidence.append(f"Conceded {goals_conceded} goals — defensive platform unstable.")
            signal = "🔴"

        if opp_shots is not None:
            evidence.append(f"Opponent managed {opp_shots} shots ({opp_sot or 0} on target) — {'restricted' if opp_shots <= 8 else 'moderate threat' if opp_shots <= 14 else 'under sustained pressure'}.")
            if opp_shots > 14 and signal != "🔴":
                signal = "🔴"

        # Attacking returns from defensive platform
        if arsenal_xg is not None and opp_xg is not None:
            if arsenal_xg > opp_xg + 0.5:
                evidence.append(f"Arsenal out-created opponent in xG ({arsenal_xg:.2f} vs {opp_xg:.2f}) — defensive work fed chance generation.")
                if signal == "🟡":
                    signal = "🟢"
            elif arsenal_xg < opp_xg - 0.5:
                evidence.append(f"xG deficit ({arsenal_xg:.2f} vs {opp_xg:.2f}) — defending didn't translate to enough attacking threat.")
                if signal == "🟡":
                    signal = "🔴"

        # Transition/counter-press proxy: goals from events that suggest quick turnovers
        # We approximate by looking at goal events with detail mentioning fast/counter/press
        transition_keywords = ["counter", "fast break", "press", "turnover", "recovery"]
        arsenal_goals = [e for e in arsenal_events if e.type == "goal"]
        transition_goals = [
            e for e in arsenal_goals
            if any(kw in e.detail.lower() for kw in transition_keywords)
        ]
        if transition_goals:
            evidence.append(f"{len(transition_goals)} goal(s) stemmed from high-press or counter-attack — defence directly fuelled attack.")
            signal = "🟢"

        if match.result == "W" and goals_conceded <= 1:
            insights.append("Defensive identity enabled victory — players see defending as the path to their game.")
        elif match.result == "L" and goals_conceded >= 2:
            insights.append("Defensive platform collapsed — attacking identity can't emerge without defensive stability.")
        else:
            insights.append("Mixed defensive returns — need more transitions from recovery to chance creation.")

        summary = (
            f"Defence {'fuelled attack effectively' if signal == '🟢' else 'failed to enable attack' if signal == '🔴' else 'had moments but link to attack inconsistent'} — "
            f"{goals_conceded} conceded, {len([e for e in arsenal_events if e.type == 'goal'])} scored."
        )

        return MentalModelResult(
            model_number=self.model_number,
            model_name=self.model_name,
            signal=signal,
            summary=summary,
            evidence=evidence,
            insights=insights,
        )


class MarginalGainsEvaluator(BaseEvaluator):
    model_number = 4
    model_name = "边际收益要专家化"

    SET_PIECE_KEYWORDS = [
        "corner", "free kick", "set piece", "header from corner",
        "direct free kick", "penalty", "cross from free kick",
        "throw-in",
    ]

    def evaluate(self, match: Match, context: Optional[dict] = None) -> MentalModelResult:
        signal = "🟡"
        evidence: list[str] = []
        insights: list[str] = []

        arsenal_events = self._arsenal_events(match)
        opponent_events = self._opponent_events(match)

        arsenal_sp_goals = [
            e for e in arsenal_events
            if e.type == "goal" and any(kw in e.detail.lower() for kw in self.SET_PIECE_KEYWORDS)
        ]
        opponent_sp_goals = [
            e for e in opponent_events
            if e.type == "goal" and any(kw in e.detail.lower() for kw in self.SET_PIECE_KEYWORDS)
        ]
        arsenal_penalties = [
            e for e in arsenal_events
            if e.type == "goal" and "penalty" in e.detail.lower()
        ]
        opponent_penalties = [
            e for e in opponent_events
            if e.type == "goal" and "penalty" in e.detail.lower()
        ]

        total_sp_arsenal = len(arsenal_sp_goals) + len(arsenal_penalties)
        total_sp_opponent = len(opponent_sp_goals) + len(opponent_penalties)

        evidence.append(f"Arsenal scored {total_sp_arsenal} set piece / penalty goal(s) from specialist routines.")
        evidence.append(f"Conceded {total_sp_opponent} set piece / penalty goal(s).")

        if arsenal_stats := self._arsenal_stats(match):
            evidence.append(f"Arsenal won {arsenal_stats.corners} corners — restart opportunities created.")

        if total_sp_arsenal >= 2:
            evidence.append("Multiple set piece goals — Jover's specialist routines delivered decisive output.")
            signal = "🟢"
        elif total_sp_arsenal == 1:
            evidence.append("One set piece goal — specialist department contributed.")
            if signal == "🟡":
                signal = "🟢"

        if total_sp_opponent >= 2:
            evidence.append("Conceded multiple set piece goals — specialist defensive organisation failed.")
            signal = "🔴"
        elif total_sp_opponent == 1:
            evidence.append("Conceded one set piece goal — marginal gain went to opponent.")
            if signal == "🟡":
                signal = "🔴"

        if len(arsenal_penalties) > 0:
            evidence.append(f"Penalty converted — composure under specialist pressure.")

        if total_sp_arsenal >= 2 and total_sp_opponent == 0:
            insights.append("Set piece threat was decisive — Jover's routines delivered a clear marginal gain.")
        elif total_sp_opponent > 0:
            insights.append("Opponent exploited restarts — specialist defensive routines need immediate review.")
        else:
            insights.append("Set piece battle was neutral — no decisive marginal gain either way.")

        summary = (
            f"Marginal gains {'specialised effectively' if signal == '🟢' else 'went against Arsenal' if signal == '🔴' else 'balanced'} — "
            f"{total_sp_arsenal} scored, {total_sp_opponent} conceded from set pieces / penalties."
        )

        return MentalModelResult(
            model_number=self.model_number,
            model_name=self.model_name,
            signal=signal,
            summary=summary,
            evidence=evidence,
            insights=insights,
        )


class AddCapabilityEvaluator(BaseEvaluator):
    model_number = 5
    model_name = "加能力，但不要丢身份"

    def evaluate(self, match: Match, context: Optional[dict] = None) -> MentalModelResult:
        signal = "🟡"
        evidence: list[str] = []
        insights: list[str] = []

        arsenal_stats = self._arsenal_stats(match)
        opponent_stats = self._opponent_stats(match)
        arsenal_events = self._arsenal_events(match)

        # Traditional Arsenal identity proxies: technical play, build-up, passing
        if arsenal_stats:
            pass_acc = arsenal_stats.pass_accuracy
            possession = arsenal_stats.possession
            passes = arsenal_stats.passes

            evidence.append(f"Pass accuracy {pass_acc:.1f}% — {'technical identity intact' if pass_acc >= 82 else 'technical level dropped' if pass_acc < 76 else 'moderate technical display'}.")
            evidence.append(f"Possession {possession:.1f}% — {'build-up game preserved' if possession >= 50 else 'more direct approach than traditional identity'}.")
            evidence.append(f"{passes} passes attempted — {'patient build-up evident' if passes > 400 else 'quicker transitions preferred' if passes < 300 else 'mixed build-up and direct play'}.")

            # Identity score: positive if traditional strengths maintained
            identity_score = 0
            if pass_acc >= 82:
                identity_score += 1
            if possession >= 50:
                identity_score += 1
            if passes >= 350:
                identity_score += 1

            # Capability addition score: positive if new dimensions evident
            capability_score = 0
            shots = arsenal_stats.shots
            if shots >= 15:
                capability_score += 1  # Increased shot volume = new threat
            if match.arsenal_xg is not None and match.arsenal_xg >= 1.5:
                capability_score += 1  # Quality chance creation
            if arsenal_stats.corners >= 6:
                capability_score += 1  # Set piece threat / territory dominance

            evidence.append(f"Identity markers: {identity_score}/3 — capability markers: {capability_score}/3.")

            if identity_score >= 2 and capability_score >= 2:
                signal = "🟢"
            elif identity_score <= 1 and capability_score <= 1:
                signal = "🔴"
        else:
            evidence.append("Stats unavailable — identity assessment limited to events.")

        # Look for varied goal types as evidence of added capability without losing identity
        goal_types = set()
        for e in arsenal_events:
            if e.type == "goal":
                detail = e.detail.lower()
                if "header" in detail:
                    goal_types.add("aerial")
                elif "outside box" in detail or "long range" in detail:
                    goal_types.add("long_range")
                elif "penalty" in detail:
                    goal_types.add("penalty")
                elif "counter" in detail or "fast break" in detail:
                    goal_types.add("transition")
                else:
                    goal_types.add("build_up")

        if len(goal_types) >= 2:
            evidence.append(f"Goal variety ({', '.join(goal_types)}) — added capabilities complementing existing strengths.")
            if signal == "🟡":
                signal = "🟢"

        if signal == "🟢":
            insights.append("New capabilities layered onto traditional identity — evolution without dilution.")
        elif signal == "🔴":
            insights.append("Identity markers weak — risk of losing what made Arsenal effective while adding new elements.")
        else:
            insights.append("Mixed picture: some identity held, but new capabilities not yet firing consistently.")

        summary = (
            f"Identity {'preserved with added capability' if signal == '🟢' else 'eroded' if signal == '🔴' else 'partially intact, additions uneven'} — "
            f"technical play and chance creation balance {'achieved' if signal == '🟢' else 'missing' if signal == '🔴' else 'in progress'}."
        )

        return MentalModelResult(
            model_number=self.model_number,
            model_name=self.model_name,
            signal=signal,
            summary=summary,
            evidence=evidence,
            insights=insights,
        )


class RoleClarityEvaluator(BaseEvaluator):
    model_number = 6
    model_name = "人需要清晰度，不只是压力"

    def evaluate(self, match: Match, context: Optional[dict] = None) -> MentalModelResult:
        signal = "🟡"
        evidence: list[str] = []
        insights: list[str] = []

        arsenal_events = self._arsenal_events(match)
        all_events = match.events

        # Substitutions impact
        subs = [e for e in all_events if e.type == "substitution"]
        arsenal_subs = [e for e in subs if e.team == ("home" if match.arsenal_is_home else "away")]
        opponent_subs = [e for e in subs if e.team == ("away" if match.arsenal_is_home else "home")]

        evidence.append(f"Arsenal made {len(arsenal_subs)} substitution(s), opponent made {len(opponent_subs)}.")

        # Sub impact: did a sub score or assist within 15 mins of coming on?
        sub_impact = False
        for sub in arsenal_subs:
            # Approximate impact: look for goal events by same player within 15 mins after sub
            sub_minute = sub.minute
            for e in arsenal_events:
                if e.type == "goal" and e.player == sub.player and sub_minute < e.minute <= sub_minute + 15:
                    evidence.append(f"{sub.player} scored within 15 minutes of coming on — sub had immediate impact.")
                    sub_impact = True

        if arsenal_subs and not sub_impact:
            evidence.append("Substitutes didn't register a direct goal impact within 15 minutes of coming on.")

        # Positional discipline via formation
        if match.arsenal_is_home and match.home_formation:
            evidence.append(f"Formation: {match.home_formation} — structure provided.")
        elif not match.arsenal_is_home and match.away_formation:
            evidence.append(f"Formation: {match.away_formation} — structure provided.")
        else:
            evidence.append("Formation data unavailable — role clarity harder to assess.")

        # Lineup size as proxy for selection clarity
        lineup = match.home_lineup if match.arsenal_is_home else match.away_lineup
        if lineup:
            evidence.append(f"Lineup of {len(lineup)} players named — roles defined pre-match.")

        # Red/yellow cards as proxy for positional confusion (players out of position making desperate fouls)
        cards = [e for e in arsenal_events if e.type == "card"]
        if len(cards) >= 3:
            evidence.append(f"{len(cards)} cards — possible positional confusion leading to recovery fouls.")
            signal = "🔴"
        elif len(cards) <= 1 and len(arsenal_subs) >= 3:
            evidence.append("Low cards with full bench usage — squad depth used, roles clear across squad.")
            signal = "🟢"
        elif sub_impact:
            evidence.append("Substitute made decisive contribution — non-starters understood their role.")
            if signal == "🟡":
                signal = "🟢"

        # Result context
        if match.result == "W" and len(arsenal_subs) >= 3:
            evidence.append("Full squad rotation with victory — depth and role clarity validated.")
            signal = "🟢"
        elif match.result == "L" and len(arsenal_subs) <= 1:
            evidence.append("Late/few subs in defeat — either lack of clarity in alternatives or reluctance to change roles.")
            if signal == "🟡":
                signal = "🔴"

        if signal == "🟢":
            insights.append("Players had context and protection — role clarity enabled confident execution.")
        elif signal == "🔴":
            insights.append("Role confusion or lack of bench impact — players need more clarity, not just pressure.")
        else:
            insights.append("Some roles clear, but bench impact and positional discipline inconsistent.")

        summary = (
            f"Role clarity {'strong' if signal == '🟢' else 'weak' if signal == '🔴' else 'mixed'} — "
            f"{len(arsenal_subs)} sub(s), {'sub impact evident' if sub_impact else 'no direct sub goal impact'}."
        )

        return MentalModelResult(
            model_number=self.model_number,
            model_name=self.model_name,
            signal=signal,
            summary=summary,
            evidence=evidence,
            insights=insights,
        )
