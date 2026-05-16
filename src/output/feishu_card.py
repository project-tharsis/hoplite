import json
import subprocess
from src.report import MatchReport


class FeishuCardBuilder:
    """Builds Feishu interactive card from v4 MatchReport or report dict."""

    def __init__(self, chat_id: str):
        self.chat_id = chat_id

    def build_match_card_with_narrative(
        self,
        report_json: dict,
        narrative: str = "",
        doc_url: str = "",
    ) -> dict:
        """Build feishu v2.0 card from v4 report JSON."""
        summary = report_json.get("one_line_summary", "")
        stats = report_json.get("stats", {})
        predicted_plan = report_json.get("predicted_plan", {})
        context = report_json.get("context", {})
        key_events = report_json.get("key_events", [])
        set_pieces = report_json.get("set_pieces", {})
        sub_impact = report_json.get("sub_impact", [])

        # LLM-produced fields (may or may not be present)
        model_signals = report_json.get("model_signals", {})
        dimension_signals = report_json.get("dimension_signals", {})

        # Build header
        score_info = stats.get("score", {})
        score_text = f"{score_info.get('arsenal', '?')}-{score_info.get('opponent', '?')}"

        # Determine overall signal from dimension_signals if available
        overall_signal = self._compute_overall_signal(dimension_signals)
        emoji = overall_signal

        clean_summary = summary
        for sig in ("🟢 ", "🟡 ", "🔴 "):
            if clean_summary.startswith(sig):
                clean_summary = clean_summary[len(sig):]
                break

        card = {
            "schema": "2.0",
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"{emoji} {clean_summary}"},
                "template": "blue",
            },
            "body": {
                "elements": []
            },
        }

        elements = card["body"]["elements"]

        # Stats line
        stats_md = self._build_stats_line(stats)
        if stats_md:
            elements.append({"tag": "markdown", "content": stats_md})

        # Dimension signals (if LLM produced them)
        if dimension_signals:
            elements.append({"tag": "hr"})
            elements.append({
                "tag": "markdown",
                "content": self._build_dimension_line(dimension_signals),
            })

        # Model signals (if LLM produced them)
        if model_signals:
            elements.append({"tag": "hr"})
            elements.append({
                "tag": "markdown",
                "content": self._build_models_summary(model_signals),
            })

        # Predicted plan (if present)
        if predicted_plan and predicted_plan.get("focus_areas"):
            elements.append({"tag": "hr"})
            elements.append({
                "tag": "markdown",
                "content": self._build_predicted_plan(predicted_plan),
            })

        # Narrative
        if narrative:
            elements.append({"tag": "hr"})
            elements.append({
                "tag": "markdown",
                "content": narrative[:800],
            })

        # Doc URL button
        if doc_url:
            elements.append({"tag": "hr"})
            elements.append({
                "tag": "action",
                "actions": [{
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "📄 完整复盘"},
                    "url": doc_url,
                    "type": "default",
                }],
            })

        return card

    def _compute_overall_signal(self, dimension_signals: dict) -> str:
        """Compute overall signal from dimension signals via majority vote."""
        if not dimension_signals:
            return "🟡"
        signals = list(dimension_signals.values())
        green_count = signals.count("🟢")
        red_count = signals.count("🔴")
        if green_count >= 2:
            return "🟢"
        if red_count >= 2:
            return "🔴"
        return "🟡"

    def _build_stats_line(self, stats: dict) -> str:
        """Build a one-line stats summary."""
        score = stats.get("score", {})
        xg = stats.get("xg", {})
        arsenal_score = score.get("arsenal", "?")
        opp_score = score.get("opponent", "?")
        parts = [f"**比分**: {arsenal_score}-{opp_score}"]
        if xg.get("arsenal") is not None:
            parts.append(f"**xG**: {xg.get('arsenal', '?')}-{xg.get('opponent', '?')}")
        return " | ".join(parts)

    def _build_dimension_line(self, dimension_signals: dict) -> str:
        """Build dimension signals line from v4 format."""
        exe = dimension_signals.get("execution", "")
        adj = dimension_signals.get("adjustment", "")
        sat = dimension_signals.get("satisfaction", "")
        return (
            f"综合评估: "
            f"执行{exe} "
            f"调整{adj} "
            f"满意{sat}"
        )

    def _build_models_summary(self, model_signals: dict) -> str:
        """Build model signals summary from v4 format (dict of {number: signal})."""
        model_names = {
            "1": "文化标准",
            "2": "比赛控制",
            "3": "防守身份",
            "4": "边际收益",
            "5": "能力叠加",
            "6": "角色清晰",
        }
        lines = ["**🧠 Arteta心智模型**"]
        for num in sorted(model_signals.keys()):
            signal = model_signals[num]
            name = model_names.get(num, f"模型{num}")
            lines.append(f"{signal} {name}")
        return "\n".join(lines)

    def _build_predicted_plan(self, predicted_plan: dict) -> str:
        """Build predicted plan section."""
        parts = ["**📋 赛前预测方向**"]
        focus = predicted_plan.get("focus_areas", [])
        if focus:
            parts.append(f"- 战略重点: {', '.join(focus)}")
        approach = predicted_plan.get("likely_approach", "")
        if approach:
            parts.append(f"- 可能策略: {approach}")
        battles = predicted_plan.get("key_battles", [])
        if battles:
            parts.append(f"- 关键对决: {', '.join(battles)}")
        return "\n".join(parts)

    def send(self, report_or_card) -> bool:
        """Build card, save to temp file, send via lark-cli.

        Accepts either MatchReport (old) or card dict (new).
        """
        if isinstance(report_or_card, MatchReport):
            card = self.build_match_card_with_narrative(report_or_card.to_dict())
        elif isinstance(report_or_card, dict):
            card = report_or_card
        else:
            raise TypeError(
                "send() expects MatchReport or dict, got "
                f"{type(report_or_card).__name__}"
            )

        card_path = "/tmp/hoplite_card_v4.json"
        with open(card_path, "w", encoding="utf-8") as f:
            json.dump(card, f, ensure_ascii=False)

        result = subprocess.run(
            [
                "bash", "-c",
                f"jq -c '.' {card_path} > {card_path}.compact && "
                f"lark-cli im messages-send --as bot --chat-id {self.chat_id} "
                f"--msg-type interactive --content \"$(cat {card_path}.compact)\""
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        return "ok" in result.stdout.lower() or result.returncode == 0
