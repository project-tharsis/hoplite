"""Tool: build_narrative_prompt — inject raw data + Arteta framework for LLM evaluation.

Backward-compatible wrapper. When new data sources (MatchFeatures, WeakLabels, rubric)
are provided, delegates to PromptBuilder for structured output.
Otherwise falls back to the original monolithic prompt path.
"""

import json
import sys
from typing import Optional, Union
from pathlib import Path

from src.paths import PROMPTS_DIR


def _load_framework() -> str:
    """Read the canonical Arteta framework from prompts/arteta_framework.md."""
    framework_path = PROMPTS_DIR / "arteta_framework.md"
    if not framework_path.exists():
        print(f"[WARN] Framework file not found: {framework_path}", file=sys.stderr)
        return "## Arteta Framework (missing)\n核心评估框架文件未找到。请参考 SKILL.md。\n"
    return framework_path.read_text(encoding="utf-8")


_ARTETA_FRAMEWORK = _load_framework()


def build_narrative_prompt(
    report_json: dict,
    search_context: str = "",
    kb_path: str = None,
    skip_history: bool = False,
    # ── New optional parameters (Phase 5) ────────────────────────────
    features=None,
    weak_labels=None,
    rubric: Optional[Union[str, Path, dict]] = None,
    calibration_hints: Optional[dict] = None,
    language: str = "zh",
) -> str:
    """Build prompt: raw data → Arteta framework → LLM evaluation.

    Backward-compatible: when new structured inputs (features, weak_labels, rubric)
    are provided, delegates to PromptBuilder for modular output.
    Otherwise uses the original monolithic prompt path.

    Args:
        report_json: Original match report dict (legacy path).
        search_context: External tactical analysis text.
        kb_path: Path to knowledge base JSON.
        skip_history: If True, skip KB historical pattern injection.
        features: MatchFeatures instance (new path).
        weak_labels: WeakLabels instance (new path).
        rubric: Path to YAML rubric or pre-loaded dict (new path).
        calibration_hints: Historical calibration dict (new path).
        language: Output language code ("zh" or "en").
    """
    # ── New path: delegate to PromptBuilder ───────────────────────────
    if features is not None and weak_labels is not None and rubric is not None:
        from src.evaluation.prompt_builder import PromptBuilder

        # If calibration_hints not provided, try to compute from KB
        if calibration_hints is None and not skip_history:
            calibration_hints = _try_load_calibration_hints(
                report_json.get("context", {}), kb_path
            )

        builder = PromptBuilder(rubric=rubric, language=language)
        return builder.build(
            features=features,
            weak_labels=weak_labels,
            calibration_hints=calibration_hints,
            skip_history=skip_history,
            search_context=search_context,
        )

    # ── Legacy path: original monolithic prompt ───────────────────────
    summary = report_json.get("one_line_summary", "")
    predicted_plan = report_json.get("predicted_plan", {})
    context = report_json.get("context", {})
    stats = report_json.get("stats", {})
    key_events = report_json.get("key_events", [])
    set_pieces = report_json.get("set_pieces", {})
    sub_impact = report_json.get("sub_impact", [])

    # Inject historical patterns from KB (skipped for batch evaluation)
    historical_block = ""
    if not skip_history:
        if kb_path is None:
            from src.paths import DEFAULT_KB_PATH
            kb_path = str(DEFAULT_KB_PATH)

        try:
            from src.evaluation.patterns import PatternComputer
            if context:
                pc = PatternComputer(kb_path)
                historical_block = pc.format_for_prompt(context, limit=5)
                if historical_block:
                    historical_block = f"\n{historical_block}\n"
        except FileNotFoundError:
            historical_block = "\n## 历史模式参考\n\n无历史数据\n\n"
            print("[WARN] KB file not found, skipping historical injection", file=sys.stderr)
        except Exception as e:
            print(f"[WARN] Failed to load KB patterns: {e}", file=sys.stderr)

    prompt = f"""你是足球战术分析师，需要基于原始比赛数据，用 Arteta 的6个心智模型框架评估阿森纳的表现，然后撰写中文复盘。

## 比赛基本信息
{summary}

## 赛前预测方向
- 战略重点: {predicted_plan.get('focus_areas', [])}
- 可能策略: {predicted_plan.get('likely_approach', '')}
- 关键对决: {predicted_plan.get('key_battles', [])}
- 预期换人: {predicted_plan.get('expected_subs', '')}

## 比赛背景
- 对手等级: {context.get('opponent_quality', '')}
- 场地: {context.get('venue', '')}  
- 赛事阶段: {context.get('competition_stage', '')}
- 伤病: {context.get('injury_situation', '')}

## 原始数据
```json
{json.dumps(stats, indent=2, ensure_ascii=False)}
```

## 关键事件
```json
{json.dumps(key_events[:20], indent=2, ensure_ascii=False)}
```

## 定位球数据
```json
{json.dumps(set_pieces, indent=2, ensure_ascii=False)}
```

## 换人影响
```json
{json.dumps(sub_impact, indent=2, ensure_ascii=False)}
```

{historical_block}

{_ARTETA_FRAMEWORK}
"""
    
    if search_context:
        prompt += f"\n\n## 外部战术分析参考\n{search_context[:1000]}\n"
    
    return prompt


def _try_load_calibration_hints(context: dict, kb_path: Optional[str] = None) -> Optional[dict]:
    """Try to load calibration hints from KB. Returns None on failure."""
    if not context:
        return None
    try:
        from src.evaluation.patterns import PatternComputer
        path = kb_path
        if path is None:
            from src.paths import DEFAULT_KB_PATH
            path = str(DEFAULT_KB_PATH)
        pc = PatternComputer(path)
        return pc.similar_match_summary(context, limit=5)
    except Exception:
        return None


if __name__ == "__main__":
    input_data = json.load(sys.stdin)
    report = input_data.get("report", input_data)
    search = input_data.get("search_context", "")
    skip = input_data.get("skip_history", False)
    prompt = build_narrative_prompt(report, search, skip_history=skip)
    print(prompt)
