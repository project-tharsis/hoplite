"""Test that all KB paths are consistent."""
from src.paths import DEFAULT_KB_PATH, PROJECT_ROOT, PROMPTS_DIR
from src.report import ReportOrchestrator
from src.evaluation.knowledge import KnowledgeBase
from src.evaluation.patterns import PatternComputer


def test_kb_path_consistency():
    """All components point to the same default KB path."""
    kb = KnowledgeBase()
    ro = ReportOrchestrator()
    pc = PatternComputer()

    assert kb.path == ro.kb.path == pc.kb.path, \
        f"KB path mismatch: {kb.path} vs {ro.kb.path} vs {pc.kb.path}"


def test_kb_path_is_project_relative():
    """DEFAULT_KB_PATH is under project root."""
    assert str(PROJECT_ROOT) in str(DEFAULT_KB_PATH)
    assert DEFAULT_KB_PATH.name == "knowledge.json"


def test_prompts_dir_exists_after_create():
    """PROMPTS_DIR points to <repo>/prompts."""
    assert str(PROJECT_ROOT) in str(PROMPTS_DIR)
    assert PROMPTS_DIR.name == "prompts"
