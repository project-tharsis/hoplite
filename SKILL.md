---
name: hoplite
description: "Hoplite v4 — Arsenal tactical analysis MCP skill. Python extracts raw data; LLM applies Arteta's 6 mental models for qualitative analysis."
version: 4.2.0
---

# Hoplite — Arsenal Tactical Analysis Engine 🔴⚪

Post-match analysis through Mikel Arteta's six mental models. Python extracts raw data; LLM applies decision framework; narrative → Feishu card + Knowledge Base.

**Architecture:**
```
Python tools (raw data extraction) → SKILL.md (Arteta decision framework) → Agent/LLM (qualitative analysis + narrative) → Feishu card
                                    ↕
                           Evolution Layer (knowledge.json → patterns.py → calibration.py → prompt injection)
```

**Separation of concerns:**
- `src/tools/extract.py` — pure stats, events, context. No judgment.
- `src/report.py` — data container. No scoring.
- `src/tools/analyze.py` — orchestrates extraction → assembly
- `src/tools/prompt.py` — injects raw data + Arteta framework + historical patterns as LLM prompt (legacy path)
- `src/tools/prepare_evaluation.py` — v2 pipeline: features + weak labels + structured prompt in one CLI
- `src/tools/save_evaluation.py` — v2 pipeline: validates strict LLM output, persists to KB
- `src/tools/review.py` — v2 pipeline: human review override write path
- `src/features/extractor.py` — deterministic feature extraction from match or report JSON
- `src/labels/weak_labeler.py` — rule-based weak labels for 6 models + 3 dimensions
- `src/evaluation/prompt_builder.py` — structured v2 prompt from rubric + features + calibration hints
- `src/evaluation/calibration.py` — CalibrationComputer: guarded calibration hints from JSON history
- `src/evaluation/patterns.py` — PatternComputer: historical patterns (legacy-compatible aggregator)
- `src/evaluation/knowledge.py` — local JSON knowledge base for match storage/retrieval
- `scripts/ingest_history.py` — batch fetch historical matches from API-Football, populate KB
- `scripts/replay_history.py` — deterministic weak-label replay, never mutates KB
- **SKILL.md (this file)** — the Arteta decision brain: 6 mental model framework, 3D assessment logic, writing rules
- **Agent (LLM)** — applies framework to data, produces signals + narrative

**Rubric sources:**
- `rubrics/arteta_v1.yaml` — **Machine-readable canonical rubric** (source of truth for v2 pipeline)
- `prompts/arteta_framework.md` — Human-readable / legacy reference (not read by v2 code)

## Language

All user-facing output MUST be in Chinese (简体中文) with Elio's voice: short lines, conversational, Chinese + English terms blended without spaces (e.g. "rest-defence" not "rest defence"). No formal/academic tone.

## Triggers

User says any of:
- "analyze Arsenal latest match"
- "hoplite latest"  
- "Arsenal match report"
- "review Arsenal game"

## Workflow (v2 Pipeline — Default)

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

### Step 3: Prepare Evaluation (v2 structured prompt)
Pipe the report JSON into the `prepare_evaluation` tool:
```bash
source .venv/bin/activate && echo '<report_json>' | python -m src prepare_evaluation
```
Output: JSON with `{features, weak_labels, rubric_version, prompt}`.

For prompt-only (copy/paste to LLM):
```bash
source .venv/bin/activate && echo '<report_json>' | python -m src prepare_evaluation --format prompt
```

The prompt uses `PromptBuilder` with the canonical rubric (`rubrics/arteta_v1.yaml`) and includes calibration hints from `CalibrationComputer` when available.

### Step 4: LLM Evaluation + Narrative
**This is YOUR job.**

The prompt from Step 3 contains:
- Extracted features (deterministic)
- Weak label baseline (deterministic)
- Calibration hints from historical matches (when available)
- Arteta's 6 mental model assessment framework
- 3-dimension assessment framework (L1→L2→L3 satisfaction, execution, adjustment)
- Writing style rules

**You must:**
1. Apply each mental model to the raw data → produce signal + evidence
2. Apply 3-dimension assessment → produce signals
3. Vote overall signal from 3 dimensions (≥2🟢→🟢, ≥2🔴→🔴, else🟡)
4. Write 300-400 word Chinese tactical narrative
5. Output as strict v2 JSON (see schema below)

**Strict v2 output schema** (all fields required):
```json
{
  "overall_signal": "🟡",
  "model_signals": {"1": "🟢", "2": "🟡", "3": "🟢", "4": "🟡", "5": "🟢", "6": "🟡"},
  "dimension_signals": {"execution": "🟢", "adjustment": "🟡", "satisfaction": "🟢"},
  "confidence": {"1": "high", "2": "medium", ...},
  "evidence": {"1": ["evidence string", ...], "2": [...], ...},
  "missing_or_weak_evidence": ["list of missing data points"],
  "weak_label_disagreements": ["list of disagreements with weak labels"],
  "narrative": "300-400 word Chinese tactical narrative"
}
```

### Step 5: Save Evaluation to KB
Pipe the report + evaluation + features + weak labels into `save_evaluation`:
```bash
source .venv/bin/activate && echo '{"report": <report>, "evaluation": <eval>, "features": <features>, "weak_labels": <weak_labels>, "versions": {...}}' | python -m src save_evaluation
```
Output: `{ok: true, entry: {...}}` — the saved KB entry with features, weak labels, evaluation, and version metadata.

### Step 6 (optional): Build & Send Card
Pipe the report JSON + narrative into the `build_card` tool:
```bash
source .venv/bin/activate && echo '{"report": <report_json>, "narrative": "<narrative>"}' | python -m src build_card
```
Output: Card JSON file path. Send via `lark-cli` with your chat_id.

### Step 7 (optional): Human Review Override
For sampled human review, pipe review data into `review_evaluation`:
```bash
source .venv/bin/activate && echo '{"match_id": "123", "reviewer": "shuo", "review_status": "corrected", "corrected_overall_signal": "🟡", "corrected_model_signals": {...}}' | python -m src review_evaluation
```
This writes `human_override` into the KB entry. Original evaluation is preserved.

### Step 8 (optional): Replay Weak Labels
For consistency checking across historical entries:
```bash
python scripts/replay_history.py --kb data/knowledge.json --mode weak-label-only --output /tmp/replay.json
```
Deterministic, no LLM calls, never mutates KB.

### Legacy Path (backward-compatible)

`build_narrative_prompt` still works for the legacy monolithic prompt:
```bash
source .venv/bin/activate && echo '{"report": <report_json>}' | python -m src build_narrative_prompt
```
Use the v2 pipeline (Steps 3-5) for all new evaluations.

## Output Format

Feishu v4.0 interactive card with:
- Match header (score + overall signal emoji)
- 3-dimension summary line (执行🟢 调整🟡 满意🟢)
- 6 mental model summaries (signal + one-liner each)
- Tactical Narrative (LLM-generated, objective Chinese)
- 📄 完整复盘 button (doc link)

## Arteta's 6 Mental Models + 3D Assessment (Decision Brain)

**Canonical source:** `rubrics/arteta_v1.yaml` — this is the machine-readable canonical rubric.
Python's `PromptBuilder` reads it for v2 structured prompts.
`prompts/arteta_framework.md` is the human-readable reference (not read by v2 code).

For detailed signal criteria per model and the 3-dimension L1→L2→L3 satisfaction logic,
see the canonical rubric file.

## Evolution Layer

Hoplite's decision brain self-improves through a multi-tier evolution layer:

- **Data** (`data/knowledge.json`) — Every match saves context + plan + features + weak labels + signals + versions
- **Patterns** (`src/evaluation/patterns.py`) — `PatternComputer`: queries similar matches, computes signal distributions (legacy-compatible aggregator)
- **Calibration** (`src/evaluation/calibration.py`) — `CalibrationComputer`: guarded calibration hints with sample-quality accounting, legacy-entry detection, confidence capping, and guardrails. New v2 code should use this.
- **Injection** (`src/tools/prompt.py` + `predictor.py`) — Historical patterns injected into LLM prompt
- **Replay** (`scripts/replay_history.py`) — Deterministic weak-label replay for consistency checking

Batch-ingest historical matches (2022-2024, ~150 matches) via:
```bash
python scripts/ingest_history.py --season 2024 --league 39
```

## Historical Backfill Script

**Location:** `scripts/backfill_history.py`

Upgrades selected legacy KB entries into v2-compatible, feature-backed entries using a manifest-driven workflow.

### 4 Modes

1. **`inventory`** — Reads KB and manifest, reports counts (total, with features, legacy-only, seed-set size, validation-set size, missing inputs, manifest IDs not in KB). No writes.
2. **`prepare-seed`** — For seed-set entries: loads raw match JSON or analyze report JSON, runs `prepare_evaluation`, writes `prepare_results.jsonl` and `llm_jobs.jsonl`. Produces LLM job prompts but does NOT call an LLM. No KB mutation.
3. **`apply-features`** — Reads prepare results from a run directory, applies features, weak_labels, version fields, and backfill metadata to KB entries. Normalizes legacy evaluation if needed (copies original into `legacy_evaluation`). Requires `--run` and `--write`.
4. **`validate-rest`** — Dry-run prepare for validation-set entries, compares weak labels with legacy signals, writes `validation_report.json`. Does NOT mutate KB.

### Manifest Format

`data/backfill/backfill_manifest.json`:
```json
{
  "version": "v1",
  "seed_set": [
    {
      "legacy_match_id": "1",
      "fixture_id": 123456,
      "opponent": "Chelsea",
      "date": "2025-05-01",
      "raw_match_path": "data/backfill/raw/123456.json",
      "report_path": "data/backfill/reports/123456.json"
    }
  ],
  "validation_set": [
    {
      "legacy_match_id": "31",
      "fixture_id": 789012,
      "opponent": "Everton",
      "date": "2025-08-15"
    }
  ]
}
```

At least one of `raw_match_path` or `report_path` is required for seed-set entries.

### Usage

```bash
# Inventory
python scripts/backfill_history.py --kb data/knowledge.json --manifest data/backfill/backfill_manifest.json --mode inventory

# Prepare seed artifacts
python scripts/backfill_history.py --kb data/knowledge.json --manifest data/backfill/backfill_manifest.json --mode prepare-seed --output data/backfill/runs/20260519-seed

# Apply features (requires --write)
python scripts/backfill_history.py --kb data/knowledge.json --manifest data/backfill/backfill_manifest.json --mode apply-features --run data/backfill/runs/20260519-seed --write

# Validate rest (dry-run)
python scripts/backfill_history.py --kb data/knowledge.json --manifest data/backfill/backfill_manifest.json --mode validate-rest --output data/backfill/runs/20260519-validate
```

### Safety Rules

- **`--write` required:** `apply-features` will not mutate KB without `--write`
- **Before/after snapshots:** `apply-features` saves `knowledge.before.json` and `knowledge.after.json` in the run directory
- **Idempotency:** Re-running `apply-features --write` skips entries that already have `features` and `weak_labels` (unless `--force`)
- **Legacy evaluation preserved:** Original evaluation is copied to `legacy_evaluation` before normalization
- **No entries deleted:** Only adds fields, never removes entries or unknown fields

## Project Location

Key files and directories:

```
hoplite/
├── rubrics/arteta_v1.yaml          # Machine-readable canonical rubric
├── prompts/arteta_framework.md     # Human-readable framework reference
├── data/knowledge.json             # JSON knowledge base (persistence layer)
├── src/
│   ├── tools/
│   │   ├── prepare_evaluation.py   # v2: features + weak labels + prompt
│   │   ├── save_evaluation.py      # v2: validate + persist evaluation
│   │   ├── review.py               # v2: human review override
│   │   ├── extract.py              # Pure data extraction
│   │   ├── analyze.py              # Extraction orchestrator
│   │   ├── prompt.py               # Legacy prompt builder
│   │   ├── fetch.py                # API-Football fetcher
│   │   └── card.py                 # Feishu card builder
│   ├── features/extractor.py       # Deterministic feature extraction
│   ├── labels/weak_labeler.py      # Rule-based weak labels
│   ├── evaluation/
│   │   ├── calibration.py          # CalibrationComputer (v2)
│   │   ├── patterns.py             # PatternComputer (legacy-compatible)
│   │   ├── predictor.py            # Pre-match plan prediction
│   │   ├── prompt_builder.py       # Structured v2 prompt builder
│   │   ├── knowledge.py            # JSON knowledge base
│   │   └── llm_result.py           # LLM output validation (strict mode)
│   └── paths.py                    # Canonical project paths
├── scripts/
│   ├── replay_history.py           # Deterministic weak-label replay
│   ├── ingest_history.py           # Batch historical data fetch
│   └── batch_prep_prompts.py       # Batch prompt preparation
└── tests/                          # Test suite
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

- You orchestrate the tool sequence (not automated in Python)
- You apply the 6 mental models from the rubric to raw data from Step 3's prompt
- You apply the 3-dimension assessment framework
- You produce signals (overall + per-model + per-dimension) with evidence and confidence
- You write the tactical narrative (300-400 words, Chinese, Elio voice)
- You output strict v2 JSON (all required fields — see Step 4 schema)
- Python tools only do data: fetch, extract, features, weak labels, prompt building, card JSON
