"""Test KnowledgeBase upsert and schema."""
import pytest
import tempfile
import os
from src.evaluation.knowledge import KnowledgeBase


def test_upsert_prevents_duplicates():
    """Saving same match_id twice results in one entry."""
    with tempfile.NamedTemporaryFile(suffix=".json", mode="w") as f:
        f.write("[]")
        f.flush()
        kb = KnowledgeBase(f.name)

        entry1 = {"match_id": "123", "score": "2-1", "result": "W"}
        entry2 = {"match_id": "123", "score": "3-1", "result": "W"}

        kb.upsert_entry(entry1, key="match_id")
        kb.upsert_entry(entry2, key="match_id")

        data = kb.get_all()
        assert len(data) == 1
        assert data[0]["score"] == "3-1"


def test_save_entry_appends():
    """Normal save_entry() appends (no upsert)."""
    with tempfile.NamedTemporaryFile(suffix=".json", mode="w") as f:
        f.write("[]")
        f.flush()
        kb = KnowledgeBase(f.name)

        kb.save_entry({"match_id": "1", "score": "1-0"})
        kb.save_entry({"match_id": "2", "score": "2-0"})

        assert len(kb.get_all()) == 2


def test_upsert_preserves_other_entries():
    """Upsert only touches the matching entry."""
    with tempfile.NamedTemporaryFile(suffix=".json", mode="w") as f:
        f.write("[]")
        f.flush()
        kb = KnowledgeBase(f.name)

        kb.save_entry({"match_id": "a", "score": "1-0"})
        kb.save_entry({"match_id": "b", "score": "2-0"})
        kb.upsert_entry({"match_id": "a", "score": "3-0"}, key="match_id")

        data = kb.get_all()
        assert len(data) == 2
        scores = {e["match_id"]: e["score"] for e in data}
        assert scores["a"] == "3-0"
        assert scores["b"] == "2-0"
