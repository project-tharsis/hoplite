from datetime import datetime
from src.models.match import Match
from src.analysis.build_up import BuildUpLens
from src.analysis.pressing import PressingLens
from src.analysis.rest_defence import RestDefenceLens
from src.analysis.overload import OverloadLens


def make_match():
    return Match(
        fixture_id=1, date=datetime(2025, 5, 1), competition="PL",
        home_team="Arsenal", away_team="Chelsea",
        home_score=3, away_score=1,
    )


def test_build_up_basic():
    result = BuildUpLens().analyze(make_match())
    assert result.score >= 5.0
    assert "limited" in result.summary.lower()


def test_build_up_with_search():
    result = BuildUpLens().analyze(make_match(), context={"search_results": ["Arsenal used 3-2-5 buildup."]})
    assert result.score > 5.0
    assert "available" in result.summary.lower()


def test_pressing_basic():
    result = PressingLens().analyze(make_match())
    assert result.score == 5.0
    assert len(result.insights) >= 1


def test_rest_defence_with_search():
    result = RestDefenceLens().analyze(make_match(), context={"search_results": ["Arsenal rest-defence solid."]})
    assert result.score > 5.0


def test_overload_basic():
    result = OverloadLens().analyze(make_match())
    assert 5.0 <= result.score <= 6.0
    assert result.lens_name == "Overload-to-Isolate"
