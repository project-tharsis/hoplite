"""Tests for modular prompt builder (Phase 5).

Covers:
- Full prompt generation from MatchFeatures + WeakLabels + rubric
- Skip history mode
- Missing data section
- Weak label baseline with all 6 models + 3 dimensions
- JSON schema in prompt
- Chinese and English output
- Backward compatibility (old call path)
- Evidence and confidence in output schema
"""
import copy
import json
import pytest
import tempfile
from pathlib import Path

from src.features.extractor import MatchFeatures
from src.labels.weak_labeler import WeakLabels
from src.evaluation.prompt_builder import PromptBuilder, OUTPUT_SCHEMA
from src.evaluation.llm_result import validate_llm_result


# ── Fixtures ─────────────────────────────────────────────────────────

RUBRIC_PATH = Path(__file__).resolve().parent.parent / "rubrics" / "arteta_v1.yaml"


def _make_features(**overrides) -> MatchFeatures:
    """Create a MatchFeatures with sensible defaults."""
    defaults = dict(
        result="W",
        score_margin=2,
        opponent_quality="top6",
        venue="home",
        competition_stage="league_late",
        arsenal_goals=3,
        opponent_goals=1,
        possession_for=58.0,
        possession_against=42.0,
        possession_delta=16.0,
        shots_for=15,
        shots_against=8,
        shot_delta=7,
        shots_on_target_for=6,
        shots_on_target_against=3,
        shot_on_target_delta=3,
        xg_for=2.5,
        xg_against=0.6,
        xg_delta=1.9,
        pass_accuracy_for=87.0,
        pass_accuracy_against=79.0,
        pass_accuracy_delta=8.0,
        corners_for=7,
        corners_against=4,
        corner_delta=3,
        fouls_for=8,
        fouls_against=12,
        yellow_cards_for=1,
        red_cards_for=0,
        goals_conceded=1,
        opponent_shots_on_target=3,
        set_piece_goals_for=1,
        set_piece_goals_against=0,
        arsenal_sub_count=3,
        goals_after_arsenal_subs=1,
        substitution_windows=[{"minute": 60, "player": "Trossard"}, {"minute": 72, "player": "Havertz"}],
        missing_data=[],
    )
    defaults.update(overrides)
    return MatchFeatures(**defaults)


def _make_weak_labels(**overrides) -> WeakLabels:
    """Create WeakLabels with sensible defaults."""
    wl = WeakLabels()
    wl.model_signals = {
        "culture_as_os": "🟢",
        "where_game_is_played": "🟢",
        "defence_as_attacking_identity": "🟢",
        "marginal_gains": "🟢",
        "add_capability_keep_identity": "🟡",
        "role_clarity": "🟢",
    }
    wl.dimension_signals = {
        "execution": "🟢",
        "adjustment": "🟢",
        "satisfaction": "🟢",
    }
    wl.overall_signal = "🟢"
    wl.confidence = {
        "culture_as_os": "high",
        "where_game_is_played": "high",
        "defence_as_attacking_identity": "high",
        "marginal_gains": "high",
        "add_capability_keep_identity": "medium",
        "role_clarity": "high",
    }
    wl.evidence_refs = {
        "culture_as_os": ["yellow_cards_for=1"],
        "where_game_is_played": ["shot_delta=7", "xg_delta=1.90"],
        "defence_as_attacking_identity": ["goals_conceded=1"],
        "marginal_gains": ["set_piece_goals_for=1"],
        "add_capability_keep_identity": ["result=W"],
        "role_clarity": ["arsenal_sub_count=3"],
    }
    for k, v in overrides.items():
        setattr(wl, k, v)
    return wl


def _make_calibration_hints() -> dict:
    """Create sample calibration hints."""
    return {
        "count": 5,
        "wins": 3,
        "draws": 1,
        "losses": 1,
        "avg_arsenal_score": 2.2,
        "avg_opponent_score": 1.0,
        "model_signal_distribution": {
            "1": {"🟢": 3, "🟡": 1, "🔴": 1},
            "2": {"🟢": 2, "🟡": 2, "🔴": 1},
            "3": {"🟢": 4, "🟡": 1, "🔴": 0},
            "4": {"🟢": 2, "🟡": 2, "🔴": 1},
            "5": {"🟢": 3, "🟡": 1, "🔴": 1},
            "6": {"🟢": 3, "🟡": 2, "🔴": 0},
        },
        "most_common_focus_areas": ["控制中场", "边路进攻"],
    }


# ── Test: Full prompt generation ─────────────────────────────────────

def test_full_prompt_generation_zh():
    """Full prompt contains all 6 sections in Chinese."""
    builder = PromptBuilder(rubric=RUBRIC_PATH, language="zh")
    features = _make_features()
    wl = _make_weak_labels()
    hints = _make_calibration_hints()

    prompt = builder.build(features, wl, calibration_hints=hints)

    # Section 1: Match summary
    assert "## 1. 比赛概述" in prompt
    assert "阿森纳 3 - 1 对手" in prompt

    # Section 2: Feature table
    assert "## 2. 关键数据" in prompt
    assert "possession" in prompt
    assert "shots" in prompt

    # Section 3: Missing data
    assert "## 3. 缺失数据" in prompt

    # Section 4: Weak label baseline
    assert "## 4. 弱标签基线" in prompt
    assert "模型1" in prompt
    assert "模型6" in prompt

    # Section 5: Rubric excerpt
    assert "## 5. 评估规则摘要" in prompt
    assert "文化是战术的操作系统" in prompt

    # Section 6: Calibration hints
    assert "## 6. 历史校准参考" in prompt
    assert "类似场景共 5 场" in prompt

    # Disagreement instruction
    assert "MUST" in prompt

    # Output schema
    assert "output_schema" in prompt.lower() or "输出格式" in prompt
    assert "evidence" in prompt
    assert "confidence" in prompt
    assert "missing_or_weak_evidence" in prompt
    assert "weak_label_disagreements" in prompt


# ── Test: Skip history mode ──────────────────────────────────────────

def test_skip_history_omits_calibration():
    """When skip_history=True, section 6 is omitted."""
    builder = PromptBuilder(rubric=RUBRIC_PATH, language="zh")
    features = _make_features()
    wl = _make_weak_labels()
    hints = _make_calibration_hints()

    prompt = builder.build(features, wl, calibration_hints=hints, skip_history=True)

    assert "## 6. 历史校准参考" not in prompt
    # But other sections should still be present
    assert "## 1. 比赛概述" in prompt
    assert "## 4. 弱标签基线" in prompt


def test_skip_history_no_hints():
    """When skip_history=True and no hints, section 6 is still omitted."""
    builder = PromptBuilder(rubric=RUBRIC_PATH, language="zh")
    features = _make_features()
    wl = _make_weak_labels()

    prompt = builder.build(features, wl, calibration_hints=None, skip_history=True)

    assert "## 6. 历史校准参考" not in prompt


# ── Test: Missing data section ───────────────────────────────────────

def test_missing_data_section_present():
    """Missing data section shows items when features have missing_data."""
    builder = PromptBuilder(rubric=RUBRIC_PATH, language="zh")
    features = _make_features(missing_data=["xG", "pressing", "pressing_recoveries"])
    wl = _make_weak_labels()

    prompt = builder.build(features, wl)

    assert "## 3. 缺失数据" in prompt
    assert "xG" in prompt
    assert "pressing" in prompt


def test_missing_data_section_empty():
    """Missing data section reports none when empty."""
    builder = PromptBuilder(rubric=RUBRIC_PATH, language="zh")
    features = _make_features(missing_data=[])
    wl = _make_weak_labels()

    prompt = builder.build(features, wl)

    assert "无缺失数据" in prompt


# ── Test: Weak label baseline ────────────────────────────────────────

def test_weak_label_baseline_all_models():
    """Weak label baseline includes all 6 models."""
    builder = PromptBuilder(rubric=RUBRIC_PATH, language="zh")
    features = _make_features()
    wl = _make_weak_labels()

    prompt = builder.build(features, wl)

    for model_num in ["1", "2", "3", "4", "5", "6"]:
        assert f"模型{model_num}" in prompt, f"Model {model_num} missing from prompt"


def test_weak_label_baseline_all_dimensions():
    """Weak label baseline includes all 3 dimensions."""
    builder = PromptBuilder(rubric=RUBRIC_PATH, language="zh")
    features = _make_features()
    wl = _make_weak_labels()

    prompt = builder.build(features, wl)

    assert "执行" in prompt
    assert "调整" in prompt
    assert "满意" in prompt


def test_weak_label_baseline_signals():
    """Weak label baseline shows correct signals."""
    builder = PromptBuilder(rubric=RUBRIC_PATH, language="zh")
    features = _make_features()
    wl = _make_weak_labels()

    prompt = builder.build(features, wl)

    # Overall signal
    assert "🟢" in prompt
    # Model signals should be present
    assert "culture_as_os" in prompt or "文化标准" in prompt


# ── Test: JSON schema in prompt ──────────────────────────────────────

def test_json_schema_included():
    """JSON output schema is included in the prompt."""
    builder = PromptBuilder(rubric=RUBRIC_PATH, language="zh")
    features = _make_features()
    wl = _make_weak_labels()

    prompt = builder.build(features, wl)

    # Schema should include all required fields
    assert "overall_signal" in prompt
    assert "model_signals" in prompt
    assert "dimension_signals" in prompt
    assert "evidence" in prompt
    assert "confidence" in prompt
    assert "missing_or_weak_evidence" in prompt
    assert "weak_label_disagreements" in prompt
    assert "narrative" in prompt


def test_output_schema_structure():
    """OUTPUT_SCHEMA dict has the expected structure."""
    assert "overall_signal" in OUTPUT_SCHEMA
    assert "model_signals" in OUTPUT_SCHEMA
    assert len(OUTPUT_SCHEMA["model_signals"]) == 6
    assert "dimension_signals" in OUTPUT_SCHEMA
    assert len(OUTPUT_SCHEMA["dimension_signals"]) == 3
    assert "evidence" in OUTPUT_SCHEMA
    assert "confidence" in OUTPUT_SCHEMA
    assert "missing_or_weak_evidence" in OUTPUT_SCHEMA
    assert "weak_label_disagreements" in OUTPUT_SCHEMA
    assert "narrative" in OUTPUT_SCHEMA


# ── Test: Chinese and English output ─────────────────────────────────

def test_chinese_output():
    """Chinese language output uses Chinese labels."""
    builder = PromptBuilder(rubric=RUBRIC_PATH, language="zh")
    features = _make_features()
    wl = _make_weak_labels()

    prompt = builder.build(features, wl)

    assert "比赛概述" in prompt
    assert "关键数据" in prompt
    assert "缺失数据" in prompt
    assert "弱标签基线" in prompt
    assert "评估规则摘要" in prompt
    assert "你是足球战术分析师" in prompt


def test_english_output():
    """English language output uses English labels."""
    builder = PromptBuilder(rubric=RUBRIC_PATH, language="en")
    features = _make_features()
    wl = _make_weak_labels()

    prompt = builder.build(features, wl)

    assert "Match Summary" in prompt
    assert "Feature Table" in prompt
    assert "Missing Data" in prompt
    assert "Weak Label Baseline" in prompt
    assert "Rubric Excerpt" in prompt
    assert "You are a football tactical analyst" in prompt


def test_english_result_labels():
    """English output uses Win/Draw/Loss instead of 胜/平/负."""
    builder = PromptBuilder(rubric=RUBRIC_PATH, language="en")
    features = _make_features(result="W")
    wl = _make_weak_labels()

    prompt = builder.build(features, wl)

    assert "Win" in prompt


# ── Test: Backward compatibility ─────────────────────────────────────

def test_backward_compat_old_call_path():
    """Old call path (no features/weak_labels/rubric) still works."""
    from src.tools.prompt import build_narrative_prompt

    report_json = {
        "one_line_summary": "Arsenal 3-1 Chelsea (Premier League)",
        "predicted_plan": {
            "focus_areas": ["控制中场"],
            "likely_approach": "高位防线",
            "key_battles": ["中场对抗"],
            "expected_subs": "60' 边路换人",
        },
        "context": {
            "opponent_quality": "top6",
            "venue": "home",
            "competition_stage": "league_late",
        },
        "stats": {
            "score": {"arsenal": 3, "opponent": 1},
            "xg": {"arsenal": 2.5, "opponent": 0.6},
        },
        "key_events": [],
        "set_pieces": {},
        "sub_impact": [],
    }

    prompt = build_narrative_prompt(report_json, "Some context.", skip_history=True)

    # Old path should produce the legacy format
    assert "Arsenal 3-1 Chelsea" in prompt
    assert "心智模型" in prompt
    assert "Arteta" in prompt
    assert "Some context." in prompt


def test_backward_compat_new_call_path():
    """New call path with features + weak_labels + rubric delegates to PromptBuilder."""
    from src.tools.prompt import build_narrative_prompt

    report_json = {
        "one_line_summary": "Arsenal 3-1 Chelsea",
        "context": {"opponent_quality": "top6", "venue": "home"},
        "predicted_plan": {},
        "stats": {},
        "key_events": [],
        "set_pieces": {},
        "sub_impact": [],
    }

    features = _make_features()
    wl = _make_weak_labels()

    prompt = build_narrative_prompt(
        report_json,
        skip_history=True,
        features=features,
        weak_labels=wl,
        rubric=RUBRIC_PATH,
        language="zh",
    )

    # New path should produce modular format
    assert "## 1. 比赛概述" in prompt
    assert "## 4. 弱标签基线" in prompt
    assert "输出格式" in prompt


def test_backward_compat_no_features_falls_back():
    """When only some new params are provided, falls back to legacy."""
    from src.tools.prompt import build_narrative_prompt

    report_json = {
        "one_line_summary": "Arsenal 2-0 Spurs",
        "context": {},
        "predicted_plan": {},
        "stats": {},
        "key_events": [],
        "set_pieces": {},
        "sub_impact": [],
    }

    # Only features, no weak_labels or rubric — should fall back
    prompt = build_narrative_prompt(
        report_json,
        skip_history=True,
        features=_make_features(),
    )

    # Should be legacy format
    assert "Arsenal 2-0 Spurs" in prompt
    assert "心智模型" in prompt


# ── Test: Rubric loading ─────────────────────────────────────────────

def test_rubric_load_from_path():
    """Rubric loads correctly from YAML file."""
    builder = PromptBuilder(rubric=RUBRIC_PATH)
    assert "models" in builder.rubric
    assert len(builder.rubric["models"]) == 6


def test_rubric_load_from_dict():
    """Rubric loads correctly from a dict."""
    import yaml
    with open(RUBRIC_PATH, encoding="utf-8") as f:
        rubric_dict = yaml.safe_load(f)
    builder = PromptBuilder(rubric=rubric_dict)
    assert len(builder.rubric["models"]) == 6


def test_rubric_not_found():
    """Rubric file not found raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        PromptBuilder(rubric="/nonexistent/rubric.yaml")


# ── Test: Validator with new fields ──────────────────────────────────

def _make_valid_v2_result():
    """Create a valid result with v2 fields."""
    return {
        "overall_signal": "🟢",
        "model_signals": {
            "1": "🟢", "2": "🟢", "3": "🟡",
            "4": "🟢", "5": "🟡", "6": "🟢",
        },
        "dimension_signals": {
            "execution": "🟢",
            "adjustment": "🟡",
            "satisfaction": "🟢",
        },
        "narrative": "阿森纳通过控制中场和定位球威胁掌控了比赛节奏。",
        "evidence": {
            "1": ["yellow_cards_for=1"],
            "2": ["shot_delta=7", "xg_delta=1.90"],
            "3": ["goals_conceded=1"],
            "4": ["set_piece_goals_for=1"],
            "5": ["result=W"],
            "6": ["arsenal_sub_count=3"],
        },
        "confidence": {
            "1": "high", "2": "high", "3": "high",
            "4": "high", "5": "medium", "6": "high",
        },
        "missing_or_weak_evidence": ["xG missing in some sources"],
        "weak_label_disagreements": [],
    }


def test_validator_v2_result_passes():
    """Full v2 result with all optional fields passes validation."""
    data = _make_valid_v2_result()
    result = validate_llm_result(data)
    assert result["overall_signal"] == "🟢"
    assert "evidence" in result
    assert "confidence" in result
    assert "missing_or_weak_evidence" in result
    assert "weak_label_disagreements" in result


def test_validator_v2_optional_fields_warned():
    """Missing v2 optional fields produce warnings but don't fail."""
    import io
    import sys

    data = {
        "overall_signal": "🟢",
        "model_signals": {
            "1": "🟢", "2": "🟢", "3": "🟡",
            "4": "🟢", "5": "🟡", "6": "🟢",
        },
        "dimension_signals": {
            "execution": "🟢",
            "adjustment": "🟡",
            "satisfaction": "🟢",
        },
        "narrative": "Test narrative.",
    }

    # Capture stderr
    old_stderr = sys.stderr
    sys.stderr = captured = io.StringIO()
    try:
        result = validate_llm_result(data)
    finally:
        sys.stderr = old_stderr

    # Should pass
    assert result["overall_signal"] == "🟢"

    # Should warn about missing optional fields
    stderr_output = captured.getvalue()
    assert "Optional v2 fields missing" in stderr_output
    assert "evidence" in stderr_output
    assert "confidence" in stderr_output


def test_validator_v2_disagreements():
    """Validation passes with disagreement entries."""
    data = _make_valid_v2_result()
    data["weak_label_disagreements"] = [
        {
            "model": "2",
            "weak_signal": "🟡",
            "llm_signal": "🟢",
            "reason": "Despite xG missing, shot dominance was clear",
        }
    ]
    result = validate_llm_result(data)
    assert len(result["weak_label_disagreements"]) == 1


# ── Test: Feature table formatting ──────────────────────────────────

def test_feature_table_with_none_values():
    """Feature table handles None values gracefully."""
    builder = PromptBuilder(rubric=RUBRIC_PATH, language="zh")
    features = _make_features(
        xg_for=None,
        xg_against=None,
        xg_delta=None,
        possession_for=None,
        possession_against=None,
        possession_delta=None,
    )
    wl = _make_weak_labels()

    prompt = builder.build(features, wl)

    assert "N/A" in prompt


def test_feature_table_with_zero_subs():
    """Feature table shows 0 subs correctly."""
    builder = PromptBuilder(rubric=RUBRIC_PATH, language="zh")
    features = _make_features(arsenal_sub_count=0, goals_after_arsenal_subs=0)
    wl = _make_weak_labels()

    prompt = builder.build(features, wl)

    assert "换人次数" in prompt


# ── Test: Search context ─────────────────────────────────────────────

def test_search_context_included():
    """External search context is included when provided."""
    builder = PromptBuilder(rubric=RUBRIC_PATH, language="zh")
    features = _make_features()
    wl = _make_weak_labels()

    prompt = builder.build(features, wl, search_context="Arsenal used 3-2-5 build-up.")

    assert "3-2-5" in prompt
    assert "外部战术分析参考" in prompt


def test_search_context_truncated():
    """Search context is truncated to 1000 chars."""
    builder = PromptBuilder(rubric=RUBRIC_PATH, language="zh")
    features = _make_features()
    wl = _make_weak_labels()

    long_context = "A" * 2000
    prompt = builder.build(features, wl, search_context=long_context)

    # The context should be truncated
    assert "A" * 1000 in prompt
    assert "A" * 1500 not in prompt


# ── Test: Rubric excerpt content ─────────────────────────────────────

def test_rubric_excerpt_has_all_models():
    """Rubric excerpt includes all 6 model philosophies."""
    builder = PromptBuilder(rubric=RUBRIC_PATH, language="zh")
    features = _make_features()
    wl = _make_weak_labels()

    prompt = builder.build(features, wl)

    assert "文化是战术的操作系统" in prompt
    assert "控制比赛发生在哪里" in prompt
    assert "防守也是进攻身份" in prompt
    assert "边际收益要专家化" in prompt
    assert "加能力，但不要丢身份" in prompt
    assert "人需要清晰度，不只是压力" in prompt


def test_rubric_excerpt_has_dimensions():
    """Rubric excerpt includes dimension judgment rules."""
    builder = PromptBuilder(rubric=RUBRIC_PATH, language="zh")
    features = _make_features()
    wl = _make_weak_labels()

    prompt = builder.build(features, wl)

    assert "赛前决策执行度" in prompt
    assert "赛中调整合理性" in prompt
    assert "比赛结果满意度" in prompt


# ── Test: Calibration hints formatting ───────────────────────────────

def test_calibration_hints_with_data():
    """Calibration hints section shows stats correctly."""
    builder = PromptBuilder(rubric=RUBRIC_PATH, language="zh")
    features = _make_features()
    wl = _make_weak_labels()
    hints = _make_calibration_hints()

    prompt = builder.build(features, wl, calibration_hints=hints)

    assert "5 场" in prompt
    assert "3胜" in prompt
    assert "控制中场" in prompt or "边路进攻" in prompt


def test_calibration_hints_empty():
    """Empty calibration hints shows 'no data' message."""
    builder = PromptBuilder(rubric=RUBRIC_PATH, language="zh")
    features = _make_features()
    wl = _make_weak_labels()
    hints = {"count": 0, "wins": 0, "draws": 0, "losses": 0}

    prompt = builder.build(features, wl, calibration_hints=hints)

    assert "无历史数据" in prompt


def test_calibration_hints_none():
    """None calibration hints skips section."""
    builder = PromptBuilder(rubric=RUBRIC_PATH, language="zh")
    features = _make_features()
    wl = _make_weak_labels()

    prompt = builder.build(features, wl, calibration_hints=None, skip_history=False)

    # Section 6 should not appear when hints is None
    assert "## 6. 历史校准参考" not in prompt


# ── Test: Disagreement instruction ───────────────────────────────────

def test_disagreement_instruction():
    """Prompt includes instruction to explain weak label disagreements."""
    builder = PromptBuilder(rubric=RUBRIC_PATH, language="zh")
    features = _make_features()
    wl = _make_weak_labels()

    prompt = builder.build(features, wl)

    assert "MUST" in prompt
    assert "弱标签" in prompt or "weak label" in prompt.lower()


# ── Test: YAML rubric validity ───────────────────────────────────────

def test_yaml_rubric_valid():
    """YAML rubric file is valid and parseable."""
    import yaml
    with open(RUBRIC_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    assert data is not None
    assert "metadata" in data
    assert data["metadata"]["version"] == "1.0"
    assert "models" in data
    assert len(data["models"]) == 6
    assert "dimensions" in data
    assert len(data["dimensions"]) == 3
    assert "output_schema" in data
    assert "writing_style" in data
    assert "narrative_structure" in data


def test_yaml_rubric_model_fields():
    """Each model in rubric has all required fields."""
    import yaml
    with open(RUBRIC_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    required_fields = [
        "id", "name", "display_name", "philosophy",
        "observable_features", "positive_indicators", "negative_indicators",
        "weak_label_rules", "confidence_rules", "data_limitations",
        "narrative_guidance",
    ]

    for model in data["models"]:
        for field_name in required_fields:
            assert field_name in model, f"Model {model.get('id')} missing field: {field_name}"


def test_yaml_rubric_dimension_fields():
    """Each dimension in rubric has all required fields."""
    import yaml
    with open(RUBRIC_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    required_fields = ["id", "display_name", "description", "constituent_models", "judgment_rules"]

    for dim in data["dimensions"]:
        for field_name in required_fields:
            assert field_name in dim, f"Dimension {dim.get('id')} missing field: {field_name}"
