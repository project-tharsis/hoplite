from src.analysis.base import TacticalLens, AnalysisResult


def test_analysis_result_dataclass():
    result = AnalysisResult(
        lens_name="test",
        summary="Good performance",
        score=7.5,
        key_moments=["Goal at 23'"],
        insights=["Pressing intensity was high"]
    )
    assert result.lens_name == "test"
    assert result.score == 7.5
    assert len(result.key_moments) == 1


class FakeLens(TacticalLens):
    name = "fake"
    def analyze(self, match, context=None):
        return self._build_result("ok", 5.0)


def test_tactical_lens_scores_are_clamped():
    lens = FakeLens()
    result1 = lens._build_result("test", 15.0)
    assert result1.score == 10.0
    result2 = lens._build_result("test", -2.0)
    assert result2.score == 1.0


def test_tactical_lens_default_values():
    lens = FakeLens()
    result = lens._build_result("summary", 5.0)
    assert result.key_moments == []
    assert result.insights == []
