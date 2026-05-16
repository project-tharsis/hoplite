from dataclasses import dataclass
from typing import Optional

from src.models.match import Match, MatchEvent


@dataclass
class DimensionResult:
    name: str
    signal: str  # '🟢' | '🟡' | '🔴'
    verdict: str  # short Chinese verdict (10-20 chars)
    reasoning: str  # Chinese explanation (2-4 sentences)
    evidence: list[str]  # specific match facts


class PreMatchExecutionDimension:
    name = "赛前决策执行度"

    def assess(
        self,
        match: Match,
        predicted_plan: dict,
        context: Optional[dict] = None,
    ) -> DimensionResult:
        focus_areas = predicted_plan.get("focus_areas", [])
        likely_approach = predicted_plan.get("likely_approach", "")
        key_battles = predicted_plan.get("key_battles", [])

        arsenal_stats = match.home_stats if match.arsenal_is_home else match.away_stats
        opponent_stats = match.away_stats if match.arsenal_is_home else match.home_stats

        green_flags = 0
        red_flags = 0
        evidence: list[str] = []

        # Evaluate focus areas
        for area in focus_areas:
            area_lower = area.lower()
            if "possession" in area_lower or "midfield" in area_lower or "control" in area_lower:
                if arsenal_stats and arsenal_stats.possession >= 60:
                    green_flags += 1
                    evidence.append(f"控球率达到 {arsenal_stats.possession}%，符合'{area}'的赛前部署")
                elif arsenal_stats and arsenal_stats.possession <= 45:
                    red_flags += 1
                    evidence.append(f"控球率仅 {arsenal_stats.possession}%，与'{area}'的部署严重不符")
                else:
                    evidence.append(f"控球率 {arsenal_stats.possession if arsenal_stats else 'N/A'}%，'{area}'执行一般")

            elif "press" in area_lower or "pressure" in area_lower or "逼抢" in area_lower:
                opponent_pass_acc = opponent_stats.pass_accuracy if opponent_stats else 100
                if opponent_pass_acc <= 75:
                    green_flags += 1
                    evidence.append(f"对手传球成功率仅 {opponent_pass_acc}%，高压逼抢效果显著")
                elif opponent_pass_acc >= 85:
                    red_flags += 1
                    evidence.append(f"对手传球成功率高达 {opponent_pass_acc}%，逼抢未能奏效")
                else:
                    evidence.append(f"对手传球成功率 {opponent_pass_acc}%，逼抢效果一般")

            elif "shot" in area_lower or "attack" in area_lower or "进攻" in area_lower:
                if arsenal_stats and arsenal_stats.shots >= 15:
                    green_flags += 1
                    evidence.append(f"全场射门 {arsenal_stats.shots} 次，进攻火力充足")
                elif arsenal_stats and arsenal_stats.shots <= 5:
                    red_flags += 1
                    evidence.append(f"全场仅射门 {arsenal_stats.shots} 次，进攻严重受阻")
                else:
                    evidence.append(f"射门 {arsenal_stats.shots if arsenal_stats else 'N/A'} 次，进攻表现中规中矩")

            elif "defend" in area_lower or "防守" in area_lower or "deep" in area_lower:
                if opponent_stats and opponent_stats.shots <= 8:
                    green_flags += 1
                    evidence.append(f"对手仅 {opponent_stats.shots} 次射门，防守部署成功")
                elif opponent_stats and opponent_stats.shots >= 15:
                    red_flags += 1
                    evidence.append(f"对手狂轰 {opponent_stats.shots} 次射门，防线承压过大")
                else:
                    evidence.append(f"对手射门 {opponent_stats.shots if opponent_stats else 'N/A'} 次，防守表现一般")

        # Evaluate early pressure / early goal
        if "early" in likely_approach.lower() or "开场" in likely_approach:
            early_goals = [
                e for e in match.events
                if e.type == "goal" and e.team == ("home" if match.arsenal_is_home else "away") and e.minute <= 15
            ]
            if early_goals:
                green_flags += 1
                evidence.append(f"开场 {early_goals[0].minute}' 取得进球， early pressure 执行到位")
            else:
                red_flags += 1
                evidence.append("开场15分钟内未能进球， early pressure 未达预期")

        # Evaluate key battles via xG
        if key_battles:
            if match.arsenal_xg is not None and match.arsenal_xg >= 1.5:
                green_flags += 1
                evidence.append(f"预期进球 xG {match.arsenal_xg}，关键对位创造足够威胁")
            elif match.arsenal_xg is not None and match.arsenal_xg <= 0.5:
                red_flags += 1
                evidence.append(f"预期进球 xG 仅 {match.arsenal_xg}，关键对位未能打开局面")

        if not evidence:
            evidence.append("赛前计划数据不足，无法精确评估执行度")

        if green_flags > 0 and red_flags == 0:
            signal = "🟢"
            verdict = "赛前部署执行到位"
            reasoning = (
                "球队在比赛中清晰地贯彻了赛前制定的战术方案，"
                "关键指标均达到或超过预期，整体表现协调一致。"
            )
        elif red_flags > 0 and green_flags == 0:
            signal = "🔴"
            verdict = "赛前计划执行失败"
            reasoning = (
                "球队未能按照赛前部署展开比赛，多个关键指标与预期存在明显偏差，"
                "战术执行层面出现较大问题，需要复盘总结。"
            )
        else:
            signal = "🟡"
            verdict = "部分执行有偏差"
            reasoning = (
                "球队在某些方面执行了赛前计划，但整体表现不够稳定，"
                "部分关键战术未能完全落地，属于中等执行水平。"
            )

        return DimensionResult(
            name=self.name,
            signal=signal,
            verdict=verdict,
            reasoning=reasoning,
            evidence=evidence,
        )


class InMatchAdjustmentDimension:
    name = "赛中调整合理性"

    def assess(
        self,
        match: Match,
        predicted_plan: dict,
        context: Optional[dict] = None,
    ) -> DimensionResult:
        evidence: list[str] = []
        sub_events = [e for e in match.events if e.type == "substitution" and e.team == ("home" if match.arsenal_is_home else "away")]
        arsenal_events = [e for e in match.events if e.team == ("home" if match.arsenal_is_home else "away")]

        # Sub timing analysis
        late_subs = [e for e in sub_events if e.minute >= 80]
        mid_subs = [e for e in sub_events if 45 <= e.minute < 80]
        early_subs = [e for e in sub_events if e.minute < 45]

        sub_goals = 0
        for sub in sub_events:
            # Check if a goal happened after this sub by the subbed player
            for ev in arsenal_events:
                if ev.type == "goal" and ev.minute > sub.minute and sub.player in ev.detail:
                    sub_goals += 1
                    evidence.append(f"替补球员 {sub.player} 在 {sub.minute}' 上场后取得进球/助攻")

        formation_changed = False
        if match.home_formation and match.away_formation:
            formation_changed = True  # Assume formation tracked implies a possible change

        # Score state at sub times
        was_losing_or_drawing = match.result in ("D", "L")

        # Heuristic scoring
        green_flags = 0
        red_flags = 0

        if sub_events:
            if sub_goals > 0:
                green_flags += 2
                evidence.append("换人直接产生进球效果，调整立竿见影")
            if mid_subs and was_losing_or_drawing:
                green_flags += 1
                evidence.append(f"在中场/下半场初段（{mid_subs[0].minute}'）及时调整，反应迅速")
            if late_subs and match.result == "L":
                red_flags += 1
                evidence.append(f"比分落后至 {late_subs[0].minute}' 才换人，调整时机过晚")
            if not sub_goals and len(sub_events) >= 3 and match.result == "L":
                red_flags += 1
                evidence.append("多次换人仍未能扭转败局，调整方向可能存在问题")
        else:
            if match.result == "W":
                evidence.append("球队保持领先，未进行大规模调整，稳定发挥即可")
            else:
                evidence.append("比赛局势有变但未做出换人调整，临场反应不足")
                red_flags += 1

        if formation_changed and match.result == "W":
            green_flags += 1
            evidence.append("阵型变化后球队取得胜利，战术调整有效")

        if not evidence:
            evidence.append("换人及调整数据有限，难以全面评估临场指挥")

        if green_flags >= 2:
            signal = "🟢"
            verdict = "临场调整及时有效"
            reasoning = (
                "教练组在比赛中做出了恰当的战术调整和换人决策，"
                "这些改变有效提升了球队表现或直接转化为进球，体现了出色的临场指挥能力。"
            )
        elif red_flags >= 2 or (red_flags > green_flags):
            signal = "🔴"
            verdict = "调整滞后且效果差"
            reasoning = (
                "比赛中的换人和战术调整未能起到积极作用，"
                "要么时机选择不当，要么方向错误，导致球队错失扭转局势的机会。"
            )
        else:
            signal = "🟡"
            verdict = "调整基本合理"
            reasoning = (
                "教练组做出了常规调整，虽然未带来决定性改变，"
                "但也未出现明显失误，整体属于中规中矩的临场指挥。"
            )

        return DimensionResult(
            name=self.name,
            signal=signal,
            verdict=verdict,
            reasoning=reasoning,
            evidence=evidence,
        )


class ResultSatisfactionDimension:
    name = "比赛结果满意度"

    def assess(
        self,
        match: Match,
        pre_match_context: dict,
        context: Optional[dict] = None,
    ) -> DimensionResult:
        opponent_quality = pre_match_context.get("opponent_quality", "medium")
        injury_situation = pre_match_context.get("injury_situation", "normal")
        competition_stage = pre_match_context.get("competition_stage", "league")

        result = match.result
        goal_diff = match.arsenal_score - match.opponent_score
        evidence: list[str] = []

        is_strong_opponent = opponent_quality in ("top", "strong", "high")
        is_weak_opponent = opponent_quality in ("weak", "low", "bottom")
        is_away = not match.arsenal_is_home
        heavy_loss = result == "L" and goal_diff <= -3
        injury_crisis = injury_situation in ("severe", "crisis", "many")

        evidence.append(f"赛果：{'胜' if result == 'W' else '平' if result == 'D' else '负'} ({match.arsenal_score}-{match.opponent_score})")
        evidence.append(f"对手实力评估：{opponent_quality}")
        if injury_crisis:
            evidence.append(f"伤病情况：{injury_situation}")

        # Determine signal
        if heavy_loss:
            signal = "🔴"
            verdict = "大比分失利不可接受"
            reasoning = (
                "无论对手强弱，大比分惨败都是难以接受的结果。"
                "球队在攻防两端均出现严重问题，需要深刻反思。"
            )
        elif result == "W" and is_strong_opponent:
            signal = "🟢"
            verdict = "强强对话拿下胜利"
            reasoning = (
                "面对实力强劲的对手能够全取三分，"
                "这充分体现了球队的竞争力和战术执行力，是令人满意的结果。"
            )
        elif result == "W" and is_weak_opponent:
            signal = "🟡"
            verdict = "正常发挥取得三分"
            reasoning = (
                "面对实力较弱的对手拿下胜利是预期之内，"
                "虽然结果合格，但过程未必令人完全放心。"
            )
        elif result == "D" and is_strong_opponent and is_away:
            signal = "🟢"
            verdict = "客场逼平强敌可接受"
            reasoning = (
                "在客场面对强劲对手能够拿下一分，"
                "从积分和士气角度看都是不错的结果，体现了球队的韧性。"
            )
        elif result == "D" and is_weak_opponent:
            signal = "🔴"
            verdict = "应赢未赢令人失望"
            reasoning = (
                "面对实力明显弱于自己的对手未能取胜，"
                "暴露了球队把握机会能力不足或心态松懈的问题。"
            )
        elif result == "L" and is_strong_opponent:
            signal = "🟡"
            verdict = "虽败犹荣表现尚可"
            reasoning = (
                "输给实力更强的对手并非不可接受，"
                "如果过程数据（如 xG、射门数）并不逊色，这场失利仍有可取之处。"
            )
        elif result == "L" and is_weak_opponent:
            signal = "🔴"
            verdict = "输给弱旅不可接受"
            reasoning = (
                "输给实力明显弱于自己的球队是严重失分，"
                "无论过程如何，这样的结果都无法让人满意。"
            )
        elif result == "D" and is_strong_opponent and not is_away:
            signal = "🟡"
            verdict = "主场平局略显遗憾"
            reasoning = (
                "主场面对强敌拿到一分可以接受，"
                "但球迷和球队原本可能期待更多，属于中规中矩的结果。"
            )
        elif result == "W" and injury_crisis:
            signal = "🟢"
            verdict = "残阵取胜难能可贵"
            reasoning = (
                "在伤病严重的情况下依然能够取得胜利，"
                "展现了球队的阵容深度和战斗精神，结果非常令人满意。"
            )
        else:
            signal = "🟡"
            verdict = "结果基本符合预期"
            reasoning = (
                "综合比赛背景和最终比分，"
                "这一结果处于可接受范围内，没有特别出彩也没有明显失误。"
            )

        if competition_stage in ("knockout", "final", "semifinal") and result == "L":
            signal = "🔴"
            verdict = "关键战失利影响重大"
            reasoning = (
                "在淘汰赛或决赛阶段输球意味着直接出局，"
                "这样的结果无论如何都是令人极度失望的。"
            )
            evidence.append(f"赛事阶段：{competition_stage}，输球即出局")

        return DimensionResult(
            name=self.name,
            signal=signal,
            verdict=verdict,
            reasoning=reasoning,
            evidence=evidence,
        )
