# Hoplite v2 Upgrade Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Upgrade Hoplite from statistical data dump to manager-specific tactical narrative engine. Close the gap between current v1 (Chat delivery only) and the three-pronged value proposition (Manager-specific analysis + LLM narrative + Chat delivery).

**Architecture Decision:**
LLM narrative synthesis runs in Hermes skill context (not in CLI). CLI handles data pipeline + analysis, outputs a structured MatchReport with a `narrative_prompt` field. The hoplite Hermes skill feeds this prompt to the LLM, generates the tactical narrative, and builds the final card. This avoids adding a new LLM API key dependency to the CLI — Hoplite leverages the existing Hermes LLM.

---

## What Changes (High Level)

**Data pipeline upgrade:** `cmd_latest` merges all 4 sources instead of just football-data.org
**New module:** `NarrativePromptBuilder` — generates Arteta-style tactical prompt from MatchReport
**Card upgrade:** New narrative section in the Feishu card
**Skill upgrade:** hoplite skill adds LLM synthesis step before card delivery

---

## What Elio Needs To Do

**Nothing from v1 changes.** Same API tokens (football-data.org + API-Football) already in config.yaml. No new registrations, no new keys. The LLM narrative uses Hermes' existing model — zero new dependencies.

---

## Tasks (6 tasks, ~30 min total)

### Task 2.0: Upgrade `cmd_latest` — full data pipeline

**Objective:** Make `cmd_latest` pull from all 4 data sources (football-data.org + Understat xG + Brave search context + API-Football events when available), merge into Match, pass search context to orchestrator.

**Files:** Modify `src/cli.py:19-52`

**Changes:**
1. After fetching match from football-data.org, try Understat for xG merge
2. Run Brave search queries (use `build_match_report_query` from `search_source.py`) — for now, the CLI just generates the queries; actual search is done by Hermes skill
3. Pass all acquired context to `orchestrator.generate(match, search_context={...})`
4. Add `--full` flag that enables all sources (default: `latest` = fast path, `latest --full` = all sources)

```python
def cmd_latest(config: dict, full: bool = False) -> None:
    # ... existing football-data.org fetch ...
    
    search_queries = []
    if full:
        # Try Understat for xG
        try:
            from src.data.understat import UnderstatClient
            uc = UnderstatClient()
            understat_matches = uc.get_league_matches(season="2024")
            # Find matching match by team names
            for um in understat_matches:
                if um["home_team"] == match.home_team and um["away_team"] == match.away_team:
                    merge_match_data(match, understat_data=um)
                    break
        except Exception:
            pass  # Understat optional
        
        # Build search queries for Brave
        from src.data.search_source import build_match_report_query
        search_queries = [build_match_report_query(match.away_team if match.arsenal_is_home else match.home_team)]
```

**Status:** `cmd_latest` is the default path. `cmd_analyze` (fixture-id based) already has API-Football integration — leave as-is for advanced use.

---

### Task 2.1: `NarrativePromptBuilder` — new module

**Objective:** Generate an LLM-ready prompt from a MatchReport that instructs the LLM to write an Arteta-perspective tactical narrative.

**Files:** Create `src/narrative.py`

```python
from src.report import MatchReport

class NarrativePromptBuilder:
    """Builds an LLM prompt for Arteta-style tactical narrative synthesis."""
    
    def build(self, report: MatchReport, search_context: str = "") -> str:
        m = report.match
        
        prompt = f"""You are a football tactics analyst writing in the voice of a coach deeply familiar with Mikel Arteta's system. Write a concise post-match tactical analysis (300-400 words) of the following match:

MATCH: {m.home_team} {m.home_score}-{m.away_score} {m.away_team}
COMPETITION: {m.competition}
DATE: {m.date.strftime('%Y-%m-%d')}

TACTICAL LENS ANALYSIS:
"""
        for r in report.results:
            prompt += f"\n## {r.lens_name} (Score: {r.score:.1f}/10)\n{r.summary}\n"
            for insight in r.insights:
                prompt += f"- {insight}\n"
        
        if search_context:
            prompt += f"\nPOST-MATCH ANALYSIS CONTEXT:\n{search_context[:2000]}\n"
        
        prompt += """
Write in this style:
- Short paragraphs, no academic language
- Football terminology natural: "inverted fullback", "rest-defence", "overload-to-isolate", "double pivot"
- Analyze WHY things happened, not just WHAT happened
- Reference Arteta's known tactical preferences when relevant
- End with a one-sentence verdict

Write only the analysis, no headers or meta-commentary.
"""
        return prompt
```

**Test:** Create `tests/test_narrative.py` — 1 test verifying prompt structure contains match data, lens names, and style instructions.

---

### Task 2.2: Upgrade `FeishuCardBuilder` — narrative section

**Objective:** Add a narrative markdown section to the card, placed between the header summary and the score table.

**Files:** Modify `src/output/feishu_card.py`

**Changes:**
- Add optional `narrative: str = ""` parameter to `build_match_card`
- Insert narrative markdown element after the competition/date line, before the first `<hr>`
- Narrative length cap: 500 chars for card display (full version in doc later)

```python
def build_match_card(self, report: MatchReport, narrative: str = "") -> dict:
    # ... existing header ...
    elements = [
        {
            "tag": "markdown",
            "content": f"**{m.competition}** · {m.date.strftime('%Y-%m-%d')} · Overall: **{report.overall_score:.1f}/10**"
        },
    ]
    
    if narrative:
        elements.append({
            "tag": "markdown",
            "content": narrative[:500]
        })
    
    elements.extend([
        {"tag": "hr"},
        self._build_lens_score_table(report),
        {"tag": "hr"},
        self._build_key_moments(report),
    ])
    # ...
```

**Test:** Update `tests/output/test_feishu_card.py` — add `test_card_with_narrative()` verifying narrative appears when provided.

---

### Task 2.3: Update hoplite Hermes skill

**Objective:** Upgrade the hoplite skill workflow to include LLM narrative synthesis.

**Files:** Modify `~/.hermes/skills/hoplite/SKILL.md`

**Updated workflow section:**
```markdown
## Workflow

1. Load this skill
2. Read `/tmp/hoplite/config.yaml` for API tokens
3. Run `cd /tmp/hoplite && source .venv/bin/activate && python -m src latest --full`
   - This fetches all data sources, generates MatchReport, builds narrative prompt
4. Read the output — extract the narrative prompt
5. Use the LLM to generate a tactical narrative based on the prompt (inline in this conversation)
6. Build the Feishu card using `FeishuCardBuilder.build_match_card(report, narrative=generated_narrative)`
7. Send the card to the hoplite group via `send_message` or `lark-cli`

## Output Format

Feishu v2.0 interactive card with:
- Match header (score + emoji)
- Competition + date + overall score
- **Tactical Narrative** (LLM-generated, 300-400 words, Arteta tactical perspective)
- 6-lens score table (Dimension | Rating | Key Point)
- Key moments from each lens
```

---

### Task 2.4: Full integration test

**Objective:** End-to-end test of the new pipeline.

**Steps:**
1. `cd /tmp/hoplite && source .venv/bin/activate && python -m src latest --full`
2. Verify output includes: match data, xG (if available), narrative prompt
3. Trigger hoplite skill via "hoplite latest"
4. Verify card arrives in hoplite group with narrative section

---

## Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| Understat match-matching fails (team name differences) | Low | xG is optional, graceful pass |
| Brave search context quality varies | Medium | Accept v2 surface level; v3 adds structured search |
| LLM narrative quality inconsistent | Medium | Prompt includes style guide; skill can retry |
| Card too long with narrative | Low | 500-char narrative cap in card; full text in doc (v3) |

---

## Success Metrics (v2)

- [ ] `hoplite latest --full` pulls from ≥3 data sources
- [ ] Card includes LLM-generated tactical narrative
- [ ] Narrative references at least 2 of 6 tactical lenses
- [ ] Narrative reads in Arteta tactical voice (not generic stats recap)
- [ ] Zero new API token requirements
- [ ] All existing 43 tests still pass
