"""Hoplite CLI entry point."""
import argparse
import yaml
import sys
from pathlib import Path


def load_config() -> dict:
    """Load hoplite config from config.yaml."""
    config_path = Path(__file__).resolve().parent.parent / "config.yaml"
    if not config_path.exists():
        print(f"Error: config.yaml not found at {config_path}")
        print("Copy config.example.yaml to config.yaml and fill in tokens.")
        sys.exit(1)
    with open(config_path) as f:
        return yaml.safe_load(f)


def cmd_latest(config: dict) -> None:
    """Stub — v3 code removed. Use the current pipeline."""
    print(
        "The 'latest' command has been removed in v4.\n"
        "Use the current two-step pipeline instead:\n"
        "\n"
        "  # Step 1: Fetch\n"
        "  python -m src fetch_match_data > match.json\n"
        "\n"
        "  # Step 2: Analyze (if fetch succeeded)\n"
        "  python -m src analyze_match < match.json\n"
    )


def cmd_analyze(config: dict, fixture_id: int) -> None:
    """Stub — v3 code removed. Use the current pipeline."""
    print(
        "The 'analyze' command has been removed in v4.\n"
        "Use the current two-step pipeline instead:\n"
        "\n"
        "  # Step 1: Fetch\n"
        "  python -m src fetch_match_data > match.json\n"
        "\n"
        "  # Step 2: Analyze (if fetch succeeded)\n"
        "  python -m src analyze_match < match.json\n"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Hoplite — Arsenal tactical analysis engine",
        prog="hoplite"
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # 'latest' command
    subparsers.add_parser("latest", help="Analyze the most recent Arsenal match (deprecated)")
    
    # 'analyze' command
    analyze_parser = subparsers.add_parser("analyze", help="Analyze a specific match (deprecated)")
    analyze_parser.add_argument("--fixture-id", type=int, help="API-Football fixture ID")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    # No config needed for stub commands
    if args.command == "latest":
        cmd_latest({})
    elif args.command == "analyze":
        cmd_analyze({}, args.fixture_id or 0)


if __name__ == "__main__":
    main()
