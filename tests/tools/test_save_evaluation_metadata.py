"""Tests for evaluation_metadata support in save_evaluation."""
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_EVALUATION = {
    "overall_signal": "🟢",
    "model_signals": {
        "1": "🟢", "2": "🟢", "3": "🟢",
        "4": "🟢", "5": "🟢", "6": "🟢",
    },
    "dimension_signals": {"execution": "🟢", "adjustment": "🟢", "satisfaction": "🟢"},
    "narrative": "Strong performance.",
    "evidence": {
        "1": ["stat:goals=2"], "2": [], "3": [], "4": [], "5": [], "6": [],
    },
    "confidence": {
        "1": "high", "2": "high", "3": "high",
        "4": "high", "5": "high", "6": "high",
    },
    "missing_or_weak_evidence": [],
    "weak_label_disagreements": [],
}

REPORT_JSON = {
    "match": {
        "fixture_id": "12345",
        "date": "2026-05-20",
        "arsenal_score": 2,
        "opponent_score": 1,
        "result": "W",
        "competition": "PL",
    },
    "context": {"opponent": "Chelsea"},
    "predicted_plan": {},
}

SAMPLE_METADATA = {
    "evaluator_id": "B",
    "run_id": "b-001",
    "model": "evaluator-b-model",
    "prompt_hash": "sha256:abc123",
    "created_at": "2026-05-20T00:00:00Z",
    "features_version": "v1",
    "weak_label_version": "v1.1",
    "rubric_version": "arteta_v1",
    "prompt_builder_version": "v1",
    "job_schema_version": "self_iteration_job_v1",
}


@pytest.fixture(autouse=True)
def _patch_kb(tmp_path, monkeypatch):
    """Redirect KnowledgeBase to a temp dir so tests don't touch real KB."""
    import src.paths as paths
    kb_path = tmp_path / "kb.json"
    kb_path.write_text("[]")
    monkeypatch.setattr(paths, "DEFAULT_KB_PATH", kb_path)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSaveEvaluationMetadata:
    """save_evaluation should accept and persist evaluation_metadata."""

    def test_accepts_evaluation_metadata(self):
        """save_evaluation accepts evaluation_metadata without error."""
        from src.tools.save_evaluation import save_evaluation

        result = save_evaluation(
            REPORT_JSON,
            VALID_EVALUATION,
            evaluation_metadata=SAMPLE_METADATA,
        )
        assert result["ok"] is True

    def test_metadata_persisted_to_evaluation_metadata(self):
        """Metadata is written into entry['evaluation']['metadata']."""
        from src.tools.save_evaluation import save_evaluation

        result = save_evaluation(
            REPORT_JSON,
            VALID_EVALUATION,
            evaluation_metadata=SAMPLE_METADATA,
        )
        entry = result["entry"]
        assert "metadata" in entry["evaluation"]
        assert entry["evaluation"]["metadata"] == SAMPLE_METADATA

    def test_metadata_contains_expected_keys(self):
        """Metadata dict includes features_version, weak_label_version, etc."""
        from src.tools.save_evaluation import save_evaluation

        result = save_evaluation(
            REPORT_JSON,
            VALID_EVALUATION,
            evaluation_metadata=SAMPLE_METADATA,
        )
        meta = result["entry"]["evaluation"]["metadata"]
        for key in (
            "features_version",
            "weak_label_version",
            "rubric_version",
            "prompt_builder_version",
            "job_schema_version",
        ):
            assert key in meta, f"Missing key: {key}"

    def test_strict_validation_still_rejects_bad_results(self):
        """Strict validation still rejects results missing required fields."""
        from src.tools.save_evaluation import save_evaluation

        bad_eval = {"overall_signal": "🟢"}  # missing everything
        result = save_evaluation(
            REPORT_JSON,
            bad_eval,
            evaluation_metadata=SAMPLE_METADATA,
        )
        assert result["ok"] is False
        assert result["error"]["code"] == "VALIDATION_FAILED"

    def test_backward_compat_no_metadata(self):
        """Old callers without metadata still work and no metadata key added."""
        from src.tools.save_evaluation import save_evaluation

        result = save_evaluation(REPORT_JSON, VALID_EVALUATION)
        assert result["ok"] is True
        entry = result["entry"]
        assert "metadata" not in entry["evaluation"]
