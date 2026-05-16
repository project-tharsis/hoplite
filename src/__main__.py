"""Hoplite tool dispatcher."""
import sys


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m src <tool_name>")
        print("Tools: fetch_match_data, analyze_match, build_narrative_prompt, build_card")
        print("       latest (original CLI, kept for backward compat)")
        sys.exit(1)

    tool = sys.argv[1]

    if tool == "fetch_match_data":
        from src.tools.fetch import fetch_match_data
        import json
        print(json.dumps(fetch_match_data(), indent=2, ensure_ascii=False))
    elif tool == "analyze_match":
        from src.tools.analyze import analyze_match
        import json
        data = json.load(sys.stdin)
        print(json.dumps(analyze_match(data), indent=2, ensure_ascii=False))
    elif tool == "build_narrative_prompt":
        from src.tools.prompt import build_narrative_prompt
        import json
        data = json.load(sys.stdin)
        print(build_narrative_prompt(data.get("report", data), data.get("search_context", "")))
    elif tool == "build_card":
        from src.tools.card import build_card
        import json
        data = json.load(sys.stdin)
        result = build_card(data.get("report", data), data.get("narrative", ""))
        print(json.dumps(result, ensure_ascii=False))
    elif tool == "latest":
        from src.cli import main as cli_main
        sys.argv = ["hoplite", "latest"]
        cli_main()
    else:
        print(f"Unknown tool: {tool}")
        sys.exit(1)


if __name__ == "__main__":
    main()
