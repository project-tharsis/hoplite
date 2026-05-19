"""Tool: review_evaluation — write human review override into KB entry."""

import json
import sys
from datetime import datetime

import src.paths as paths
from src.evaluation.knowledge import KnowledgeBase


def review_evaluation(input_data: dict) -> dict:
    """Apply a human review override to an existing KB entry.

    Input:
        {
            "match_id": "123",
            "reviewer": "shuo",
            "review_status": "corrected",
            "corrected_overall_signal": "🟡",
            "corrected_model_signals": {"1": "🟢", ...},
            "corrected_dimension_signals": {"execution": "🟡", ...},
            "comments": "Win was useful but control was mixed."
        }

    Returns:
        {"ok": true, "entry": {...}} on success
        {"ok": false, "error": {"code": "...", "message": "..."}} on failure
    """
    match_id = input_data.get("match_id")
    if not match_id:
        return {
            "ok": False,
            "error": {"code": "MISSING_FIELD", "message": "match_id is required"},
        }

    reviewer = input_data.get("reviewer", "")
    review_status = input_data.get("review_status", "corrected")
    corrected_overall_signal = input_data.get("corrected_overall_signal")
    corrected_model_signals = input_data.get("corrected_model_signals", {})
    corrected_dimension_signals = input_data.get("corrected_dimension_signals", {})
    comments = input_data.get("comments", "")

    kb = KnowledgeBase(str(paths.DEFAULT_KB_PATH))
    entries = kb.get_all()

    # Find matching entry
    target_index = None
    for i, entry in enumerate(entries):
        if str(entry.get("match_id")) == str(match_id):
            target_index = i
            break

    if target_index is None:
        return {
            "ok": False,
            "error": {
                "code": "NOT_FOUND",
                "message": f"No KB entry found with match_id={match_id}",
            },
        }

    # Build human_override — preserve original weak_labels and evaluation
    human_override = {
        "reviewer": reviewer,
        "review_status": review_status,
        "corrected_overall_signal": corrected_overall_signal,
        "corrected_model_signals": corrected_model_signals,
        "corrected_dimension_signals": corrected_dimension_signals,
        "comments": comments,
        "reviewed_at": datetime.now().isoformat(timespec="seconds"),
    }

    entries[target_index]["human_override"] = human_override

    # Write back the entire KB
    kb._write(entries)

    return {"ok": True, "entry": entries[target_index]}


if __name__ == "__main__":
    data = json.load(sys.stdin)
    result = review_evaluation(data)
    print(json.dumps(result, indent=2, ensure_ascii=False))
