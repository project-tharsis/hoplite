"""Modular prompt builder for Arteta evaluation.

Builds structured prompts from MatchFeatures, WeakLabels, rubric,
and optional calibration hints. Replaces the monolithic prompt dump
with targeted, machine-readable sections.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional, Union

import yaml

from src.features.extractor import MatchFeatures
from src.labels.weak_labeler import WeakLabels

# Model ID → number mapping for rubric lookup
_MODEL_ID_TO_NUM = {
    "culture_as_os": "1",
    "where_game_is_played": "2",
    "defence_as_attacking_identity": "3",
    "marginal_gains": "4",
    "add_capability_keep_identity": "5",
    "role_clarity": "6",
}

_MODEL_NUM_TO_NAME_ZH = {
    "1": "文化标准",
    "2": "比赛控制",
    "3": "防守身份",
    "4": "边际收益",
    "5": "能力叠加",
    "6": "角色清晰",
}

_DIMENSION_LABELS_ZH = {
    "execution": "执行",
    "adjustment": "调整",
    "satisfaction": "满意",
}

_RESULT_LABELS_ZH = {"W": "胜", "D": "平", "L": "负"}

_RESULT_LABELS_EN = {"W": "Win", "D": "Draw", "L": "Loss"}

# ── JSON output schema (required by spec Section 9) ──────────────────

OUTPUT_SCHEMA = {
    "overall_signal": "🟢 | 🟡 | 🔴",
    "model_signals": {
        "1": "🟢 | 🟡 | 🔴",
        "2": "🟢 | 🟡 | 🔴",
        "3": "🟢 | 🟡 | 🔴",
        "4": "🟢 | 🟡 | 🔴",
        "5": "🟢 | 🟡 | 🔴",
        "6": "🟢 | 🟡 | 🔴",
    },
    "dimension_signals": {
        "execution": "🟢 | 🟡 | 🔴",
        "adjustment": "🟢 | 🟡 | 🔴",
        "satisfaction": "🟢 | 🟡 | 🔴",
    },
    "evidence": {
        "1": ["evidence string 1", "evidence string 2"],
        "2": ["..."],
        "3": ["..."],
        "4": ["..."],
        "5": ["..."],
        "6": ["..."],
    },
    "confidence": {
        "1": "high | medium | low",
        "2": "high | medium | low",
        "3": "high | medium | low",
        "4": "high | medium | low",
        "5": "high | medium | low",
        "6": "high | medium | low",
    },
    "missing_or_weak_evidence": ["xG missing", "pressing data unavailable"],
    "weak_label_disagreements": [
        {
            "model": "2",
            "weak_signal": "🟡",
            "llm_signal": "🟢",
            "reason": "xG data unavailable but shot dominance clear",
        }
    ],
    "narrative": "中文复盘正文...",
}


class PromptBuilder:
    """Build modular evaluation prompts from structured inputs.

    Sections:
        1. Match Summary
        2. Feature Table
        3. Missing Data
        4. Weak Label Baseline
        5. Rubric Excerpt
        6. Historical Calibration Hints (optional)
    """

    def __init__(
        self,
        rubric: Union[str, Path, dict],
        language: str = "zh",
    ):
        """Initialize with rubric and language.

        Args:
            rubric: Path to YAML file or pre-loaded dict.
            language: Output language code ("zh" or "en").
        """
        self.language = language
        self.rubric = self._load_rubric(rubric)

    @staticmethod
    def _load_rubric(rubric: Union[str, Path, dict]) -> dict:
        """Load rubric from path or dict."""
        if isinstance(rubric, dict):
            return rubric
        path = Path(rubric)
        if not path.exists():
            raise FileNotFoundError(f"Rubric file not found: {path}")
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def build(
        self,
        features: MatchFeatures,
        weak_labels: WeakLabels,
        calibration_hints: Optional[dict] = None,
        skip_history: bool = False,
        search_context: str = "",
    ) -> str:
        """Build the full modular prompt.

        Args:
            features: Extracted match features.
            weak_labels: Weak label signals.
            calibration_hints: Historical calibration data (optional).
            skip_history: If True, omit section 6.
            search_context: Additional external context.

        Returns:
            Complete prompt string for LLM evaluation.
        """
        sections = []

        # System instruction
        sections.append(self._build_system_instruction())

        # Section 1: Match Summary
        sections.append(self._build_match_summary(features))

        # Section 1.5: Match Process Signals
        sections.append(self._build_match_process_signals(features))

        # Section 2: Feature Table
        sections.append(self._build_feature_table(features))

        # Section 3: Missing Data
        sections.append(self._build_missing_data(features))

        # Section 4: Weak Label Baseline
        sections.append(self._build_weak_label_baseline(weak_labels))

        # Section 5: Rubric Excerpt
        sections.append(self._build_rubric_excerpt())

        # Section 6: Historical Calibration Hints
        if not skip_history and calibration_hints:
            sections.append(self._build_calibration_hints(calibration_hints))

        # External search context
        if search_context:
            sections.append(
                f"## 外部战术分析参考\n{search_context[:1000]}\n"
            )

        # Disagreement instruction
        sections.append(self._build_disagreement_instruction())

        # JSON output schema
        sections.append(self._build_output_schema())

        return "\n".join(sections)

    # ── Section builders ──────────────────────────────────────────────

    def _build_system_instruction(self) -> str:
        """System instruction for the LLM."""
        if self.language == "zh":
            return (
                "你是足球战术分析师，需要基于结构化比赛数据和弱标签基线，"
                "用 Arteta 的6个心智模型框架评估阿森纳的表现，然后撰写中文复盘。\n"
            )
        return (
            "You are a football tactical analyst. Evaluate Arsenal's performance "
            "using Arteta's 6 mental models framework based on structured match "
            "data and weak label baselines, then write a post-match review.\n"
        )

    def _build_match_summary(self, f: MatchFeatures) -> str:
        """Section 1: Concise factual match summary."""
        result_label = (
            _RESULT_LABELS_ZH.get(f.result, f.result)
            if self.language == "zh"
            else _RESULT_LABELS_EN.get(f.result, f.result)
        )

        opp = f.opponent_name or "对手"

        if self.language == "zh":
            lines = [
                "## 1. 比赛概述",
                "",
                f"比分: 阿森纳 {f.arsenal_goals} - {f.opponent_goals} {opp}（{result_label}）",
                f"场地: {f.venue or '未知'} | 对手等级: {f.opponent_quality or '未知'} | 赛事: {f.competition_stage or '未知'}",
            ]
        else:
            lines = [
                "## 1. Match Summary",
                "",
                f"Score: Arsenal {f.arsenal_goals} - {f.opponent_goals} {opp} ({result_label})",
                f"Venue: {f.venue or 'Unknown'} | Opponent tier: {f.opponent_quality or 'Unknown'} | Stage: {f.competition_stage or 'Unknown'}",
            ]
        lines.append("")
        return "\n".join(lines)

    def _build_match_process_signals(self, f: MatchFeatures) -> str:
        """Section 1.5: Match process signals (v2 features)."""
        if self.language == "zh":
            header = "## 1.5 比赛过程信号"
        else:
            header = "## 1.5 Match Process Signals"

        lines = [header, ""]

        # First goal
        if f.first_goal_team is not None:
            if f.first_goal_team == "arsenal":
                first_goal_label = "Arsenal"
            elif f.first_goal_team == "opponent":
                first_goal_label = f.opponent_name or "对手"
            else:
                first_goal_label = "unknown"
        else:
            first_goal_label = "unknown"

        if self.language == "zh":
            lines.append(f"- 先进球：{first_goal_label}")
        else:
            lines.append(f"- First goal: {first_goal_label}")

        # Minutes leading / trailing
        if f.minutes_leading is not None and f.minutes_trailing is not None:
            if self.language == "zh":
                lines.append(f"- 领先时间：{f.minutes_leading} 分钟；落后时间：{f.minutes_trailing} 分钟")
            else:
                lines.append(f"- Minutes leading: {f.minutes_leading}; trailing: {f.minutes_trailing}")

        # Lead protection
        if self.language == "zh":
            lines.append(f"- 领先保护：{f.final_state_from_first_lead}")
        else:
            lines.append(f"- Lead protection: {f.final_state_from_first_lead}")

        # After 75'
        if self.language == "zh":
            led_75 = "是" if f.led_after_75 else "否"
            late_lost = "是" if f.late_lead_lost else "否"
            lines.append(f"- 75' 后领先：{led_75}；75' 后丢领先：{late_lost}")
        else:
            led_75 = "Yes" if f.led_after_75 else "No"
            late_lost = "Yes" if f.late_lead_lost else "No"
            lines.append(f"- Led after 75': {led_75}; Late lead lost: {late_lost}")

        # Substitution state
        if f.first_sub_score_state is not None:
            if self.language == "zh":
                lines.append(f"- 换人时状态：{f.first_sub_score_state}")
            else:
                lines.append(f"- Sub state: {f.first_sub_score_state}")
        else:
            if self.language == "zh":
                lines.append("- 换人时状态：unknown")
            else:
                lines.append("- Sub state: unknown")

        # Net goals after first sub
        if f.first_sub_minute is not None:
            sign = "+" if f.net_goals_after_first_sub >= 0 else ""
            if self.language == "zh":
                lines.append(f"- 换人后净胜球：{sign}{f.net_goals_after_first_sub}")
            else:
                lines.append(f"- Net goals after first sub: {sign}{f.net_goals_after_first_sub}")

        # xG conversion
        if f.xg_overperformance_for is not None or f.xg_overperformance_against is not None:
            xg_parts = []
            if f.xg_overperformance_for is not None:
                sign = "+" if f.xg_overperformance_for >= 0 else ""
                xg_parts.append(f"for {sign}{f.xg_overperformance_for:.1f}")
            if f.xg_overperformance_against is not None:
                sign = "+" if f.xg_overperformance_against >= 0 else ""
                xg_parts.append(f"against {sign}{f.xg_overperformance_against:.1f}")
            if self.language == "zh":
                lines.append(f"- xG 转化差：{', '.join(xg_parts)}")
            else:
                lines.append(f"- xG conversion: {', '.join(xg_parts)}")

        # Opponent shot quality
        if f.opponent_xg_per_shot is not None:
            if self.language == "zh":
                lines.append(f"- 对手机会质量：xG/shot {f.opponent_xg_per_shot:.2f}")
            else:
                lines.append(f"- Opponent chance quality: xG/shot {f.opponent_xg_per_shot:.2f}")

        lines.append("")
        return "\n".join(lines)

    def _build_feature_table(self, f: MatchFeatures) -> str:
        """Section 2: Key features as a structured table."""
        if self.language == "zh":
            header = "## 2. 关键数据"
            cols = ("指标", "阿森纳", "对手", "差值")
        else:
            header = "## 2. Feature Table"
            cols = ("Metric", "Arsenal", "Opponent", "Delta")

        rows = []
        self._add_row(rows, cols, "possession", f.possession_for, f.possession_against, f.possession_delta, fmt=".1f", unit="%")
        self._add_row(rows, cols, "shots", f.shots_for, f.shots_against, f.shot_delta)
        self._add_row(rows, cols, "shots_on_target", f.shots_on_target_for, f.shots_on_target_against, f.shot_on_target_delta)
        self._add_row(rows, cols, "xG", f.xg_for, f.xg_against, f.xg_delta, fmt=".2f")
        self._add_row(rows, cols, "pass_accuracy", f.pass_accuracy_for, f.pass_accuracy_against, f.pass_accuracy_delta, fmt=".1f", unit="%")
        self._add_row(rows, cols, "corners", f.corners_for, f.corners_against, f.corner_delta)
        self._add_row(rows, cols, "fouls", f.fouls_for, f.fouls_against, None)

        # Cards
        if self.language == "zh":
            rows.append(f"| 黄牌 | {f.yellow_cards_for} | - | - |")
            rows.append(f"| 红牌 | {f.red_cards_for} | - | - |")
        else:
            rows.append(f"| Yellow cards | {f.yellow_cards_for} | - | - |")
            rows.append(f"| Red cards | {f.red_cards_for} | - | - |")

        # Set pieces
        self._add_row(rows, cols, "set_piece_goals", f.set_piece_goals_for, f.set_piece_goals_against, None)

        # Subs
        if self.language == "zh":
            rows.append(f"| 换人次数 | {f.arsenal_sub_count} | - | - |")
            rows.append(f"| 换人后进球 | {f.goals_after_arsenal_subs} | - | - |")
        else:
            rows.append(f"| Substitutions | {f.arsenal_sub_count} | - | - |")
            rows.append(f"| Goals after subs | {f.goals_after_arsenal_subs} | - | - |")

        # Build markdown table
        table_lines = [header, ""]
        table_lines.append(f"| {cols[0]} | {cols[1]} | {cols[2]} | {cols[3]} |")
        table_lines.append("| --- | --- | --- | --- |")
        table_lines.extend(rows)
        table_lines.append("")
        return "\n".join(table_lines)

    @staticmethod
    def _add_row(
        rows: list,
        cols: tuple,
        name: str,
        arsenal_val: Any,
        opponent_val: Any,
        delta_val: Any,
        fmt: str = "d",
        unit: str = "",
    ) -> None:
        """Add a formatted table row."""
        def _fmt(val, fmt_str, unit_str):
            if val is None:
                return "N/A"
            if fmt_str == "d":
                return f"{int(val)}{unit_str}"
            return f"{val:{fmt_str}}{unit_str}"

        a = _fmt(arsenal_val, fmt, unit)
        o = _fmt(opponent_val, fmt, unit)
        d = _fmt(delta_val, fmt, unit)
        rows.append(f"| {name} | {a} | {o} | {d} |")

    def _build_missing_data(self, f: MatchFeatures) -> str:
        """Section 3: What data is unavailable."""
        if self.language == "zh":
            header = "## 3. 缺失数据"
            if not f.missing_data:
                return f"{header}\n\n无缺失数据。\n"
            items = "\n".join(f"- {d}" for d in f.missing_data)
            return f"{header}\n\n{items}\n"
        else:
            header = "## 3. Missing Data"
            if not f.missing_data:
                return f"{header}\n\nNo missing data.\n"
            items = "\n".join(f"- {d}" for d in f.missing_data)
            return f"{header}\n\n{items}\n"

    def _build_weak_label_baseline(self, wl: WeakLabels) -> str:
        """Section 4: Weak label signals for all 6 models + 3 dimensions."""
        if self.language == "zh":
            header = "## 4. 弱标签基线"
            model_header = "### 心智模型信号"
            dim_header = "### 维度信号"
            overall_label = "综合信号"
            conf_label = "置信度"
        else:
            header = "## 4. Weak Label Baseline"
            model_header = "### Model Signals"
            dim_header = "### Dimension Signals"
            overall_label = "Overall"
            conf_label = "Confidence"

        lines = [header, ""]

        # Overall
        lines.append(f"**{overall_label}:** {wl.overall_signal}")
        lines.append("")

        # 6 model signals
        lines.append(model_header)
        for model_key in ["culture_as_os", "where_game_is_played",
                          "defence_as_attacking_identity", "marginal_gains",
                          "add_capability_keep_identity", "role_clarity"]:
            num = _MODEL_ID_TO_NUM.get(model_key, model_key)
            signal = wl.model_signals.get(model_key, "?")
            conf = wl.confidence.get(model_key, "?")
            name_zh = _MODEL_NUM_TO_NAME_ZH.get(num, model_key)
            ref = wl.evidence_refs.get(model_key, [])
            ref_str = ", ".join(ref[:3]) if ref else "N/A"
            if self.language == "zh":
                lines.append(f"- 模型{num} ({name_zh}): {signal} [{conf_label}: {conf}] 证据: {ref_str}")
            else:
                lines.append(f"- Model {num} ({model_key}): {signal} [{conf_label}: {conf}] Evidence: {ref_str}")
        lines.append("")

        # 3 dimension signals
        lines.append(dim_header)
        for dim_key in ["execution", "adjustment", "satisfaction"]:
            signal = wl.dimension_signals.get(dim_key, "?")
            label = _DIMENSION_LABELS_ZH.get(dim_key, dim_key) if self.language == "zh" else dim_key
            lines.append(f"- {label}: {signal}")
        lines.append("")

        return "\n".join(lines)

    def _build_rubric_excerpt(self) -> str:
        """Section 5: Relevant rubric rules for each model."""
        if self.language == "zh":
            header = "## 5. 评估规则摘要"
        else:
            header = "## 5. Rubric Excerpt"

        lines = [header, ""]

        models = self.rubric.get("models", [])
        for model in models:
            model_id = model.get("id", "?")
            name = model.get("display_name", model.get("name", "?"))
            philosophy = model.get("philosophy", "")
            weak_rules = model.get("weak_label_rules", [])
            neg_indicators = model.get("negative_indicators", [])
            pos_indicators = model.get("positive_indicators", [])
            guidance = model.get("narrative_guidance", "")

            lines.append(f"### 模型{model_id}: {name}")
            lines.append(f"**哲学**: {philosophy}")

            if pos_indicators:
                lines.append("**正面指标**:")
                for ind in pos_indicators[:3]:
                    lines.append(f"  - {ind}")

            if neg_indicators:
                lines.append("**负面指标**:")
                for ind in neg_indicators[:3]:
                    lines.append(f"  - {ind}")

            if weak_rules:
                lines.append("**判断规则**:")
                for rule in weak_rules[:4]:
                    lines.append(f"  - {rule}")

            if guidance:
                lines.append(f"**叙事指导**: {guidance}")

            lines.append("")

        # Dimensions
        dims = self.rubric.get("dimensions", [])
        if dims:
            if self.language == "zh":
                lines.append("### 三维度评估")
            else:
                lines.append("### Three Dimensions")

            for dim in dims:
                dim_id = dim.get("id", "?")
                name = dim.get("display_name", dim_id)
                rules = dim.get("judgment_rules", [])
                lines.append(f"**{name}** ({dim_id}):")
                for rule in rules[:3]:
                    lines.append(f"  - {rule}")
                lines.append("")

        return "\n".join(lines)

    def _build_calibration_hints(self, hints: dict) -> str:
        """Section 6: Historical calibration hints."""
        if self.language == "zh":
            header = "## 6. 历史校准参考"
        else:
            header = "## 6. Historical Calibration Hints"

        lines = [header, ""]

        if not hints:
            if self.language == "zh":
                lines.append("无历史数据可用。")
            else:
                lines.append("No historical data available.")
            lines.append("")
            return "\n".join(lines)

        # Similar scenario summary
        count = hints.get("count", 0)
        if count == 0:
            if self.language == "zh":
                lines.append("类似场景：无历史数据")
            else:
                lines.append("Similar scenarios: no historical data")
            lines.append("")
            return "\n".join(lines)

        # Support both flat (PatternComputer) and nested record (CalibrationComputer) shapes
        record = hints.get("record", hints)
        if self.language == "zh":
            wins = record.get("wins", 0)
            draws = record.get("draws", 0)
            losses = record.get("losses", 0)
            lines.append(f"类似场景共 {count} 场: {wins}胜 {draws}平 {losses}负")
            lines.append(f"场均进球 {record.get('avg_arsenal_score', 0)}, 场均失球 {record.get('avg_opponent_score', 0)}")
        else:
            wins = record.get("wins", 0)
            draws = record.get("draws", 0)
            losses = record.get("losses", 0)
            lines.append(f"Similar scenarios: {count} matches ({wins}W {draws}D {losses}L)")
            lines.append(f"Avg goals: {record.get('avg_arsenal_score', 0)}, Avg conceded: {record.get('avg_opponent_score', 0)}")

        # Model signal distributions
        model_dist = hints.get("model_signal_distribution", {})
        if model_dist:
            lines.append("")
            if self.language == "zh":
                lines.append("历史模型信号分布:")
            else:
                lines.append("Historical model signal distribution:")
            for model_num in sorted(model_dist.keys()):
                dist = model_dist[model_num]
                name = _MODEL_NUM_TO_NAME_ZH.get(model_num, f"模型{model_num}")
                lines.append(f"- {name}: 🟢{dist.get('🟢', 0)} 🟡{dist.get('🟡', 0)} 🔴{dist.get('🔴', 0)}")

        # Top focus areas
        top_areas = hints.get("most_common_focus_areas", [])
        if top_areas:
            lines.append("")
            if self.language == "zh":
                lines.append(f"常见战术重点: {'、'.join(top_areas)}")
            else:
                lines.append(f"Common focus areas: {', '.join(top_areas)}")

        # Calibration confidence (v2 CalibrationComputer fields)
        confidence = hints.get("confidence")
        if confidence:
            lines.append("")
            if self.language == "zh":
                lines.append(f"校准置信度: {confidence}")
            else:
                lines.append(f"Calibration confidence: {confidence}")

        # Sample quality breakdown
        sample_quality = hints.get("sample_quality")
        if sample_quality:
            wf = sample_quality.get("with_features", 0)
            wr = sample_quality.get("with_human_review", 0)
            lo = sample_quality.get("legacy_only", 0)
            lines.append("")
            if self.language == "zh":
                lines.append(f"样本质量: {wf}条含特征 / {wr}条含人工审核 / {lo}条仅旧格式")
            else:
                lines.append(f"Sample quality: {wf} with features / {wr} with human review / {lo} legacy-only")

        # Common missing data
        common_missing = hints.get("common_missing_data", [])
        if common_missing:
            lines.append("")
            if self.language == "zh":
                lines.append(f"历史常见缺失数据: {', '.join(common_missing)}")
            else:
                lines.append(f"Common missing data: {', '.join(common_missing)}")

        # Guardrails
        guardrails = hints.get("guardrails", [])
        if guardrails:
            lines.append("")
            if self.language == "zh":
                lines.append("校准护栏:")
            else:
                lines.append("Calibration guardrails:")
            for g in guardrails:
                lines.append(f"- {g}")

        # Known blind spots (v1.1)
        blind_spots = hints.get("known_blind_spots", [])
        if blind_spots:
            lines.append("")
            if self.language == "zh":
                lines.append("已知WK盲区:")
            else:
                lines.append("Known WK blind spots:")
            for bs in blind_spots:
                bs_id = bs.get("id", "?")
                bs_desc = bs.get("description", "")
                bs_guard = bs.get("guardrail", "")
                lines.append(f"- {bs_id}: {bs_desc}")
                if bs_guard:
                    if self.language == "zh":
                        lines.append(f"  护栏: {bs_guard}")
                    else:
                        lines.append(f"  Guardrail: {bs_guard}")

        lines.append("")
        if self.language == "zh":
            lines.append("**注意**: 历史仅作参考，以本场数据为准。")
        else:
            lines.append("**Note**: Historical data is reference only — prioritize current match data.")

        lines.append("")
        return "\n".join(lines)

    def _build_disagreement_instruction(self) -> str:
        """Instruction requiring LLM to explain disagreements."""
        if self.language == "zh":
            return (
                "## ⚠️ 弱标签分歧要求\n\n"
                "你 MUST 解释任何与弱标签基线的分歧。"
                "如果你的信号与弱标签不同，请在 weak_label_disagreements 中说明原因。\n"
            )
        return (
            "## ⚠️ Weak Label Disagreement Requirement\n\n"
            "You MUST explain any disagreements with the weak label baseline. "
            "If your signal differs from weak labels, explain why in weak_label_disagreements.\n"
        )

    def _build_output_schema(self) -> str:
        """Required JSON output schema."""
        if self.language == "zh":
            header = "## 输出格式\n\n请按以下 JSON 结构输出评估结果（先说 signals，再写 narrative）："
        else:
            header = "## Output Format\n\nOutput your evaluation in the following JSON structure:"

        schema_json = json.dumps(OUTPUT_SCHEMA, indent=2, ensure_ascii=False)
        return f"{header}\n\n```json\n{schema_json}\n```\n"
