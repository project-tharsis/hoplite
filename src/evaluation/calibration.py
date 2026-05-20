"""
Calibration hints from KnowledgeBase for v2 structured prompts.

Higher-level interface built on top of PatternComputer (legacy-compatible
aggregator).  CalibrationComputer adds:
  - sample-quality accounting (features vs. legacy-only entries)
  - legacy-entry detection
  - confidence capping when most entries are legacy-only
  - guardrails suitable for prompt injection
  - common missing-data reporting

New v2 code should call CalibrationComputer, not PatternComputer directly.
PatternComputer is retained for backward compatibility with legacy prompt code.
"""

import json
import logging
from collections import Counter
from pathlib import Path

from src.evaluation.knowledge import KnowledgeBase
from src.evaluation.patterns import (
    PatternComputer,
    MODEL_NAMES,
    DIMENSION_KEYS,
)

logger = logging.getLogger(__name__)

# Path to the versioned blind-spots JSON registry (relative to project root).
_BLIND_SPOTS_PATH: Path = Path(__file__).resolve().parent.parent.parent / "rubrics" / "arteta_blind_spots.json"


def _load_blind_spots() -> list[dict]:
    """Load active blind spots from the JSON registry.

    Falls back to the built-in KNOWN_BLIND_SPOTS constant if the file is
    missing, malformed, or contains no active spots.
    """
    path = _BLIND_SPOTS_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        spots = [
            s for s in data.get("blind_spots", [])
            if s.get("status") == "active"
        ]
        if spots:
            return spots
        logger.warning("No active blind spots in %s; falling back to built-in.", path)
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.warning("Could not load blind spots from %s (%s); falling back to built-in.", path, exc)

    return list(CalibrationComputer.KNOWN_BLIND_SPOTS)


class CalibrationComputer:
    """Produce guarded calibration hints from JSON history.

    Use this class (not PatternComputer) for new v2 structured-prompt code.
    """

    GUARDRAILS: list[str] = [
        "Historical hints are reference only.",
        "Current-match features take priority.",
        "Fewer than 5 similar matches means calibration confidence is low or medium.",
    ]

    KNOWN_BLIND_SPOTS: list[dict] = [
        {
            "id": "dominant_stats_loss",
            "description": "WK can overrate matches where Arsenal dominates shots/xG/possession but loses.",
            "guardrail": "Do not let shot/xG/possession dominance override result satisfaction. A loss to lower/mid_table opposition cannot be overall green.",
            "source": "human_review",
            "weak_label_version": "v1.1",
        }
    ]

    def __init__(self, kb_path: str | None = None):
        self._pc = PatternComputer(kb_path)
        self.kb = self._pc.kb  # expose for callers that need raw access

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_hints(self, context: dict, limit: int = 5) -> dict:
        """Build calibration hints for the given match context.

        Args:
            context: e.g. {"opponent_quality": "mid_table", "venue": "away",
                     "competition_stage": "league_early"}
            limit: max similar entries to consider.

        Returns:
            dict matching the CalibrationHints schema (see module docstring).
        """
        all_entries = self.kb.get_all()
        matches = self._pc._filter_by_context(all_entries, context)[:limit]

        if not matches:
            return self._empty_hints()

        # Sample-quality accounting
        with_features = 0
        with_human_review = 0
        legacy_only = 0

        for entry in matches:
            has_features = bool(entry.get("features"))
            has_review = bool(entry.get("human_override"))
            if has_review:
                with_human_review += 1
            if has_features:
                with_features += 1
            else:
                legacy_only += 1

        # Confidence
        count = len(matches)
        confidence = self._compute_confidence(count, with_features, legacy_only)

        # Record aggregates via PatternComputer (reuse existing logic)
        summary = self._pc.similar_match_summary(context, limit=limit)
        record = {
            "wins": summary["wins"],
            "draws": summary["draws"],
            "losses": summary["losses"],
            "avg_arsenal_score": summary["avg_arsenal_score"],
            "avg_opponent_score": summary["avg_opponent_score"],
        }

        # Common missing data
        missing_counter: Counter = Counter()
        for entry in matches:
            for field in entry.get("features", {}).get("missing_data", []):
                missing_counter[field] += 1
        common_missing = [f for f, _ in missing_counter.most_common(5)]

        return {
            "count": count,
            "confidence": confidence,
            "sample_quality": {
                "with_features": with_features,
                "with_human_review": with_human_review,
                "legacy_only": legacy_only,
            },
            "record": record,
            "model_signal_distribution": summary["model_signal_distribution"],
            "dimension_signal_distribution": summary["dimension_signal_distribution"],
            "common_missing_data": common_missing,
            "guardrails": list(self.GUARDRAILS),
            "known_blind_spots": list(_load_blind_spots()),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_confidence(
        count: int, with_features: int, legacy_only: int
    ) -> str:
        """Determine calibration confidence level.

        Rules:
          count < 3              → low
          3 <= count < 5         → medium
          count >= 5 and most have features → high
          most legacy-only       → cap at medium
        """
        if count < 3:
            return "low"
        if count < 5:
            return "medium"
        # count >= 5
        if legacy_only > with_features:
            # most entries are legacy-only → cap at medium
            return "medium"
        return "high"

    @staticmethod
    def _empty_hints() -> dict:
        return {
            "count": 0,
            "confidence": "low",
            "sample_quality": {
                "with_features": 0,
                "with_human_review": 0,
                "legacy_only": 0,
            },
            "record": {
                "wins": 0,
                "draws": 0,
                "losses": 0,
                "avg_arsenal_score": 0.0,
                "avg_opponent_score": 0.0,
            },
            "model_signal_distribution": {},
            "dimension_signal_distribution": {},
            "common_missing_data": [],
            "guardrails": list(CalibrationComputer.GUARDRAILS),
            "known_blind_spots": list(_load_blind_spots()),
        }
