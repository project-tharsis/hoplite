import pytest
from src.data.search_source import build_match_report_query, build_trend_query


def test_build_match_report_query_with_date():
    query = build_match_report_query("Manchester City", "2025-05-10")
    assert "Arsenal" in query
    assert "Manchester City" in query
    assert "2025-05-10" in query
    assert "tactical" in query


def test_build_match_report_query_without_date():
    query = build_match_report_query("Chelsea")
    assert "Arsenal" in query
    assert "Chelsea" in query
    assert "tactical" in query


def test_build_trend_query_known_topic():
    query = build_trend_query("set_pieces")
    assert "set piece" in query.lower()
    assert "Jover" in query


def test_build_trend_query_unknown_topic():
    query = build_trend_query("something_unknown")
    assert "something_unknown" in query
    assert "Arsenal" in query
