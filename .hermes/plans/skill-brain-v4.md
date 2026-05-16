# Hoplite v4 — Skill Brain Architecture

## Goal
Python = pure data extraction. SKILL.md = Arteta decision brain.
Move ALL judgment logic from `src/evaluation/` into SKILL.md as prompt framework.

## Principle
```
Python tools: extract raw stats/events → JSON
SKILL.md: Arteta mental model framework → prompt instructions  
Agent (LLM): apply framework to data → qualitative analysis + narrative
```

## Phase E1: Pure Data Extraction
**File:** `src/tools/extract.py` (NEW)

```python
def extract_match_stats(match_json: dict) -> dict:
    """Pure stat aggregation. No judgment."""
    # Returns: possession, shots, xG, passes, cards, fouls, corners, set_piece_goals, etc.
    # Everything is raw numbers — no 🟢🟡🔴, no "good" or "bad".

def extract_key_events(match_json: dict) -> list[dict]:
    """Goals, cards, subs with context (minute, player, detail, match_state)."""

def extract_context(match_json: dict) -> dict:
    """Opponent quality, venue, competition stage, injuries."""
```

## Phase E2: Rewrite analyze tool
**File:** `src/tools/analyze.py` (rewrite)

Replaces evaluator loop with: extract_stats → extract_events → extract_context → MatchReport container.

## Phase E3: Simplify MatchReport
**File:** `src/report.py` (rewrite)

`MatchReport` becomes pure data container: match, stats, events, context, predicted_plan.
No mental_model_results, no execution/adjustment/satisfaction.
Adds KB write.

## Phase E4: New Prompt Builder
**File:** `src/tools/prompt.py` (rewrite)

Prompt now injects:
- Raw stats + events as data block
- Arteta 6 Mental Model framework (from SKILL.md) as evaluation instructions
- 3-Dimension framework as evaluation instructions
- Writing style rules

## Phase E5: Rewrite SKILL.md
Full Arteta mental model evaluation framework embedded as prompt template:
- Model 1-6 with evaluation questions + data mapping
- 3-Dimension assessment logic (previously in dimensions.py)
- Predictor heuristics (previously in predictor.py)
- All written as WHAT to look for, not conditional code

## Phase E6: Cleanup
Remove: `src/evaluation/mental_models.py`, `dimensions.py`
Simplify: `src/evaluation/__init__.py`
Update: tests

## Dependencies
E1 → E2, E3, E4 (all need extract.py)
E2 + E3 + E4 → E5 (SKILL.md references data format)
E5 → E6 (cleanup after SKILL.md solid)
