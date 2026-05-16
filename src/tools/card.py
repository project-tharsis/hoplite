"""Tool: build_card — build Feishu interactive card from report + narrative."""
import json
import sys
from pathlib import Path
from src.output.feishu_card import FeishuCardBuilder


def build_card(report_json: dict, narrative: str = "", chat_id: str = None) -> dict:
    """Build Feishu v2.0 card. Saves to temp file, returns path + card dict."""
    builder = FeishuCardBuilder(chat_id=chat_id or "oc_placeholder")

    # Build card JSON without sending
    card = builder.build_match_card_with_narrative(report_json, narrative)

    # Save to temp
    temp_path = f"/tmp/hoplite_card_{report_json.get('fixture_id', 'latest')}.json"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(card, f, ensure_ascii=False)

    return {"card_path": temp_path, "card": card}


if __name__ == "__main__":
    input_data = json.load(sys.stdin)
    report = input_data.get("report", input_data)
    narrative = input_data.get("narrative", "")
    result = build_card(report, narrative)
    print(json.dumps({"card_path": result["card_path"]}, ensure_ascii=False))
