import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.paths import DEFAULT_KB_PATH as _DEFAULT_KB_PATH

DEFAULT_KB_PATH = str(_DEFAULT_KB_PATH)


class KnowledgeBase:
    def __init__(self, path: str = DEFAULT_KB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write([])

    def _write(self, data: list) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _read(self) -> list[dict]:
        with open(self.path, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_entry(self, entry: dict) -> None:
        """Append a match analysis entry to the knowledge base."""
        if "timestamp" not in entry:
            entry["timestamp"] = datetime.now().isoformat()
        data = self._read()
        data.append(entry)
        self._write(data)

    def get_all(self) -> list[dict]:
        """Return all entries."""
        return self._read()

    def query(
        self,
        opponent: Optional[str] = None,
        venue: Optional[str] = None,
        result: Optional[str] = None,
        limit: int = 10,
    ) -> list[dict]:
        """Query entries by filters. Returns most recent first."""
        data = self._read()
        filtered = []
        for entry in data:
            if opponent is not None and entry.get("opponent") != opponent:
                continue
            if result is not None and entry.get("result") != result:
                continue
            if venue is not None:
                pre_match = entry.get("pre_match_context", {})
                if pre_match.get("venue") != venue:
                    continue
            filtered.append(entry)
        # Sort by timestamp descending (most recent first)
        filtered.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
        return filtered[:limit]

    def find_similar_context(
        self, opponent_quality: str, venue: str, limit: int = 3
    ) -> list[dict]:
        """Find past matches with similar pre-match context for pattern recognition."""
        data = self._read()
        matches = []
        for entry in data:
            pre_match = entry.get("pre_match_context", {})
            if (
                pre_match.get("opponent_quality") == opponent_quality
                and pre_match.get("venue") == venue
            ):
                matches.append(entry)
        matches.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
        return matches[:limit]

    def get_patterns(self, model_number: str) -> dict:
        """Get signal distribution for a specific mental model across history.
        Returns {'🟢': N, '🟡': N, '🔴': N}
        """
        data = self._read()
        distribution: dict[str, int] = {"🟢": 0, "🟡": 0, "🔴": 0}
        for entry in data:
            model_signals = entry.get("evaluation", {}).get("model_signals", {})
            signal = model_signals.get(model_number)
            if signal in distribution:
                distribution[signal] += 1
        return distribution
