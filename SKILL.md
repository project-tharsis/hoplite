---
name: hoplite
description: "Hoplite v4 — Arsenal tactical analysis MCP skill. Python extracts raw data; LLM applies Arteta's 6 mental models for qualitative analysis."
version: 4.1.0
---

# Hoplite — Arsenal Tactical Analysis Engine 🔴⚪

Post-match analysis through Mikel Arteta's six mental models. Python extracts raw data; LLM applies decision framework; narrative → Feishu card + Knowledge Base.

**Architecture:**
```
Python tools (raw data extraction) → SKILL.md (Arteta decision framework) → Agent/LLM (qualitative analysis + narrative) → Feishu card
                                    ↕
                           Evolution Layer (knowledge.json → patterns.py → prompt injection)
```

**Separation of concerns:**
- `src/tools/extract.py` — pure stats, events, context. No judgment.
- `src/report.py` — data container. No scoring.
- `src/tools/analyze.py` — orchestrates extraction → assembly
- `src/tools/prompt.py` — injects raw data + Arteta framework + historical patterns as LLM prompt
- `src/evaluation/predictor.py` — directional pre-match plan prediction, KB-weighted when history available
- `src/evaluation/patterns.py` — computes historical patterns (similar matches, focus area effectiveness, model trends)
- `src/evaluation/knowledge.py` — local JSON knowledge base for match storage/retrieval
- `scripts/ingest_history.py` — batch fetch historical matches from API-Football, populate KB
- **SKILL.md (this file)** — the Arteta decision brain: 6 mental model framework, 3D assessment logic, writing rules
- **Agent (LLM)** — applies framework to data, produces signals + narrative

## Language

All user-facing output MUST be in Chinese (简体中文) with Elio's voice: short lines, conversational, Chinese + English terms blended without spaces (e.g. "rest-defence" not "rest defence"). No formal/academic tone.

## Triggers

User says any of:
- "analyze Arsenal latest match"
- "hoplite latest"  
- "Arsenal match report"
- "review Arsenal game"

## Workflow (5-step sequence)

### Step 1: Fetch Match Data
Run the `fetch_match_data` tool to get the latest Arsenal match with xG data:
```bash
source .venv/bin/activate && python -m src fetch_match_data
```
Output: Match JSON (fixture_id, teams, score, xG, events, etc.)

If config.yaml missing → tell user to copy config.example.yaml → config.yaml and add API tokens.

### Step 2: Analyze Match (extract raw data)
Pipe the match JSON into the `analyze_match` tool:
```bash
source .venv/bin/activate && echo '<match_json>' | python -m src analyze_match
```
Output: MatchReport JSON with stats, events, context, predicted_plan, set_pieces, sub_impact.

### Step 3: Build Narrative Prompt (inject Arteta framework)
Pipe the report JSON into the `build_narrative_prompt` tool:
```bash
source .venv/bin/activate && echo '{"report": <report_json>}' | python -m src build_narrative_prompt
```
Output: Prompt string with raw data + Arteta 6 mental model framework + 3D assessment logic.

### Step 4: LLM Evaluation + Narrative
**This is YOUR job.**

The prompt from Step 3 contains:
- Raw match data (stats, events, set pieces, subs, context)
- Predicted pre-match plan
- Arteta's 6 mental model assessment framework (what to look at, how to decide 🟢🟡🔴)
- 3-dimension assessment framework (L1→L2→L3 satisfaction, execution, adjustment)
- Writing style rules

**You must:**
1. Apply each mental model to the raw data → produce signal + evidence
2. Apply 3-dimension assessment → produce signals
3. Vote overall signal from 3 dimensions (≥2🟢→🟢, ≥2🔴→🔴, else🟡)
4. Write 300-400 word Chinese tactical narrative
5. Output as JSON: `{overall_signal, model_signals: {1-6}, dimension_signals: {execution, adjustment, satisfaction}, narrative}`

### Step 5: Build & Send Card
Pipe the report JSON + narrative into the `build_card` tool:
```bash
source .venv/bin/activate && echo '{"report": <report_json>, "narrative": "<narrative>"}' | python -m src build_card
```
Output: Card JSON file path. Send via `lark-cli` with your chat_id.

## Output Format

Feishu v4.0 interactive card with:
- Match header (score + overall signal emoji)
- 3-dimension summary line (执行🟢 调整🟡 满意🟢)
- 6 mental model summaries (signal + one-liner each)
- Tactical Narrative (LLM-generated, objective Chinese)
- 📄 完整复盘 button (doc link)

## Arteta's 6 Mental Models + 3D Assessment (Decision Brain)

**Canonical source:** `prompts/arteta_framework.md` — this is the single source of truth.
Python's `prompt.py` reads it; SKILL.md references it. Never dual-write evaluation rules.

For detailed signal criteria per model and the 3-dimension L1→L2→L3 satisfaction logic,
see the canonical framework file.

## Evolution Layer

Hoplite's decision brain self-improves through a three-tier evolution layer:

- **Data** (`data/knowledge.json`) — Every match saves context + plan + signals
- **Patterns** (`src/evaluation/patterns.py`) — Queries similar matches, computes signal distributions
- **Injection** (`src/tools/prompt.py` + `predictor.py`) — Historical patterns injected into LLM prompt

Batch-ingest historical matches (2022-2024, ~150 matches) via:
```bash
python scripts/ingest_history.py --season 2024 --league 39
```

## Requirements

- `config.yaml` with API tokens (copy from `config.example.yaml`)
- Python 3.11+ (create `.venv/`: `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`)
- `lark-cli` for Feishu card delivery (optional)
- `jq` available on PATH (for card sending)

## Data Sources

- API-Football — match events, lineups, stats (free tier)
- football-data.org — fixtures, results, standings (free tier)
- Understat — xG data

API-Football free tier is season-lagged (~1 year behind). See `references/data-source-limits.md`.

## Agent Responsibilities

- You orchestrate the 5-step tool sequence (not automated in Python)
- You apply the 6 mental models from this file to raw data from Step 3's prompt
- You apply the 3-dimension assessment framework
- You produce signals (overall + per-model + per-dimension)
- You write the tactical narrative (300-400 words, Chinese, Elio voice)
- You output final JSON with signals + narrative
- Python tools only do data: fetch, extract, prompt building, card JSON
