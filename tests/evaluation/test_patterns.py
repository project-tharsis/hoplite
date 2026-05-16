"""Test PatternComputer output quality."""
import json
import tempfile
import os
from src.evaluation.patterns import PatternComputer


def test_format_for_prompt_empty_kb():
    """Empty KB produces graceful 'no data' message."""
    with tempfile.NamedTemporaryFile(suffix=".json", mode="w") as f:
        f.write("[]")
        f.flush()
        pc = PatternComputer(f.name)
        result = pc.format_for_prompt({"venue": "away", "opponent_quality": "top6"})
        assert "无历史数据" in result
        assert "以本场比赛数据为准" in result


def test_format_for_prompt_with_data():
    """KB with matches produces rich context block."""
    with tempfile.NamedTemporaryFile(suffix=".json", mode="w") as f:
        entries = [
            {
                "match_id": "1",
                "timestamp": "2024-03-10T16:30:00",
                "opponent": "Liverpool",
                "score": "3-1",
                "result": "W",
                "competition": "Premier League",
                "pre_match_context": {
                    "opponent_quality": "top6",
                    "venue": "home",
                    "competition_stage": "league_late",
                },
                "predicted_plan": {
                    "focus_areas": ["控制中场", "快速转换"],
                    "likely_approach": "",
                    "key_battles": [],
                    "expected_subs": "",
                },
                "evaluation": {
                    "model_signals": {"1": "🟢", "2": "🟢", "3": "🟡", "4": "🟢", "5": "🟡", "6": "🟢"},
                    "dimension_signals": {
                        "execution": "🟢",
                        "adjustment": "🟡",
                        "satisfaction": "🟢",
                    },
                },
                "human_override": None,
            },
        ]
        json.dump(entries, f, ensure_ascii=False)
        f.flush()
        pc = PatternComputer(f.name)
        result = pc.format_for_prompt(
            {"venue": "home", "opponent_quality": "top6", "competition_stage": "league_late"},
        )

    # Verify key sections exist
    assert "历史模式参考" in result
    assert "1胜 0平 0负" in result
    assert "Liverpool" in result
    assert "维度信号分布" in result
    assert "心智模型历史表现" in result
    assert "最近类似案例" in result
    assert "历史参考规则" in result
    assert "以本场数据为准" in result


def test_focus_area_effectiveness_excludes_unevaluated():
    """Unevaluated entries don't pollute avg_execution_signal."""
    with tempfile.NamedTemporaryFile(suffix=".json", mode="w") as f:
        entries = [
            {
                "match_id": "1",
                "timestamp": "2024-01-01T00:00:00",
                "result": "W",
                "predicted_plan": {"focus_areas": ["控制中场"]},
                "evaluation": {
                    "dimension_signals": {"execution": "🟢"},
                },
                "pre_match_context": {},
            },
            {
                "match_id": "2",
                "timestamp": "2024-02-01T00:00:00",
                "result": "W",
                "predicted_plan": {"focus_areas": ["控制中场"]},
                "evaluation": {
                    "dimension_signals": {},
                },
                "pre_match_context": {},
            },
        ]
        json.dump(entries, f, ensure_ascii=False)
        f.flush()
        pc = PatternComputer(f.name)
        result = pc.focus_area_effectiveness("控制中场")

    assert result["count"] == 2
    assert result["evaluated_count"] == 1
    assert result["avg_execution_signal"] == 1.0
    assert result["win_rate"] == 1.0
