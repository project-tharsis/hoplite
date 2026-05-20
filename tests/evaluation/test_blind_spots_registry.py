"""Tests for blind spots JSON registry migration (P6)."""
import json
import pytest
from pathlib import Path

from src.evaluation.calibration import CalibrationComputer


def _empty_kb(tmp_path):
    """Write an empty KB and return path."""
    kb_path = tmp_path / "kb.json"
    kb_path.write_text("[]")
    return str(kb_path)


def _registry_path():
    """Return the default registry path relative to project root."""
    return Path(__file__).resolve().parent.parent.parent / "rubrics" / "arteta_blind_spots.json"


# ------------------------------------------------------------------
# T1: build_hints() loads active blind spots from JSON
# ------------------------------------------------------------------
def test_build_hints_loads_active_from_json(tmp_path):
    """CalibrationComputer.build_hints() should load active blind spots from JSON."""
    cc = CalibrationComputer(_empty_kb(tmp_path))
    hints = cc.build_hints({})

    spots = hints["known_blind_spots"]
    ids = [s["id"] for s in spots]
    assert "dominant_stats_loss" in ids


# ------------------------------------------------------------------
# T2: inactive blind spots are not rendered
# ------------------------------------------------------------------
def test_inactive_blind_spots_excluded(tmp_path, monkeypatch):
    """Blind spots with status != 'active' should be filtered out."""
    registry = {
        "version": "v1",
        "blind_spots": [
            {
                "id": "dominant_stats_loss",
                "description": "...",
                "guardrail": "...",
                "source": "human_review",
                "weak_label_version": "v1.1",
                "status": "active",
            },
            {
                "id": "inactive_spot",
                "description": "should not appear",
                "guardrail": "...",
                "source": "human_review",
                "weak_label_version": "v1.1",
                "status": "retired",
            },
        ],
    }
    reg_path = tmp_path / "arteta_blind_spots.json"
    reg_path.write_text(json.dumps(registry))

    monkeypatch.setattr(
        "src.evaluation.calibration._BLIND_SPOTS_PATH",
        reg_path,
    )

    cc = CalibrationComputer(_empty_kb(tmp_path))
    hints = cc.build_hints({})

    ids = [s["id"] for s in hints["known_blind_spots"]]
    assert "dominant_stats_loss" in ids
    assert "inactive_spot" not in ids


# ------------------------------------------------------------------
# T3: registry missing → fall back to built-in KNOWN_BLIND_SPOTS
# ------------------------------------------------------------------
def test_fallback_when_registry_missing(tmp_path, monkeypatch):
    """When the JSON registry is absent, fall back to KNOWN_BLIND_SPOTS."""
    monkeypatch.setattr(
        "src.evaluation.calibration._BLIND_SPOTS_PATH",
        tmp_path / "nonexistent.json",
    )

    cc = CalibrationComputer(_empty_kb(tmp_path))
    hints = cc.build_hints({})

    spots = hints["known_blind_spots"]
    ids = [s["id"] for s in spots]
    assert "dominant_stats_loss" in ids, "Should fall back to built-in constant"


# ------------------------------------------------------------------
# T4: prompt still contains known_blind_spots (sanity)
# ------------------------------------------------------------------
def test_known_blind_spots_present_in_empty_hints():
    """_empty_hints() must also carry known_blind_spots."""
    empty = CalibrationComputer._empty_hints()
    assert "known_blind_spots" in empty
    assert len(empty["known_blind_spots"]) >= 1
    assert empty["known_blind_spots"][0]["id"] == "dominant_stats_loss"


# ------------------------------------------------------------------
# T5: registry JSON file exists and is valid
# ------------------------------------------------------------------
def test_registry_file_exists_and_valid():
    """The committed registry file should be valid JSON with version + blind_spots."""
    path = _registry_path()
    assert path.exists(), f"Registry not found: {path}"
    data = json.loads(path.read_text())
    assert "version" in data
    assert "blind_spots" in data
    assert isinstance(data["blind_spots"], list)
    assert len(data["blind_spots"]) >= 1


# ------------------------------------------------------------------
# T6: malformed JSON → fall back
# ------------------------------------------------------------------
def test_fallback_on_malformed_json(tmp_path, monkeypatch):
    """If JSON is malformed, fall back to built-in constant."""
    bad_path = tmp_path / "bad.json"
    bad_path.write_text("NOT VALID JSON {{{")

    monkeypatch.setattr(
        "src.evaluation.calibration._BLIND_SPOTS_PATH",
        bad_path,
    )

    cc = CalibrationComputer(_empty_kb(tmp_path))
    hints = cc.build_hints({})

    ids = [s["id"] for s in hints["known_blind_spots"]]
    assert "dominant_stats_loss" in ids
