"""Test that evolution layer feeds into main pipeline."""
import pytest
from src.report import ReportOrchestrator
from src.evaluation.predictor import ArtetaPredictor
from src.evaluation.knowledge import KnowledgeBase
from src.evaluation.patterns import PatternComputer


def test_predictor_receives_kb():
    """ReportOrchestrator passes KB to predictor by default."""
    ro = ReportOrchestrator()
    assert ro.kb is not None
    assert ro.predictor is not None

    # The predict() callable accepts kb= parameter
    plan = ro.predictor.predict({"opponent_quality": "top6", "venue": "home"}, kb=ro.kb)
    assert plan.focus_areas is not None
    assert len(plan.focus_areas) > 0


def test_prompt_injects_kb_default():
    """build_narrative_prompt injects historical block by default."""
    from src.tools.prompt import build_narrative_prompt
    report = {
        "one_line_summary": "Arsenal 3-1 Chelsea",
        "predicted_plan": {"focus_areas": ["控制中场"], "likely_approach": "", "key_battles": [], "expected_subs": ""},
        "context": {"opponent_quality": "top6", "venue": "home", "competition_stage": "league_late"},
        "stats": {"score": {"arsenal": 3, "opponent": 1}},
        "key_events": [],
        "set_pieces": {},
        "sub_impact": [],
    }
    prompt = build_narrative_prompt(report)
    assert "历史模式参考" in prompt


def test_prompt_no_kb_gracful():
    """Prompt builds even when KB is empty/nonexistent. No crash."""
    from src.tools.prompt import build_narrative_prompt
    import tempfile, os

    # Use a temp file that doesn't exist yet
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp_path = f.name
    os.unlink(tmp_path)

    report = {
        "one_line_summary": "Test",
        "predicted_plan": {"focus_areas": [], "likely_approach": "", "key_battles": [], "expected_subs": ""},
        "context": {"opponent_quality": "lower", "venue": "home"},
        "stats": {},
        "key_events": [],
        "set_pieces": {},
        "sub_impact": [],
    }
    prompt = build_narrative_prompt(report, kb_path=tmp_path)
    assert len(prompt) > 0
