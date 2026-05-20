"""Tool: prepare_evaluation — generate features, weak labels, and prompt from match/report JSON.

Accepts BOTH raw match JSON (from fetch_match_data) AND analyze report JSON
(from analyze_match).  Replaces the need for separate
build_structured_prompt / build_narrative_prompt_v2 commands.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional

import yaml


def _detect_input_shape(data: dict) -> str:
    """Return 'report' or 'match' based on key presence."""
    # Report from analyze_match has: match, stats, key_events, context, ...
    if "match" in data and "stats" in data:
        return "report"
    # Raw match from fetch_match_data has: fixture_id, home_team, away_team, ...
    if "fixture_id" in data and "home_team" in data:
        return "match"
    # Nested report (inside ok/report wrapper)
    if data.get("ok") and "report" in data:
        return "report"
    return "unknown"


def prepare_evaluation(data: dict, *, output_format: str = "json") -> dict | str:
    """Generate features, weak labels, rubric version, and prompt.

    Args:
        data: Raw match JSON or analyze report JSON.
        output_format: 'json' (default) or 'prompt' (prompt string only).

    Returns:
        dict with keys {features, weak_labels, rubric_version, prompt}
        or a prompt string when output_format == 'prompt'.
    """
    from src.features.extractor import FeatureExtractor, MatchFeatures
    from src.labels.weak_labeler import WeakLabeler, WeakLabels
    from src.evaluation.prompt_builder import PromptBuilder

    input_shape = _detect_input_shape(data)

    # Handle wrapped report (ok/report envelope)
    if input_shape == "report" and "report" in data and "ok" in data:
        report_data = data["report"]
    elif input_shape == "report":
        report_data = data
    else:
        report_data = None

    # ── Extract features ────────────────────────────────────────────
    try:
        if input_shape == "report":
            if report_data is None:
                return {"ok": False, "error": {"code": "EXTRACTION_FAILED", "message": "内部错误"}}
            features = FeatureExtractor.extract_from_report(report_data)
        elif input_shape == "match":
            features = FeatureExtractor().extract(data)
        else:
            return {
                "ok": False,
                "error": {
                    "code": "UNSUPPORTED_INPUT",
                    "message": (
                        "输入 JSON 格式无法识别。请提供 fetch_match_data 返回的原始比赛 JSON "
                        "或 analyze_match 返回的报告 JSON。至少需要 fixture_id/home_team 或 "
                        "match/stats 字段。"
                    ),
                },
            }
    except ValueError as e:
        return {
            "ok": False,
            "error": {
                "code": "EXTRACTION_FAILED",
                "message": str(e),
            },
        }

    # ── Validate features are not trivially empty ───────────────────
    features_dict = features.to_dict()
    if not features_dict.get("result") and not features_dict.get("arsenal_goals"):
        return {
            "ok": False,
            "error": {
                "code": "EMPTY_FEATURES",
                "message": (
                    "特征提取结果为空。请检查输入 JSON 是否包含足够的比赛数据"
                    "（至少需要 home_team、away_team、比分）。"
                ),
            },
        }

    # ── Compute weak labels ─────────────────────────────────────────
    weak_labels: WeakLabels = WeakLabeler().label(features)
    weak_labels_dict = {
        "model_signals": weak_labels.model_signals,
        "dimension_signals": weak_labels.dimension_signals,
        "overall_signal": weak_labels.overall_signal,
        "confidence": weak_labels.confidence,
        "evidence_refs": weak_labels.evidence_refs,
        "missing_data_penalty": weak_labels.missing_data_penalty,
        "weak_label_version": weak_labels.weak_label_version,
    }

    # ── Load rubric and build prompt ────────────────────────────────
    rubric_path = _find_rubric()
    rubric_version = "arteta_v1"
    if rubric_path:
        try:
            with open(rubric_path, encoding="utf-8") as f:
                rubric_data = yaml.safe_load(f)
            rubric_version = rubric_data.get("version", rubric_version)
        except Exception:
            rubric_data = {}
    else:
        rubric_data = {}

    # Get report context for calibration hints
    report_context = {}
    if report_data:
        report_context = report_data.get("context", {})

    # Try calibration hints (best effort)
    calibration_hints = _try_calibration_hints(report_context)

    if rubric_path or rubric_data:
        rubric_source: Any = rubric_data if rubric_data else rubric_path
        builder = PromptBuilder(
            rubric=rubric_source,  # type: ignore[arg-type]
            language="zh",
        )
        prompt = builder.build(
            features=features,
            weak_labels=weak_labels,
            calibration_hints=calibration_hints,
            skip_history=calibration_hints is None,
        )
    else:
        prompt = _fallback_prompt(features, weak_labels)

    if output_format == "prompt":
        return prompt

    return {
        "ok": True,
        "features": features_dict,
        "weak_labels": weak_labels_dict,
        "rubric_version": rubric_version,
        "features_version": "v2",
        "prompt": prompt,
    }


def _find_rubric() -> Optional[Path]:
    """Locate rubrics/arteta_v1.yaml relative to project root."""
    # Walk up from this file to find rubrics/
    candidates = [
        Path(__file__).resolve().parent.parent.parent / "rubrics" / "arteta_v1.yaml",
        Path.cwd() / "rubrics" / "arteta_v1.yaml",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _try_calibration_hints(context: dict, kb_path: Optional[str] = None) -> Optional[dict]:
    """Best-effort calibration hints from KB via CalibrationComputer.

    Returns the full CalibrationComputer output (confidence, sample_quality,
    guardrails, etc.) so prompt_builder can render guarded hints.
    Returns None on failure or empty context.
    """
    if not context:
        return None
    try:
        from src.evaluation.calibration import CalibrationComputer
        if kb_path is None:
            from src.paths import DEFAULT_KB_PATH
            kb_path = str(DEFAULT_KB_PATH)
        cc = CalibrationComputer(kb_path)
        return cc.build_hints(context, limit=5)
    except Exception:
        return None


def _fallback_prompt(features, weak_labels) -> str:
    """Minimal prompt when rubric is not found."""
    return (
        f"阿森纳 {features.arsenal_goals}-{features.opponent_goals} "
        f"{features.opponent_name} ({features.result})\n"
        f"弱标签基线: {weak_labels.overall_signal}\n"
        f"[注意: 未找到 rubric 文件，请检查 rubrics/arteta_v1.yaml]\n"
    )


if __name__ == "__main__":
    input_data = json.load(sys.stdin)
    fmt = "json"
    result = prepare_evaluation(input_data, output_format=fmt)
    if isinstance(result, str):
        print(result)
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))
