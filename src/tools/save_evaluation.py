"""Tool: save_evaluation — validate LLM output and save to KB."""
import json
import sys
import src.paths as paths
from src.evaluation.knowledge import KnowledgeBase
from src.evaluation.llm_result import validate_llm_result


def save_evaluation(
    report_json: dict,
    evaluation: dict,
    weak_labels: dict | None = None,
    versions: dict | None = None,
    features: dict | None = None,
    evaluation_metadata: dict | None = None,
) -> dict:
    """Validate LLM evaluation and persist to KB.

    Input:
        {
            "report": {...report dict...},
            "evaluation": {
                "overall_signal": "🟢",
                "model_signals": {"1": "🟢", ...},
                "dimension_signals": {"execution": "🟢", ...},
                "narrative": "..."
            },
            "features": {...optional features dict...},
            "weak_labels": {...optional weak labels dict...},
            "versions": {
                "features": "v1",
                "weak_label": "v1",
                "rubric": "arteta_v1",
                "prompt_builder": "v1"
            },
            "evaluation_metadata": {...optional metadata dict...}
        }

    Returns:
        {"ok": true/false, "message": "...", "entry": {...}}
    """
    # Validate (metadata must NOT be passed to validate_llm_result)
    try:
        validated = validate_llm_result(evaluation, strict=True)
    except ValueError as e:
        return {"ok": False, "error": {"code": "VALIDATION_FAILED", "message": str(e)}}

    # Extract match info from report
    match_data = report_json.get("match", report_json)
    context = report_json.get("context", {})

    # Preserve existing features if none supplied (prevent wiping on re-save)
    effective_features = features
    if not effective_features:
        match_id = str(match_data.get("fixture_id", ""))
        kb = KnowledgeBase(str(paths.DEFAULT_KB_PATH))
        for existing in kb.get_all():
            if existing.get("match_id") == match_id:
                effective_features = existing.get("features", {})
                break

    # Build KB entry matching the schema
    eval_dict: dict = {
        "source": "llm",
        "confidence": validated.get("confidence"),
        "model_signals": validated["model_signals"],
        "dimension_signals": validated["dimension_signals"],
        "overall_signal": validated["overall_signal"],
        "narrative": validated.get("narrative", ""),
        "evidence": validated.get("evidence", {}),
        "missing_or_weak_evidence": validated.get(
            "missing_or_weak_evidence", []
        ),
        "weak_label_disagreements": validated.get(
            "weak_label_disagreements", []
        ),
    }

    # Attach metadata only when explicitly provided (backward compat)
    if evaluation_metadata is not None:
        eval_dict["metadata"] = evaluation_metadata

    entry = {
        "match_id": str(match_data.get("fixture_id", "")),
        "timestamp": match_data.get("date", ""),
        "opponent": context.get("opponent", ""),
        "score": f"{match_data.get('arsenal_score', '?')}-{match_data.get('opponent_score', '?')}",
        "result": match_data.get("result", ""),
        "competition": match_data.get("competition", ""),
        "pre_match_context": context,
        "predicted_plan": report_json.get("predicted_plan", {}),
        "features": effective_features or {},
        "evaluation": eval_dict,
        "weak_labels": weak_labels or {},
        "features_version": (versions or {}).get("features", "v2"),
        "weak_label_version": (versions or {}).get("weak_label", "v1"),
        "rubric_version": (versions or {}).get("rubric", "v1"),
        "prompt_builder_version": (versions or {}).get("prompt_builder", "v1"),
        "human_override": None,
    }

    # Save with upsert
    kb = KnowledgeBase(str(paths.DEFAULT_KB_PATH))
    kb.upsert_entry(entry, key="match_id")

    return {"ok": True, "message": "Evaluation saved to KB", "entry": entry}


if __name__ == "__main__":
    input_data = json.load(sys.stdin)
    result = save_evaluation(
        input_data.get("report", {}),
        input_data.get("evaluation", {}),
        input_data.get("weak_labels"),
        input_data.get("versions"),
        input_data.get("features"),
        input_data.get("evaluation_metadata"),
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
