import json
import subprocess
from src.report import MatchReport


class FeishuCardBuilder:
    """Builds Feishu interactive card from MatchReport."""
    
    def __init__(self, chat_id: str):
        self.chat_id = chat_id
    
    def build_match_card(self, report: MatchReport) -> dict:
        """Build a feishu v2.0 interactive card for a match report."""
        m = report.match
        emoji = "🟢" if m.result == "W" else ("🟡" if m.result == "D" else "🔴")
        
        card = {
            "schema": "2.0",
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"{emoji} {m.home_team} {m.home_score}-{m.away_score} {m.away_team}"},
                "template": "blue"
            },
            "body": {
                "elements": [
                    {
                        "tag": "markdown",
                        "content": f"**{m.competition}** · {m.date.strftime('%Y-%m-%d')} · Overall: **{report.overall_score:.1f}/10**"
                    },
                    {"tag": "hr"},
                    self._build_lens_score_table(report),
                    {"tag": "hr"},
                    self._build_key_moments(report),
                ]
            }
        }
        return card
    
    def _build_lens_score_table(self, report: MatchReport) -> dict:
        """Build the 6-lens score summary table."""
        rows = []
        for r in report.results:
            stars = "⭐" * int(r.score // 2)
            rows.append({
                "lens": r.lens_name,
                "score": f"{stars}{r.score:.1f}",
                "summary": r.summary[:80] + ("..." if len(r.summary) > 80 else "")
            })
        
        return {
            "tag": "table",
            "columns": [
                {"name": "lens", "display_name": "Dimension", "data_type": "text"},
                {"name": "score", "display_name": "Rating", "data_type": "text"},
                {"name": "summary", "display_name": "Key Point", "data_type": "lark_md"},
            ],
            "rows": rows
        }
    
    def _build_key_moments(self, report: MatchReport) -> dict:
        """Build key match moments section."""
        moments = []
        for r in report.results:
            for km in r.key_moments[:1]:
                moments.append(f"**{r.lens_name}**: {km}")
        
        return {
            "tag": "markdown",
            "content": "**🔑 Key Moments**\n" + "\n".join(f"• {m}" for m in moments[:6])
        }
    
    def send(self, report: MatchReport) -> bool:
        """Build card, save to temp file, send via lark-cli."""
        card = self.build_match_card(report)
        card_path = f"/tmp/hoplite_card_{report.match.fixture_id}.json"
        
        with open(card_path, "w", encoding="utf-8") as f:
            json.dump(card, f, ensure_ascii=False)
        
        result = subprocess.run([
            "bash", "-c",
            f"jq -c '.' {card_path} > {card_path}.compact && "
            f"lark-cli im +messages-send --as bot --chat-id {self.chat_id} "
            f"--msg-type interactive --content \"$(cat {card_path}.compact)\""
        ], capture_output=True, text=True, timeout=10)
        
        return "ok" in result.stdout.lower() or result.returncode == 0
