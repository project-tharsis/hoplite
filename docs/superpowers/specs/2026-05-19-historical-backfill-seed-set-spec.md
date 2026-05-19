# Hoplite Spec: Historical Backfill Seed Set Pipeline

Date: 2026-05-19
Status: Ready for implementation
Audience: Mimo implementation agent

## 1. Context

The JSON Pipeline Closure work is complete. The v2 path now supports:

- `prepare_evaluation`: raw match or analyze report → features, weak labels, calibration-aware prompt
- `save_evaluation`: strict v2 LLM output → `data/knowledge.json`
- `review_evaluation`: human override
- `CalibrationComputer`: guarded history hints
- `replay_history.py`: deterministic weak-label replay

Current `data/knowledge.json` is still legacy-only:

- 111 entries
- 0 entries with `features`
- 0 entries with `weak_labels`
- existing entries contain context, predicted plan, old model signals, and old dimension signals
- existing entries do not contain raw stats/events/report snapshots

The next step is not auto-evolution yet. The next step is to create a controlled historical backfill pipeline so a small high-quality seed set can become feature-backed and replayable.

## 2. Product Goal

Build a safe batch backfill workflow that upgrades selected historical matches into v2-compatible, feature-backed JSON entries.

The first target is:

1. Select about 30 historical matches as a seed set.
2. Fetch or attach raw match data for those matches.
3. Run `analyze_match` and `prepare_evaluation`.
4. Persist raw/report snapshots for replay.
5. Add `features`, `weak_labels`, version fields, and backfill metadata to `data/knowledge.json`.
6. Produce strict LLM evaluation jobs for any seed matches that need refreshed v2 evaluation.
7. Keep the remaining 70+ historical matches as validation candidates for later dry-run comparison.

This creates the data foundation for later self-iteration phases.

## 3. Non-Goals

- Do not implement automatic rubric evolution.
- Do not implement automatic weak-label rule promotion.
- Do not migrate JSON to a database.
- Do not fake missing raw stats/events from legacy fields.
- Do not overwrite legacy human/LLM judgments without explicit strict v2 evaluation input.
- Do not require all 111 historical matches to be fully backfilled in this phase.
- Do not make live API calls in tests.

## 4. Core Principle

Backfill must be evidence-preserving.

If raw match data or analyze report data is unavailable, the tool may normalize legacy structure, but it must not invent feature values.

Allowed:

- Store `features_version: "legacy-none"` for entries with no features.
- Add `dimension_signals` from existing legacy dimension fields.
- Add backfill status such as `missing_raw_data`.
- Generate features from real raw match JSON or real analyze report JSON.

Not allowed:

- Guess shots, xG, substitutions, cards, or set pieces from the scoreline.
- Mark an entry as v2 feature-backed without stored raw/report evidence.
- Replace old evaluation with a new v2 evaluation unless strict validation passes.

## 5. Data Requirements

### 5.1 Minimal Legacy Entry

Existing `knowledge.json` entries may contain only:

```json
{
  "match_id": "1",
  "timestamp": "2025-05-01T00:00:00",
  "opponent": "Chelsea",
  "score": "3-1",
  "result": "W",
  "competition": "Premier League",
  "pre_match_context": {},
  "predicted_plan": {},
  "evaluation": {
    "execution_signal": "🟡",
    "adjustment_signal": "🟡",
    "satisfaction_signal": "🟡",
    "model_signals": {}
  }
}
```

This is enough only for legacy normalization. It is not enough for feature backfill.

### 5.2 Feature-Backfill Input

Each seed-set match needs one of these inputs:

1. Raw match JSON accepted by `prepare_evaluation`.
2. Analyze report JSON accepted by `prepare_evaluation`.

Raw match JSON should include, when available:

- `fixture_id`
- `date`
- `competition`
- `home_team`
- `away_team`
- `home_score`
- `away_score`
- `home_stats`
- `away_stats`
- `events`
- xG fields if available
- API-Football enriched event/stat fields if available

Analyze report JSON should include:

- `match`
- `stats`
- `key_events`
- `context`
- `set_pieces`
- `sub_impact`
- `predicted_plan`

### 5.3 Manifest Input

Do not assume legacy `match_id` is a real API fixture ID. Some legacy entries use synthetic IDs like `"1"`.

Create a manifest file:

```text
data/backfill/backfill_manifest.json
```

Shape:

```json
{
  "version": "v1",
  "seed_set": [
    {
      "legacy_match_id": "1",
      "fixture_id": 123456,
      "opponent": "Chelsea",
      "date": "2025-05-01",
      "source": "api_football",
      "raw_match_path": "data/backfill/raw/123456.json",
      "report_path": "data/backfill/reports/123456.json",
      "notes": "top6 home win seed case"
    }
  ],
  "validation_set": [
    {
      "legacy_match_id": "31",
      "fixture_id": 789012,
      "opponent": "Everton",
      "date": "2025-08-15",
      "source": "api_football"
    }
  ]
}
```

Rules:

- `legacy_match_id` is required.
- `fixture_id` is useful metadata, but it is not enough by itself for reproducible feature backfill.
- At least one of `raw_match_path` or `report_path` is required for seed-set feature backfill unless the implementation explicitly supports `--fetch-missing`.
- `raw_match_path` and `report_path` are preferred because they make the run reproducible without network.
- `validation_set` is optional in this phase.

## 6. Target Artifacts

Backfill should create a run directory:

```text
data/backfill/runs/YYYYMMDD-HHMMSS/
```

Inside each run:

```text
manifest_snapshot.json
inventory_report.json
prepare_results.jsonl
llm_jobs.jsonl
apply_report.json
validation_report.json
knowledge.before.json
knowledge.after.json
```

`knowledge.before.json` and `knowledge.after.json` are written only by `apply-features`.
`inventory`, `prepare-seed`, and `validate-rest` may omit them because they do not mutate the KB.

Raw and report snapshots should live outside the run directory so future runs can reuse them:

```text
data/backfill/raw/<fixture_id>.json
data/backfill/reports/<fixture_id>.json
```

## 7. Target Knowledge Entry Additions

For each successfully prepared seed-set match, update its existing KB entry without losing legacy fields.

Add:

```json
{
  "features": {},
  "weak_labels": {},
  "features_version": "v1",
  "weak_label_version": "v1",
  "rubric_version": "arteta_v1",
  "prompt_builder_version": "v1",
  "backfill": {
    "status": "feature_backfilled",
    "run_id": "20260519-153000",
    "legacy_match_id": "1",
    "fixture_id": "123456",
    "raw_match_path": "data/backfill/raw/123456.json",
    "report_path": "data/backfill/reports/123456.json",
    "prepared_at": "2026-05-19T15:30:00",
    "needs_v2_evaluation": true
  }
}
```

Normalize existing evaluation only if needed:

```json
{
  "legacy_evaluation": {
    "execution_signal": "🟡",
    "adjustment_signal": "🟡",
    "satisfaction_signal": "🟡",
    "model_signals": {}
  },
  "evaluation": {
    "source": "legacy",
    "model_signals": {},
    "dimension_signals": {
      "execution": "🟡",
      "adjustment": "🟡",
      "satisfaction": "🟡"
    },
    "overall_signal": "🟡",
    "narrative": ""
  }
}
```

If the tool reshapes legacy `evaluation`, it must first copy the original object into `legacy_evaluation`.

If a strict v2 LLM evaluation is later supplied, `save_evaluation` may replace `evaluation.source` with `"llm"` and persist strict v2 fields.

## 8. Required CLI

Add a dedicated backfill tool. Prefer a script because it is operational, not a normal single-match skill command:

```bash
python scripts/backfill_history.py \
  --kb data/knowledge.json \
  --manifest data/backfill/backfill_manifest.json \
  --mode inventory \
  --output data/backfill/runs/dev
```

Common flags:

- `--kb`: path to `knowledge.json`
- `--manifest`: path to manifest
- `--mode`: one of `inventory`, `prepare-seed`, `apply-features`, `validate-rest`
- `--output`: run directory for modes that create reports (`inventory`, `prepare-seed`, `validate-rest`)
- `--run`: existing run directory to read artifacts from; required by `apply-features`
- `--write`: required for any `data/knowledge.json` mutation
- `--force`: allow replacing existing backfilled `features` and `weak_labels`
- `--fetch-missing`: optional future behavior; when absent, local `raw_match_path` or `report_path` is required for prepare modes

Do not require both `--output` and `--run` in one command. The normal flow is:

```bash
python scripts/backfill_history.py \
  --kb data/knowledge.json \
  --manifest data/backfill/backfill_manifest.json \
  --mode prepare-seed \
  --output data/backfill/runs/20260519-seed

python scripts/backfill_history.py \
  --kb data/knowledge.json \
  --manifest data/backfill/backfill_manifest.json \
  --mode apply-features \
  --run data/backfill/runs/20260519-seed \
  --write
```

Supported modes:

### 8.1 `inventory`

Read KB and manifest. Do not write KB.

Output:

- total KB entries
- entries with features
- entries with weak labels
- legacy-only entries
- seed-set manifest count
- validation-set manifest count
- seed entries missing raw/report input
- legacy IDs in manifest not found in KB
- duplicate fixture IDs

### 8.2 `prepare-seed`

For seed-set entries only:

1. Load raw match JSON or analyze report JSON.
2. If only raw match JSON exists, call `src.tools.analyze.analyze_match(raw_match_json)` directly in Python.
3. If neither local raw nor local report exists, fail with `MISSING_RAW_INPUT` unless `--fetch-missing` is implemented and passed.
4. Run `prepare_evaluation` with JSON output.
5. Persist raw/report snapshots if available.
6. Write `prepare_results.jsonl`.
7. Write `llm_jobs.jsonl` with prompt and metadata.

Default behavior: dry-run. Do not mutate KB unless `--write` is passed.

Do not shell out to `python -m src analyze_match` from this script. Import the function:

```python
from src.tools.analyze import analyze_match
from src.tools.prepare_evaluation import prepare_evaluation
```

`prepare_results.jsonl` success row shape:

```json
{
  "legacy_match_id": "1",
  "fixture_id": "123456",
  "ok": true,
  "input_type": "raw_match",
  "features": {},
  "weak_labels": {},
  "rubric_version": "arteta_v1",
  "prompt": "...",
  "raw_match_path": "data/backfill/raw/123456.json",
  "report_path": "data/backfill/reports/123456.json"
}
```

`prepare_results.jsonl` error row shape:

```json
{
  "legacy_match_id": "1",
  "fixture_id": "123456",
  "ok": false,
  "error": {
    "code": "PREPARE_FAILED",
    "message": "prepare_evaluation returned EXTRACTION_FAILED"
  }
}
```

### 8.3 `apply-features`

For seed-set entries with successful prepare results:

1. Create `knowledge.before.json`.
2. Add `features`, `weak_labels`, version fields, and `backfill` metadata.
3. If old `evaluation` uses legacy dimension fields, copy the original object into `legacy_evaluation` first.
4. Normalize legacy `evaluation.dimension_signals` if needed.
5. Write `knowledge.after.json`.
6. Write `apply_report.json`.
7. Mutate `data/knowledge.json` only when `--write` is passed.

Legacy evaluation normalization is needed only when:

- `evaluation` contains any of `execution_signal`, `adjustment_signal`, or `satisfaction_signal`; and
- `evaluation.dimension_signals` is missing or empty.

Normalization mapping:

```python
dimension_signals = {
    "execution": evaluation.get("execution_signal"),
    "adjustment": evaluation.get("adjustment_signal"),
    "satisfaction": evaluation.get("satisfaction_signal"),
}
```

Then compute `evaluation.overall_signal` by the existing majority-vote rule:

- at least two `🟢` dimension signals → `🟢`
- at least two `🔴` dimension signals → `🔴`
- otherwise → `🟡`

If an entry already has `evaluation.dimension_signals`, leave it unchanged.

### 8.4 `validate-rest`

For validation-set entries:

1. Run the same prepare path.
2. Compare weak-label output with existing legacy evaluation signals.
3. Write `validation_report.json`.
4. Do not mutate KB in this phase.

This mode is for later self-iteration analysis. It should not rewrite the remaining 70+ entries yet.

## 9. LLM Job Output

Backfill should not call external LLM APIs.

Instead, `prepare-seed` writes:

```text
llm_jobs.jsonl
```

Each row:

```json
{
  "legacy_match_id": "1",
  "fixture_id": "123456",
  "opponent": "Chelsea",
  "date": "2025-05-01",
  "prompt": "...",
  "features": {},
  "weak_labels": {},
  "report_path": "data/backfill/reports/123456.json",
  "expected_output_schema": "strict_v2_evaluation"
}
```

This gives the agent/operator a clean queue for strict v2 evaluation generation.

Do not write fake strict v2 evaluations.

## 10. Selection Rules for 30-Match Seed Set

The implementation should not choose the seed set automatically unless a manifest is missing and `--auto-select-seed` is explicitly passed.

If auto-selection is implemented, use deterministic balanced sampling:

- include top6, mid_table, and lower opponents
- include home and away
- include wins, draws, and losses
- include league early, league late, and cup/knockout if present
- prefer entries with available fixture IDs or raw/report paths
- cap at `--limit`, default 30

The inventory report must show seed-set distribution:

```json
{
  "seed_distribution": {
    "opponent_quality": {},
    "venue": {},
    "result": {},
    "competition_stage": {}
  }
}
```

## 11. Safety Rules

- All mutating modes require `--write`.
- Before mutation, copy the current KB to `knowledge.before.json`.
- After mutation, write `knowledge.after.json`.
- Use atomic write behavior for `data/knowledge.json`.
- Preserve unknown fields.
- Preserve original legacy evaluation signals.
- Never delete entries.
- Never rewrite entries not named in the manifest seed set.
- Re-running the same apply should be idempotent.
- If a seed entry already has `features` and `weak_labels`, skip it unless `--force` is passed.

## 12. Error Handling

Every failed seed row should produce a structured error in `prepare_results.jsonl`:

```json
{
  "legacy_match_id": "1",
  "ok": false,
  "error": {
    "code": "MISSING_RAW_INPUT",
    "message": "No fixture_id, raw_match_path, or report_path provided"
  }
}
```

Required error codes:

- `LEGACY_ENTRY_NOT_FOUND`
- `MISSING_RAW_INPUT`
- `RAW_FILE_NOT_FOUND`
- `REPORT_FILE_NOT_FOUND`
- `FETCH_NOT_IMPLEMENTED`
- `FETCH_FAILED`
- `ANALYZE_FAILED`
- `PREPARE_FAILED`
- `FEATURES_EMPTY`
- `DUPLICATE_FIXTURE_ID`
- `WRITE_REQUIRES_FLAG`

## 13. Testing Requirements

Add focused tests. Do not rely on live APIs.

Required tests:

1. Inventory reports current KB counts correctly.
2. Inventory flags manifest IDs missing from KB.
3. Inventory flags seed rows without raw/report/fixture input.
4. `prepare-seed` can process a local raw match JSON fixture.
5. `prepare-seed` can process a local analyze report JSON fixture.
6. `prepare-seed` writes `llm_jobs.jsonl` with prompt, features, weak labels, and report path.
7. Dry-run modes do not mutate `knowledge.json`.
8. `apply-features --write` adds features, weak labels, versions, and backfill metadata.
9. `apply-features --write` preserves unknown legacy fields.
10. `apply-features --write` copies original `evaluation` into `legacy_evaluation` before normalizing.
11. `apply-features --write` normalizes legacy dimension signals.
12. Re-running `apply-features --write` is idempotent.
13. `validate-rest` writes a report and does not mutate KB.
14. `--force` allows replacing existing backfilled features.
15. Missing raw/report file creates structured row-level error.
16. Manifest row with only `fixture_id` fails with `MISSING_RAW_INPUT` unless `--fetch-missing` is implemented.
17. Full backfill E2E with 2 seed rows and 1 validation row.

Expected command:

```bash
uv run --with pytest --with pytest-mock --with pyyaml --with requests --with pandas pytest
```

All existing tests must remain green.

## 14. Documentation Requirements

Update:

- `README.md`
- `SKILL.md`

Docs must explain:

- legacy data cannot produce real features by itself
- seed-set backfill requires raw match JSON or analyze report JSON
- `prepare-seed` produces LLM jobs but does not call an LLM
- `apply-features` requires `--write`
- validation set is dry-run only in this phase

## 15. Done Definition

This phase is done when:

1. A manifest-driven backfill script exists.
2. Inventory mode runs without mutating KB.
3. Seed-set prepare mode produces feature/weak-label outputs and LLM jobs.
4. Feature apply mode can update selected seed entries with `--write`.
5. Raw/report snapshots are stored and referenced.
6. Existing legacy evaluation is preserved.
7. Validation-set mode produces comparison reports without writing KB.
8. Tests cover dry-run, write, idempotency, missing inputs, and E2E.
9. Full test suite passes.
10. No database migration is introduced.

## 16. Suggested Implementation Phases

### Phase 1: Manifest and Inventory

Add manifest parser and inventory mode.

Acceptance:

- Can report current legacy/v2 counts.
- Can validate seed/validation manifest rows.
- No writes.

### Phase 2: Prepare Seed Artifacts

Add local raw/report loading and `prepare_evaluation` integration.

Acceptance:

- Produces `prepare_results.jsonl`.
- Produces `llm_jobs.jsonl`.
- Stores or references raw/report snapshots.
- No KB mutation by default.

### Phase 3: Apply Feature Backfill

Add `apply-features` mode.

Acceptance:

- Mutates KB only with `--write`.
- Adds features, weak labels, versions, and backfill metadata.
- Preserves legacy evaluation and unknown fields.

### Phase 4: Validation Dry Run

Add `validate-rest` mode.

Acceptance:

- Produces weak-label vs legacy-signal comparison.
- Does not mutate KB.

### Phase 5: Documentation and E2E

Update docs and add full backfill E2E.

Acceptance:

- README/SKILL explain operator workflow.
- Full suite passes.

## 17. Post-Backfill Next Step

After the first 30 seed-set matches are feature-backed:

1. Generate strict v2 evaluations from `llm_jobs.jsonl`.
2. Save strict v2 evaluations through `save_evaluation`.
3. Human-review 5-8 seed matches.
4. Run validation dry-run over the remaining 70+ entries.
5. Use the validation report to design the later self-iteration phases.

Do not start automatic Arteta model evolution until the seed set has enough feature-backed and partially reviewed examples.
