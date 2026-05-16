from dataclasses import dataclass, field


@dataclass
class PredictedPlan:
    focus_areas: list[str] = field(default_factory=list)
    likely_approach: str = ""
    key_battles: list[str] = field(default_factory=list)
    expected_subs: str = ""


class ArtetaPredictor:
    """Directional prediction of Arteta's pre-match plan based on context."""

    def predict(self, pre_match_context: dict) -> PredictedPlan:
        """
        Input: {
            'opponent_quality': 'top6' | 'mid_table' | 'lower' | 'european_elite',
            'venue': 'home' | 'away' | 'neutral',
            'competition_stage': 'league_early' | 'league_late' | 'group_stage' | 'knockout' | 'final',
            'injury_situation': 'full_strength' | 'key_players_out' | 'crisis',
            'recent_form': 'W3' | 'mixed' | 'poor',
            'opponent_style': 'possession' | 'counter' | 'low_block' | 'pressing' | 'physical',
        }
        Returns: PredictedPlan with direction, not exact tactics
        """
        opponent_quality = pre_match_context.get("opponent_quality", "mid_table")
        venue = pre_match_context.get("venue", "home")
        competition_stage = pre_match_context.get("competition_stage", "league_early")
        injury_situation = pre_match_context.get("injury_situation", "full_strength")
        recent_form = pre_match_context.get("recent_form", "mixed")
        opponent_style = pre_match_context.get("opponent_style", "possession")

        focus_areas = self._build_focus_areas(
            opponent_quality, venue, competition_stage, injury_situation, recent_form, opponent_style
        )
        likely_approach = self._build_likely_approach(
            opponent_quality, venue, competition_stage, injury_situation, recent_form, opponent_style
        )
        key_battles = self._build_key_battles(opponent_quality, opponent_style, venue)
        expected_subs = self._build_expected_subs(
            competition_stage, injury_situation, recent_form, venue, opponent_quality
        )

        return PredictedPlan(
            focus_areas=focus_areas,
            likely_approach=likely_approach,
            key_battles=key_battles,
            expected_subs=expected_subs,
        )

    def _build_focus_areas(
        self,
        opponent_quality: str,
        venue: str,
        competition_stage: str,
        injury_situation: str,
        recent_form: str,
        opponent_style: str,
    ) -> list[str]:
        areas: list[str] = []

        # Venue + quality base
        if venue == "home" and opponent_quality == "lower":
            areas.extend(["控制中场", "边路overload"])
        elif venue == "away" and opponent_quality in ("top6", "european_elite"):
            areas.extend(["防守结构", "快速转换"])
        elif venue == "away" and opponent_quality == "mid_table":
            areas.extend(["控制节奏", "转换效率"])
        else:
            areas.append("控制中场")

        # Opponent style
        if opponent_style == "possession":
            if "反抢" not in areas and "断球" not in str(areas):
                areas.append("高位反抢/断球")
        elif opponent_style == "low_block":
            areas.append("耐心破低位 + 宽度利用")
        elif opponent_style == "counter":
            areas.append("防线高度管理")
        elif opponent_style == "pressing":
            areas.append("快速出球破解高压")
        elif opponent_style == "physical":
            areas.append("匹配对抗强度")

        # Competition stage
        if competition_stage in ("knockout", "final"):
            if "定位球威胁" not in areas:
                areas.append("定位球威胁")
        elif competition_stage == "group_stage":
            if "轮换体能管理" not in areas:
                areas.append("轮换体能管理")

        # Injury situation
        if injury_situation == "crisis":
            areas = ["保护阵型结构", "简化角色分工", "避免高位风险"]
        elif injury_situation == "key_players_out":
            areas.append("替补球员职责明确化")

        # Recent form
        if recent_form == "poor":
            areas.append("恢复比赛信心/控制失误")

        # Trim to 2-3 areas
        return areas[:3]

    def _build_likely_approach(
        self,
        opponent_quality: str,
        venue: str,
        competition_stage: str,
        injury_situation: str,
        recent_form: str,
        opponent_style: str,
    ) -> str:
        parts: list[str] = []

        if injury_situation == "crisis":
            parts.append("保守站位 + 保护阵型")
        elif venue == "home" and opponent_quality == "lower":
            parts.append("高位防线 + 控球消耗 + 耐心破低位")
        elif venue == "away" and opponent_quality in ("top6", "european_elite"):
            parts.append("低位防线 + 结构化防守 + 快速转换反击")
        elif opponent_style == "possession":
            parts.append("打断对手节奏 + 反抢后立即转换")
        elif opponent_style == "low_block":
            parts.append("控球消耗 + 边路宽度 + 禁区前沿渗透")
        elif opponent_style == "counter":
            parts.append("控制球权 + 防线高度管理 + 避免被反击")
        elif opponent_style == "pressing":
            parts.append("快速出球 + 利用身后空间 + 门将参与build-up")
        elif opponent_style == "physical":
            parts.append("先匹配对抗强度 + 再发挥技术优势")
        else:
            parts.append("平衡控球与防守结构")

        if competition_stage in ("knockout", "final"):
            parts.append("定位球重点部署")

        if recent_form == "poor":
            parts.append("降低风险 + 稳定开局")

        return "；".join(parts)

    def _build_key_battles(self, opponent_quality: str, opponent_style: str, venue: str) -> list[str]:
        battles: list[str] = []

        if opponent_style == "possession":
            battles.append("中场对抗 — Rice vs 对手组织型后腰")
            battles.append("压迫对手出球核心 — 限制向前传球")
        elif opponent_style == "counter":
            battles.append("防线身后空间 — 中卫回追 vs 对手前锋速度")
            battles.append("边后卫压上幅度 — 进攻宽度 vs 防守安全")
        elif opponent_style == "low_block":
            battles.append("禁区前沿创造 — 10号位/边锋内切 vs 密集防线")
            battles.append("传中质量 — 边锋/边后卫 vs 对手禁区防空")
        elif opponent_style == "pressing":
            battles.append("后场出球 — 门将/中卫 vs 对手前锋逼抢")
            battles.append("中场转身 — 球员背身接球 vs 高压")
        elif opponent_style == "physical":
            battles.append("空中对抗 — 中卫争顶 + 二点球控制")
            battles.append("身体对抗 — 中场肉搏 + 定位球攻防")

        if opponent_quality in ("top6", "european_elite"):
            battles.append("关键球员对位 — 限制对手核心进攻点")
        elif opponent_quality == "lower":
            battles.append("破密集耐心 — 避免急躁 + 把握有限机会")

        if venue == "away" and opponent_quality in ("top6", "european_elite"):
            battles.append("客场心态 — 抗压 + 把握转换效率")

        return battles[:3]

    def _build_expected_subs(
        self,
        competition_stage: str,
        injury_situation: str,
        recent_form: str,
        venue: str,
        opponent_quality: str,
    ) -> str:
        subs_parts: list[str] = []

        if injury_situation == "crisis":
            subs_parts.append("60' 上防守型中场保护领先/控制节奏")
            subs_parts.append("70' 换人保持体能避免伤病恶化")
        elif venue == "home" and opponent_quality == "lower":
            subs_parts.append("60' Trossard换边路保持压力/变化节奏")
            subs_parts.append("70' 轮换主力中场维持控球")
        elif venue == "away" and opponent_quality in ("top6", "european_elite"):
            subs_parts.append("60' 上防守型中场巩固结构")
            subs_parts.append("75' 反击点换前锋保持速度威胁")
        elif competition_stage in ("knockout", "final"):
            subs_parts.append("根据比分半场/60分钟战术调整")
            subs_parts.append("定位球专家/高点 late sub 抢分")
        else:
            subs_parts.append("60' 边路/进攻型换人维持压力")
            subs_parts.append("75' 防守型中场或后卫保护结果")

        if recent_form == "poor":
            subs_parts.insert(0, "50' 如局面僵持早换进攻球员打破平衡")

        return "；".join(subs_parts[:2])
