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
    """Analyze the most recent Arsenal match."""
    from src.data.football_data import FootballDataClient
    from src.normalizer import normalize_football_data_match
    from src.report import ReportOrchestrator
    from src.output.feishu_card import FeishuCardBuilder
    
    print("Fetching latest Arsenal match from football-data.org...")
    fd = FootballDataClient(token=config["data_sources"]["football_data"]["token"])
    matches = fd.get_team_matches(
        team_id=config["arsenal"]["team_id_football_data"],
        limit=1
    )
    
    if not matches:
        print("No recent matches found.")
        sys.exit(1)
    
    raw = matches[0]
    match = normalize_football_data_match(raw)
    
    print(f"Match: {match.home_team} vs {match.away_team} ({match.date.strftime('%Y-%m-%d')})")
    print("Generating tactical report...")
    
    orchestrator = ReportOrchestrator()
    report = orchestrator.generate(match)
    
    print(report.one_line_summary)
    
    # Send to Feishu
    chat_id = config["feishu"]["hoplite_chat_id"]
    builder = FeishuCardBuilder(chat_id=chat_id)
    success = builder.send(report)
    print(f"Card sent: {'✅' if success else '❌'}")


def cmd_analyze(config: dict, fixture_id: int) -> None:
    """Analyze a specific match by API-Football fixture ID."""
    from src.data.api_football import ApiFootballClient
    from src.data.football_data import FootballDataClient
    from src.normalizer import normalize_football_data_match, merge_match_data
    from src.data.understat import UnderstatClient
    from src.report import ReportOrchestrator
    from src.output.feishu_card import FeishuCardBuilder
    
    print(f"Fetching match fixture #{fixture_id}...")
    
    # Try football-data.org first for match identity
    fd = FootballDataClient(token=config["data_sources"]["football_data"]["token"])
    # ... (simplified — use API-Football for events/stats)
    af = ApiFootballClient(key=config["data_sources"]["api_football"]["key"])
    events = af.get_match_events(fixture_id=fixture_id, team_id=config["arsenal"]["team_id_api_football"])
    lineups = af.get_match_lineups(fixture_id=fixture_id)
    
    print(f"Loaded {len(events)} events, {len(lineups)} lineups")
    print("Full analyze flow: fetch match data from all sources, normalize, generate report, send card.")
    print("(Requires actual API tokens in config.yaml for full operation)")


def main():
    parser = argparse.ArgumentParser(
        description="Hoplite — Arsenal tactical analysis engine",
        prog="hoplite"
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # 'latest' command
    subparsers.add_parser("latest", help="Analyze the most recent Arsenal match")
    
    # 'analyze' command
    analyze_parser = subparsers.add_parser("analyze", help="Analyze a specific match")
    analyze_parser.add_argument("--fixture-id", type=int, required=True, help="API-Football fixture ID")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    config = load_config()
    
    if args.command == "latest":
        cmd_latest(config)
    elif args.command == "analyze":
        cmd_analyze(config, args.fixture_id)


if __name__ == "__main__":
    main()
