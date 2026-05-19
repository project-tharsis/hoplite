# Hoplite ⚔️🔴⚪

Arsenal post-match tactical analysis engine. Extracts raw match data, then analyzes through Mikel Arteta's six mental models via LLM.

## Architecture

```
Python tools (data extraction) → SKILL.md (decision framework) → LLM (analysis + narrative) → Feishu card
                                  ↕
                        Evolution Layer (knowledge.json → patterns.py → calibration.py → prompt injection)
```

| Layer | What | Won't |
|---|---|---|
| `src/tools/extract.py` | Stats, events, context from match JSON | Judgment, scoring |
| `src/tools/analyze.py` | Orchestrates extraction → assembly | Evaluation |
| `src/features/extractor.py` | Deterministic feature extraction | Judgment |
| `src/labels/weak_labeler.py` | Rule-based weak labels for 6 models | LLM calls |
| `src/evaluation/prompt_builder.py` | Structured v2 prompt from rubric + features | — |
| `src/evaluation/calibration.py` | CalibrationComputer: guarded calibration hints | — |
| `SKILL.md` | Arteta 6 mental models + 3D assessment framework | Raw data processing |
| LLM | Qualitative analysis + Chinese narrative | — |

## Rubric & Framework Sources

- **`rubrics/arteta_v1.yaml`** — **Machine-readable canonical rubric.** Python tooling reads this file for prompt building. This is the source of truth for evaluation criteria.
- **`prompts/arteta_framework.md`** — Human-readable / legacy reference. Contains the same framework in Markdown for documentation and LLM context. **Not read by code** in the v2 pipeline.

## Arteta's 6 Mental Models

1. **Culture as OS** — Standards, energy, accountability precede tactics
2. **Where Game is Played** — Control zones, rhythm, emotion
3. **Defence as Attacking Identity** — Defending enables attacking
4. **Marginal Gains Expertized** — Specialize every department
5. **Add Capability, Keep Identity** — Evolve without losing tradition
6. **Role Clarity > Pressure** — Context, protection, clear roles

## v2 JSON Pipeline (Default Workflow)

The v2 pipeline is the recommended workflow for new evaluations:

```bash
# Step 1: Fetch latest Arsenal match data
python -m src fetch_match_data > match.json

# Step 2: Analyze (if fetch succeeded)
python -m src analyze_match < match.json > report.json

# Step 3: Prepare evaluation (features + weak labels + structured prompt)
python -m src prepare_evaluation < report.json

# Step 4: LLM evaluation (agent applies 6 mental models to the prompt)

# Step 5: Save evaluation to KB
#   Pipe {report, evaluation, features, weak_labels, versions} into save_evaluation
python -m src save_evaluation

# Step 6 (optional): Human review override
#   Pipe {match_id, reviewer, corrected signals, comments} into review_evaluation
python -m src review_evaluation

# Step 7 (optional): Replay weak labels for consistency check
python scripts/replay_history.py --kb data/knowledge.json --mode weak-label-only --output /tmp/replay.json
```

### Pipeline flow:

```
fetch_match_data → analyze_match → prepare_evaluation → LLM evaluation → save_evaluation → (optional) review_evaluation → replay_history
```

### Key CLI commands:

- **`prepare_evaluation`** — Generates features, weak labels, and structured prompt from match or report JSON. Default output is JSON (`--format json`); use `--format prompt` for prompt-only.
- **`save_evaluation`** — Validates strict v2 LLM output and persists features, weak labels, evaluation, and version metadata to KB.
- **`review_evaluation`** — Writes human review override into an existing KB entry.
- **`replay_history.py`** — Deterministic weak-label replay against stored features. Never mutates KB.

### Legacy path (backward-compatible):

`build_narrative_prompt` still works for the legacy monolithic prompt. Use the v2 pipeline above for all new evaluations.

## v2 JSON Entry Schema

Every saved v2 evaluation entry in `data/knowledge.json` has this shape:

```json
{
  "match_id": "fixture-id",
  "timestamp": "2026-05-19T00:00:00",
  "opponent": "Bournemouth",
  "score": "3-2",
  "result": "W",
  "competition": "Premier League",
  "pre_match_context": {
    "opponent": "Bournemouth",
    "opponent_quality": "mid_table",
    "venue": "away",
    "competition_stage": "league_early"
  },
  "predicted_plan": {},
  "features": {
    "result": "W",
    "score_margin": 1,
    "possession_delta": 14.0,
    "shot_delta": -3,
    "goals_by_substitutes": 0,
    "missing_data": ["xG", "pressing", "pressing_recoveries", "transition"]
  },
  "weak_labels": {
    "model_signals": {},
    "dimension_signals": {},
    "overall_signal": "🟡",
    "confidence": {},
    "evidence_refs": {},
    "missing_data_penalty": true,
    "weak_label_version": "v1"
  },
  "evaluation": {
    "source": "llm",
    "model_signals": {},
    "dimension_signals": {},
    "overall_signal": "🟡",
    "confidence": {},
    "evidence": {},
    "missing_or_weak_evidence": [],
    "weak_label_disagreements": [],
    "narrative": ""
  },
  "features_version": "v1",
  "weak_label_version": "v1",
  "rubric_version": "arteta_v1",
  "prompt_builder_version": "v1",
  "human_override": null
}
```

Existing legacy entries may lack `features` and `weak_labels`. Readers tolerate missing fields; new v2 writes must include them.

## Evolution Layer

Self-iterating through historical match patterns:

- `data/knowledge.json` — stores per-match context + predicted plan + features + weak labels + evaluation + versions
- `src/evaluation/patterns.py` — `PatternComputer`: computes historical patterns for similar match contexts (legacy-compatible aggregator)
- `src/evaluation/calibration.py` — `CalibrationComputer`: guarded calibration hints with sample-quality accounting, confidence capping, and guardrails. New v2 code should use this instead of `PatternComputer` directly.
- `src/evaluation/predictor.py` — weights pre-match predictions using historical effectiveness
- `src/tools/prompt.py` — injects historical pattern references into LLM prompt
- `scripts/replay_history.py` — deterministic weak-label replay, never mutates KB

## Persistence

Currently JSON-based (`data/knowledge.json`). The data volume is small enough for JSON, and the system is designed for replayability and audit.

**Database migration is intentionally deferred.** The JSON format supports all current needs: feature snapshots, weak labels, version tracking, and human overrides. A future migration to SQLite or Postgres will be considered when data volume or query complexity warrants it.

## Quick Start

```bash
git clone https://github.com/project-tharsis/hoplite.git
cd hoplite
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp config.example.yaml config.yaml  # add API keys

# v2 pipeline (recommended)
python -m src fetch_match_data > match.json
python -m src analyze_match < match.json > report.json
python -m src prepare_evaluation < report.json
```

## Data Sources

- [API-Football](https://api-football.com) — events, lineups, stats (free tier)
- [football-data.org](https://football-data.org) — fixtures, results (free tier)

## License

MIT
