import json
import subprocess
from src.report import MatchReport


class FeishuCardBuilder:
    """Builds Feishu interactive card from v3 MatchReport or report dict."""

    def __init__(self, chat_id: str):
        self.chat_id = chat_id

    def build_match_card_with_narrative(
        self,
        report_json: dict,
        narrative: str = "",
        doc_url: str = "",
    ) -> dict:
        """Build feishu v2.0 card from v3 report JSON."""
        summary = report_json.get("one_line_summary", "")
        overall_signal = report_json.get("overall_signal", "🟡")
        mental_model_results = report_json.get("mental_model_results", [])
        execution = report_json.get("execution", {})
        adjustment = report_json.get("adjustment", {})
        satisfaction = report_json.get("satisfaction", {})

        emoji = overall_signal
        # Strip emoji from summary if it already starts with one (one_line_summary includes it)
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
                "elements": [
                    {
                        "tag": "markdown",
                        "content": self._build_dimension_line(
                            execution, adjustment, satisfaction
                        ),
                    },
                    {"tag": "hr"},
                    {
                        "tag": "markdown",
                        "content": self._build_models_summary(mental_model_results),
                    },
                ]
            },
        }

        if narrative:
            card["body"]["elements"].append({"tag": "hr"})
            card["body"]["elements"].append({
                "tag": "markdown",
                "content": narrative[:800],
            })

        if doc_url:
            card["body"]["elements"].append({"tag": "hr"})
            card["body"]["elements"].append({
                "tag": "action",
                "actions": [{
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "📄 完整复盘"},
                    "url": doc_url,
                    "type": "default",
                }],
            })

        return card

    def _build_dimension_line(
        self,
        execution: dict,
        adjustment: dict,
        satisfaction: dict,
    ) -> str:
        return (
            f"综合评估: "
            f"执行{execution.get('signal', '')} "
            f"调整{adjustment.get('signal', '')} "
            f"满意{satisfaction.get('signal', '')}"
        )

    def _build_models_summary(self, results: list) -> str:
        lines = ["**🧠 Arteta心智模型**"]
        for r in results[:4]:
            signal = r.get("signal", "")
            model_name = r.get("model_name", "")
            summary = r.get("summary", "")[:50]
            lines.append(f"{signal} {model_name}: {summary}")
        return "\n".join(lines)

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

        card_path = "/tmp/hoplite_card_v3.json"
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
