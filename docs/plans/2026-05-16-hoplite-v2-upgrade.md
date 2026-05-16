# Hoplite v2 Upgrade Plan — MCP Skill Architecture

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Refactor Hoplite from a monolithic CLI into a composable MCP skill — discrete Python tools for data, SKILL.md for orchestration, LLM (agent) for narrative synthesis. Open-source ready.

**Architecture Decision:**
Hoplite is an MCP skill: Python scripts are tools (fetch data, analyze, build prompt, build card), SKILL.md defines the tool-call workflow, and the agent/LLM does the narrative synthesis. This cleanly separates three layers: **data tools** (Python, stateless) → **orchestration** (SKILL.md, tool calls) → **narrative** (LLM, context-aware). Zero new API keys — LLM uses existing Hermes model.

---

## Architecture Shift

```
V1 (monolithic CLI):
  python -m src latest  →  fetch + analyze + build card + send
                              ↑ one big Python process does everything

V2 (MCP skill):
  SKILL.md workflow:
    1. call fetch_match_data tool        → Match JSON
    2. call analyze_match tool           → MatchReport JSON  
    3. call build_narrative_prompt tool  → prompt text
    4. LLM generates narrative           → narrative text
    5. call build_card tool              → card JSON
    6. send card to chat
       ↑ agent/LLM orchestrates, Python does data work
```

The agent/LLM is the **conductor**. The Python tools are the **orchestra**. SKILL.md is the **score**.

---

## What Elio Needs To Do

**Nothing from v1 changes.** Same config.yaml, same API tokens. Zero new registrations, zero new keys.

---

## Tasks (5 tasks, ~45 min total)

### Task 2.0: Restructure CLI into discrete tools

**Objective:** Decompose the monolithic `cli.py` into focused, single-responsibility Python scripts. Each tool takes structured input, produces JSON output to stdout. No side effects except file I/O for card temp files.

**Files:**
- Modify: `src/__main__.py` — becomes tool dispatcher `python -m src <tool_name> <args>`
- Create: `src/tools/__init__.py`
- Create: `src/tools/fetch.py` — `fetch_match_data(team, status, limit) → Match JSON`
- Create: `src/tools/analyze.py` — `analyze_match(match_json) → MatchReport JSON`
- Create: `src/tools/prompt.py` — `build_narrative_prompt(report_json) → prompt text`
- Create: `src/tools/card.py` — `build_card(report_json, narrative) → card JSON (saved to temp file, path printed)`

**Tool signatures:**

```python
# src/tools/fetch.py
def fetch_match_data(
    team: str = "Arsenal",
    status: str = "FINISHED",
    limit: int = 1
) -> dict:
    """
    Fetch latest match data for a team from football-data.org.
    Returns Match as JSON dict.
    Also tries Understat for xG merge if available.
    """
    # 1. Load config
    # 2. football-data.org → match identity
    # 3. Understat → xG merge (optional, graceful failure)
    # 4. API-Football → events when fixture_id known
    # 5. Return match dict (serializable Match.__dict__ equivalent)
```

```python
# src/tools/analyze.py  
def analyze_match(
    match_json: dict,
    search_queries: list[str] = None
) -> dict:
    """
    Run 6 tactical lenses against a match, return MatchReport as JSON dict.
    Generates Brave search queries for each lens (actual search done by agent).
    """
    # 1. Deserialize Match from JSON
    # 2. Run ReportOrchestrator.generate(match)
    # 3. Build search queries for agent to execute
    # 4. Return {report: {...}, search_queries: [...]}
```

```python
# src/tools/prompt.py
def build_narrative_prompt(
    report_json: dict,
    search_context: str = ""
) -> str:
    """
    Build an Arteta-style tactical narrative prompt from MatchReport + search context.
    Returns the prompt string for the agent/LLM to synthesize.
    """
    # Uses NarrativePromptBuilder (same as plan, just called from here)
```

```python
# src/tools/card.py
def build_card(
    report_json: dict,
    narrative: str = ""
) -> str:
    """
    Build Feishu v2.0 interactive card from MatchReport + narrative.
    Saves card JSON to temp file, returns file path.
    Agent sends the card via lark-cli.
    """
    # Uses FeishuCardBuilder
    # Returns: path to compact card JSON file
```

**Test:** Each tool has an integration test verifying JSON input → JSON output.

---

### Task 2.1: NarrativePromptBuilder module

**Objective:** Same as original plan — generate Arteta-style tactical prompt from MatchReport.

**Files:** Create `src/tools/prompt.py` (includes NarrativePromptBuilder logic)

**Details:** Same prompt template as original plan — 300-400 word target, Arteta tactical voice, WHY not WHAT analysis, one-sentence verdict.

---

### Task 2.2: Upgrade FeishuCardBuilder — narrative section

**Objective:** Add narrative summary to card (3-4 key sentences), placed between header and score table.

**Files:** Modify `src/output/feishu_card.py`

**Changes:**
- `build_match_card(report, narrative="")` — narrative parameter
- Card card: narrative summary (3-4 sentences)  
- Full narrative reserved for Feishu doc (v3)
- Test: `test_card_with_narrative()`

---

### Task 2.3: Rewrite SKILL.md as MCP skill orchestration

**Objective:** SKILL.md becomes the conductor — defines tool-call sequence, agent responsibilities, and output format.

**Files:** Overwrite `~/.hermes/skills/hoplite/SKILL.md`

**Key sections:**
```markdown
## Tool Calls (sequential)

### Step 1: Fetch Match Data
Run: python -m src fetch_match_data --team Arsenal --status FINISHED --limit 1
Input: none (config from config.yaml)
Output: Match JSON with xG when available

### Step 2: Analyze Match
Run: python -m src analyze_match < match.json
Input: Match JSON from Step 1
Output: MatchReport JSON + search_queries list

### Step 3: Execute Search Queries
For each query in search_queries:
  Use Brave Search MCP tool to find post-match tactical analysis
  Collect results as search_context

### Step 4: Build Narrative Prompt  
Run: python -m src build_narrative_prompt < report.json
Input: MatchReport JSON + search_context
Output: Prompt text for LLM

### Step 5: LLM Narrative Synthesis
YOU (the agent) generate the tactical narrative.
Read the prompt from Step 4. Write in Arteta tactical voice.
300-400 words. Analyze WHY not WHAT.

### Step 6: Build & Send Card
Run: python -m src build_card < report.json (with narrative)
Then: lark-cli im +messages-send --card from output path
Target: same channel user invoked from

## Agent Responsibilities
- You orchestrate the tool sequence (this is not automated in Python)
- You execute Brave searches (MCP brave_brave_web_search)
- You write the tactical narrative (this is YOUR job, not a tool's job)
- You send the card (lark-cli)
```

---

### Task 2.4: Full integration test

**Objective:** End-to-end test of the MCP skill pipeline.

**Steps:**
1. Trigger "hoplite latest" in Hermes
2. Verify tool sequence executes in order
3. Verify Brave search returns tactical analysis context
4. Verify LLM generates narrative with Arteta tactical voice
5. Verify card arrives in hoplite group with narrative + score table

**Exit criteria:**
- Agent completes all 6 steps autonomously
- Narrative references ≥2 tactical lenses
- Card has narrative section
- Zero human intervention between trigger and delivery

---

## Success Metrics (v2)

- [ ] All Python tools are composable (each does ONE thing, JSON in/out)
- [ ] SKILL.md fully defines the workflow — no implicit logic in Python
- [ ] Agent/LLM generates narrative autonomously
- [ ] Card includes narrative + 6-lens score table
- [ ] Narrative reads in Arteta tactical voice
- [ ] Zero new API keys
- [ ] All existing 43 tests still pass
- [ ] Repo structure is open-source ready (clear tool boundaries, documented SKILL.md)

---

## Open Source Structure

```
hoplite/                    # Installable Hermes MCP skill
├── SKILL.md                # Skill definition + tool workflow
├── README.md
├── requirements.txt
├── config.example.yaml
├── src/
│   ├── __init__.py
│   ├── __main__.py         # Tool dispatcher
│   ├── tools/              # MCP-exposed tools
│   │   ├── fetch.py        # → fetch_match_data
│   │   ├── analyze.py      # → analyze_match
│   │   ├── prompt.py       # → build_narrative_prompt
│   │   └── card.py         # → build_card
│   ├── data/               # Data source clients
│   │   ├── football_data.py
│   │   ├── api_football.py
│   │   ├── understat.py
│   │   └── search_source.py
│   ├── analysis/           # 6 tactical lenses
│   │   ├── base.py
│   │   ├── set_pieces.py
│   │   ├── goals.py
│   │   ├── build_up.py
│   │   ├── pressing.py
│   │   ├── rest_defence.py
│   │   └── overload.py
│   ├── models/             # Data models
│   │   └── match.py
│   ├── report.py           # ReportOrchestrator + MatchReport
│   └── output/             # Output formatting
│       └── feishu_card.py
├── tests/
└── docs/
    └── plans/
```

Any Hermes user can `hermes skill install Project-Tharsis/hoplite`, fill in their API tokens, and get Arsenal tactical analysis in their Feishu.
