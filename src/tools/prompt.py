"""Tool: build_narrative_prompt — inject raw data + Arteta framework for LLM evaluation."""

import json
import sys
from src.paths import PROMPTS_DIR


def _load_framework() -> str:
    """Read the canonical Arteta framework from prompts/arteta_framework.md."""
    framework_path = PROMPTS_DIR / "arteta_framework.md"
    if not framework_path.exists():
        print(f"[WARN] Framework file not found: {framework_path}", file=sys.stderr)
        return "## Arteta Framework (missing)\n核心评估框架文件未找到。请参考 SKILL.md。\n"
    return framework_path.read_text(encoding="utf-8")


_ARTETA_FRAMEWORK = _load_framework()


def build_narrative_prompt(report_json: dict, search_context: str = "",
                           kb_path: str = None,
                           skip_history: bool = False) -> str:
    """Build prompt: raw data → Arteta framework → LLM evaluation.
    
    Args:
        skip_history: If True, skip KB historical pattern injection.
                      Use for batch evaluation to ensure independence.
    """
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


if __name__ == "__main__":
    input_data = json.load(sys.stdin)
    report = input_data.get("report", input_data)
    search = input_data.get("search_context", "")
    skip = input_data.get("skip_history", False)
    prompt = build_narrative_prompt(report, search, skip_history=skip)
    print(prompt)
