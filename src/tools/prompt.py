"""Tool: build_narrative_prompt — generate objective third-person Chinese tactical prompt for LLM."""
import json
import sys


def build_narrative_prompt(report_json: dict, search_context: str = "") -> str:
    """Build prompt that instructs LLM to write objective third-person Chinese tactical analysis."""
    summary = report_json.get("one_line_summary", "")
    predicted_plan = report_json.get("predicted_plan", {})
    mental_model_results = report_json.get("mental_model_results", [])
    execution = report_json.get("execution", {})
    adjustment = report_json.get("adjustment", {})
    satisfaction = report_json.get("satisfaction", {})
    overall_signal = report_json.get("overall_signal", "")

    # Fallback: handle legacy report format with 'results' list
    results = report_json.get("results", [])
    if results and not mental_model_results:
        mental_model_results = [
            {
                "model_number": i + 1,
                "model_name": r.get("lens_name", "分析维度"),
                "signal": "🟢" if r.get("score", 0) >= 7 else "🟡" if r.get("score", 0) >= 5 else "🔴",
                "summary": r.get("summary", ""),
                "evidence": r.get("insights", []),
            }
            for i, r in enumerate(results)
        ]
    if not execution and results:
        execution = {"signal": "", "verdict": "执行评估不可用", "reasoning": "", "evidence": []}
    if not adjustment:
        adjustment = {"signal": "", "verdict": "调整评估不可用", "reasoning": "", "evidence": []}
    if not satisfaction:
        satisfaction = {"signal": "", "verdict": "满意度评估不可用", "reasoning": "", "evidence": []}

    prompt = f"""你是足球战术分析师，以中文撰写阿森纳赛后复盘。保持客观第三人称，不使用"我们"或"我"。

比赛: {summary}

赛前预测方向:
"""
    if predicted_plan:
        for k, v in predicted_plan.items():
            prompt += f"- {k}: {v}\n"
    else:
        prompt += "赛前预测信息未提供\n"

    prompt += f"""
战术评估:
综合信号: {overall_signal}
赛前决策执行: {execution.get('verdict', '')} {execution.get('signal', '')}
赛中调整: {adjustment.get('verdict', '')} {adjustment.get('signal', '')}
结果满意度: {satisfaction.get('verdict', '')} {satisfaction.get('signal', '')}

Arteta心智模型评估:
"""
    for r in mental_model_results:
        prompt += f"\n模型{r.get('model_number', '?')}. {r.get('model_name', '')}: {r.get('signal', '')}"
        prompt += f"\n  {r.get('summary', '')}"
        for ev in r.get("evidence", [])[:2]:
            prompt += f"\n  - {ev}"

    if search_context:
        prompt += f"\n\n外部参考信息:\n{search_context[:1500]}\n"

    prompt += """
写作要求:
- 短句分行，口语化像聊天
- 中英文术语不加空格（e.g. "rest-defence", "xG", "inverted-fullback"）
- 分析为什么发生，不是只描述什么
- 引用Arteta的战术偏好但不扮演他
- 300-400字中文
- 按以下结构组织：
  1. 总体判断（1-2句，基于综合信号和三维度）
  2. 战术执行（赛前决策执行度 + 预测方向匹配度）
  3. 关键节点（心智模型中的evidence/insights）
  4. 改进方向（信号为🔴或🟡的模型）
  5. 一句话判决（结尾）

只写复盘正文，不加标题或标记。
"""
    return prompt


if __name__ == "__main__":
    input_data = json.load(sys.stdin)
    report = input_data.get("report", input_data)
    search = input_data.get("search_context", "")
    prompt = build_narrative_prompt(report, search)
    print(prompt)
