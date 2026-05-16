"""Tool: build_narrative_prompt — generate Arteta-style tactical prompt for LLM."""
import json
import sys


def build_narrative_prompt(report_json: dict, search_context: str = "") -> str:
    """Build prompt that instructs LLM to write Arteta-perspective narrative."""
    results = report_json.get("results", [])
    summary = report_json.get("one_line_summary", "")

    prompt = f"""You are a football tactics analyst writing in the voice of a coach deeply familiar with Mikel Arteta's system. Write a concise post-match tactical analysis (300-400 words).

MATCH: {summary}

TACTICAL LENS ANALYSIS:
"""
    for r in results:
        prompt += f"\n## {r['lens_name']} (Score: {r['score']:.1f}/10)\n{r['summary']}\n"
        for insight in r.get("insights", []):
            prompt += f"- {insight}\n"

    if search_context:
        prompt += f"\nPOST-MATCH ANALYSIS CONTEXT:\n{search_context[:2000]}\n"

    prompt += """
WRITING STYLE:
- Short paragraphs, no academic language
- Football terminology: "inverted fullback", "rest-defence", "overload-to-isolate", "double pivot"
- Analyze WHY things happened, not just WHAT
- Reference Arteta's known tactical preferences when relevant
- End with a one-sentence verdict

Write only the analysis. No headers, no meta-commentary.
"""
    return prompt


if __name__ == "__main__":
    input_data = json.load(sys.stdin)
    report = input_data.get("report", input_data)
    search = input_data.get("search_context", "")
    prompt = build_narrative_prompt(report, search)
    print(prompt)
