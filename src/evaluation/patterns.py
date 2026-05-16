"""
Historical pattern computation from KnowledgeBase.

Pure statistical aggregation — no judgment, no interpretation.
"""

from collections import Counter
from pathlib import Path
from typing import Optional

from src.evaluation.knowledge import KnowledgeBase

# Signal → numeric value mapping
SIGNAL_VALUES: dict[str, float] = {
    "🟢": 1.0,
    "🟡": 0.5,
    "🔴": 0.0,
}

# Model number → short Chinese name
MODEL_NAMES: dict[str, str] = {
    "1": "文化标准",
    "2": "比赛控制",
    "3": "防守身份",
    "4": "边际收益",
    "5": "能力叠加",
    "6": "角色清晰",
}

# All known dimension signal keys (inside evaluation.dimension_signals)
DIMENSION_KEYS = ["execution", "adjustment", "satisfaction"]

DIMENSION_LABELS: dict[str, str] = {
    "execution": "执行",
    "adjustment": "调整",
    "satisfaction": "满意",
}


class PatternComputer:
    """Compute historical patterns from KB. Pure stats — no judgment."""

    def __init__(self, kb_path: str = None):
        if kb_path is None:
            kb_path = str(Path(__file__).resolve().parent.parent.parent / "data" / "knowledge.json")
        self.kb = KnowledgeBase(kb_path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _filter_by_context(self, entries: list[dict], context: dict) -> list[dict]:
        """Filter entries matching the given context keys from pre_match_context."""
        result = []
        for entry in entries:
            pre_match = entry.get("pre_match_context", {})
            match = True
            for key, value in context.items():
                if pre_match.get(key) != value:
                    match = False
                    break
            if match:
                result.append(entry)
        return result

    @staticmethod
    def _parse_score(score: str) -> tuple[int, int]:
        """Parse '3-1' → (3, 1). Returns (0, 0) on failure."""
        try:
            parts = score.split("-")
            return int(parts[0]), int(parts[1])
        except (ValueError, IndexError, AttributeError):
            return 0, 0

    @staticmethod
    def _empty_distribution() -> dict[str, int]:
        return {"🟢": 0, "🟡": 0, "🔴": 0}

    @staticmethod
    def _signal_value(signal: Optional[str]) -> float:
        """Convert a signal emoji to its numeric value; return 0.5 for unknown."""
        return SIGNAL_VALUES.get(signal, 0.5)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def similar_match_summary(self, context: dict, limit: int = 10) -> dict:
        """
        Summary of matches similar to the given context.

        Args:
            context: e.g. {"opponent_quality": "mid_table", "venue": "away", "competition_stage": "knockout"}
            limit: max entries to consider

        Returns:
            dict with count, wins, draws, losses, scoring avgs,
            model_signal_distribution, dimension_signal_distribution, most_common_focus_areas.
        """
        all_entries = self.kb.get_all()
        matches = self._filter_by_context(all_entries, context)[:limit]

        if not matches:
            return {
                "count": 0,
                "wins": 0,
                "draws": 0,
                "losses": 0,
                "avg_arsenal_score": 0.0,
                "avg_opponent_score": 0.0,
                "model_signal_distribution": {
                    m: self._empty_distribution() for m in MODEL_NAMES
                },
                "dimension_signal_distribution": {
                    k: self._empty_distribution() for k in DIMENSION_KEYS
                },
                "most_common_focus_areas": [],
            }

        wins = draws = losses = 0
        arsenal_goals = 0
        opponent_goals = 0
        model_distributions: dict[str, Counter] = {
            m: Counter() for m in MODEL_NAMES
        }
        dimension_distributions: dict[str, Counter] = {
            k: Counter() for k in DIMENSION_KEYS
        }
        focus_counter: Counter = Counter()

        for entry in matches:
            result = entry.get("result", "")
            if result == "W":
                wins += 1
            elif result == "D":
                draws += 1
            elif result == "L":
                losses += 1

            a, o = self._parse_score(entry.get("score", "0-0"))
            arsenal_goals += a
            opponent_goals += o

            # Model signals
            model_signals = entry.get("evaluation", {}).get("model_signals", {})
            for model_num, signal in model_signals.items():
                if model_num in model_distributions and signal in ("🟢", "🟡", "🔴"):
                    model_distributions[model_num][signal] += 1

            # Dimension signals (nested under evaluation.dimension_signals)
            dim_signals = entry.get("evaluation", {}).get("dimension_signals", {})
            for dim_key in DIMENSION_KEYS:
                signal = dim_signals.get(dim_key)
                if signal in ("🟢", "🟡", "🔴"):
                    dimension_distributions[dim_key][signal] += 1

            # Focus areas
            for fa in entry.get("predicted_plan", {}).get("focus_areas", []):
                focus_counter[fa] += 1

        count = len(matches)
        model_signal_dist = {
            m: {
                s: model_distributions[m].get(s, 0)
                for s in ("🟢", "🟡", "🔴")
            }
            for m in MODEL_NAMES
        }
        dimension_signal_dist = {
            k: {
                s: dimension_distributions[k].get(s, 0)
                for s in ("🟢", "🟡", "🔴")
            }
            for k in DIMENSION_KEYS
        }

        return {
            "count": count,
            "wins": wins,
            "draws": draws,
            "losses": losses,
            "avg_arsenal_score": round(arsenal_goals / count, 2),
            "avg_opponent_score": round(opponent_goals / count, 2),
            "model_signal_distribution": model_signal_dist,
            "dimension_signal_distribution": dimension_signal_dist,
            "most_common_focus_areas": [fa for fa, _ in focus_counter.most_common(3)],
        }

    def focus_area_effectiveness(
        self, focus_area: str, context: Optional[dict] = None
    ) -> dict:
        """
        How often a focus area appears and what the execution signal was.

        Args:
            focus_area: e.g. "控制中场"
            context: optional filter dict (same as similar_match_summary)

        Returns:
            dict with count, win_rate, avg_execution_signal.
        """
        all_entries = self.kb.get_all()
        if context:
            all_entries = self._filter_by_context(all_entries, context)

        count = 0
        wins = 0
        signal_sum = 0.0

        for entry in all_entries:
            focus_areas = entry.get("predicted_plan", {}).get("focus_areas", [])
            if focus_area not in focus_areas:
                continue

            count += 1
            if entry.get("result") == "W":
                wins += 1

            exec_signal = entry.get("evaluation", {}).get("dimension_signals", {}).get("execution")
            signal_sum += self._signal_value(exec_signal)

        if count == 0:
            return {"count": 0, "win_rate": 0.0, "avg_execution_signal": 0.0}

        return {
            "count": count,
            "win_rate": round(wins / count, 2),
            "avg_execution_signal": round(signal_sum / count, 2),
        }

    def model_trend(self, model_number: str, last_n: int = 10) -> dict:
        """
        Recent trend for a specific mental model.

        Args:
            model_number: "1" through "6"
            last_n: how many recent matches to consider for 'recent' distribution

        Returns:
            dict with recent_distribution and overall_distribution.
        """
        all_entries = self.kb.get_all()

        overall = Counter()
        recent_signals: list[str] = []

        for entry in all_entries:
            signal = entry.get("evaluation", {}).get("model_signals", {}).get(model_number)
            if signal in ("🟢", "🟡", "🔴"):
                overall[signal] += 1

        # For recent, take the last N entries (entries are stored chronologically)
        recent_entries = all_entries[-last_n:] if len(all_entries) > last_n else all_entries
        for entry in recent_entries:
            signal = entry.get("evaluation", {}).get("model_signals", {}).get(model_number)
            if signal in ("🟢", "🟡", "🔴"):
                recent_signals.append(signal)

        recent_counter = Counter(recent_signals)

        return {
            "model_number": model_number,
            "model_name": MODEL_NAMES.get(model_number, f"模型{model_number}"),
            "recent_distribution": {
                s: recent_counter.get(s, 0) for s in ("🟢", "🟡", "🔴")
            },
            "recent_count": len(recent_signals),
            "overall_distribution": {
                s: overall.get(s, 0) for s in ("🟢", "🟡", "🔴")
            },
            "overall_count": sum(overall.values()),
        }

    def format_for_prompt(self, context: dict, limit: int = 5) -> str:
        """
        Generate a Chinese markdown block for injection into LLM prompt.
        """
        summary = self.similar_match_summary(context, limit=limit)
        count = summary["count"]

        venue = context.get("venue", "未知")
        opp_quality = context.get("opponent_quality", "未知")
        stage = context.get("competition_stage", "未知")

        lines = ["## 历史模式参考", ""]

        if count == 0:
            lines.append(
                f"类似场景（{venue} vs {opp_quality} {stage}）：无历史数据"
            )
            return "\n".join(lines)

        lines.append(
            f"类似场景（{venue} vs {opp_quality} {stage}）：共 {count} 场"
        )
        lines.append(
            f"- 战绩：{summary['wins']}胜 {summary['draws']}平 {summary['losses']}负，"
            f"场均进球 {summary['avg_arsenal_score']}，"
            f"场均失球 {summary['avg_opponent_score']}"
        )
        lines.append("")

        # Model signals
        lines.append("心智模型历史表现：")
        model_dist = summary["model_signal_distribution"]
        for model_num in sorted(model_dist.keys()):
            name = MODEL_NAMES.get(model_num, f"模型{model_num}")
            dist = model_dist[model_num]
            lines.append(
                f"- 模型{model_num} {name}：🟢{dist['🟢']} 🟡{dist['🟡']} 🔴{dist['🔴']}"
            )

        lines.append("")

        # Common focus areas
        top_areas = summary["most_common_focus_areas"]
        if top_areas:
            lines.append(f"常见战术重点：{'、'.join(top_areas)}")

        return "\n".join(lines)
