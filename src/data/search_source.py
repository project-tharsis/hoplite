"""Query builders for Brave search — match reports and trend analysis."""


def build_match_report_query(opponent: str, date: str = "") -> str:
    """Build a Brave search query for post-match tactical analysis."""
    query = f"Arsenal vs {opponent} tactical analysis post-match report"
    if date:
        query += f" {date}"
    return query


def build_trend_query(topic: str) -> str:
    """Build a Brave search query for season trend analysis by topic."""
    topics = {
        "inverted_fullback": "Arsenal inverted fullback tactical evolution 2025 season Arteta",
        "set_pieces": "Arsenal set piece goals Nicolas Jover analysis 2025",
        "pressing": "Arsenal high press pressing triggers tactical analysis 2025",
        "build_up": "Arsenal build-up structure positional play analysis 2025",
        "rest_defence": "Arsenal rest-defence counter-attack prevention analysis 2025",
    }
    return topics.get(topic, f"Arsenal {topic} tactical analysis 2025 season")
