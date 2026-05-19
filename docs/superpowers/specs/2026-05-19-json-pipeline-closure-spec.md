# Hoplite Follow-Up Spec: JSON-Based Self-Iteration Pipeline Closure

Date: 2026-05-19
Status: Ready for implementation
Audience: DeepSeek implementation agent

## 1. Context

The original refactor spec is:

```text
docs/superpowers/specs/2026-05-18-arteta-self-iterating-skill-design.md
```

Current implementation already includes:

- `rubrics/arteta_v1.yaml`
- `src/features/extractor.py`
- `src/labels/weak_labeler.py`
- `src/evaluation/prompt_builder.py`
- strict v2 LLM result validation
- `save_evaluation` support for v2 fields and weak-label/version metadata

The team has decided to defer JSON-to-database migration because the current data volume is small enough for JSON.

This follow-up spec replaces the database portions of the original spec with a JSON-first implementation plan.

## 2. Product Goal

Make the new Arteta self-iteration architecture the default usable pipeline while keeping `data/knowledge.json` as the persistence layer.

The system should be able to:

1. Start from raw match JSON or existing report JSON.
2. Generate deterministic features.
3. Generate deterministic weak labels.
4. Build the new structured Arteta prompt.
5. Accept strict v2 LLM output.
6. Save evaluation, weak labels, features, and version metadata into JSON.
7. Replay historical JSON entries without LLM calls.
8. Generate calibration hints from JSON.
9. Allow sampled human review to override final labels.

## 3. Non-Goals

- Do not implement SQLite or Postgres in this phase.
- Do not migrate `data/knowledge.json` to a database.
- Do not add a frontend.
- Do not fine-tune a model.
- Do not remove legacy prompt compatibility yet.
- Do not break existing tests or CLI commands.

## 4. Current Gaps

### 4.1 New Modules Are Not the Default End-to-End Workflow

`FeatureExtractor`, `WeakLabeler`, and `PromptBuilder` exist, but the standard `python -m src build_narrative_prompt` path still uses the legacy prompt unless structured objects are passed in-process.

The CLI should expose a default new pipeline path.

### 4.2 JSON Save Does Not Persist Features

`save_evaluation` persists v2 evaluation fields, weak labels, and version tags, but does not persist the feature snapshot used to generate the evaluation.

Without stored features, future replay and audit cannot reconstruct why a label was generated.

### 4.3 Documentation Still Points at the Old Canonical Framework

`SKILL.md` and README still imply the Markdown framework is the main canonical rule source. The machine-readable canonical source is now `rubrics/arteta_v1.yaml`.

### 4.4 Replay and Calibration Are Not First-Class Modules

`PatternComputer` exists, but there is no explicit JSON replay script and no `calibration.py` layer that turns JSON history into guarded calibration hints.

### 4.5 Human Review Has No Write Path

`human_override` is read by pattern logic, but there is no first-class CLI/tool to write a sampled human review into `knowledge.json`.

## 5. Target JSON Entry Shape

Every saved v2 evaluation entry in `data/knowledge.json` should support this shape:

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

Backward compatibility:

- Existing legacy entries may lack `features` and `weak_labels`.
- Readers must tolerate missing fields.
- New v2 writes must include these fields.

## 6. Required Work

### Phase 1: Add Structured Prompt CLI

Add a new tool command:

```bash
python -m src build_structured_prompt < report.json
```

or, if preferred:

```bash
python -m src build_narrative_prompt_v2 < report.json
```

The command should:

1. Accept either `{ "report": {...} }` or raw report JSON.
2. Extract the original raw match data if present; otherwise use report fields as input where possible.
3. Run `FeatureExtractor`.
4. Run `WeakLabeler`.
5. Load `rubrics/arteta_v1.yaml`.
6. Build calibration hints unless `skip_history=true`.
7. Output the structured prompt.

Also provide a machine-readable mode:

```bash
python -m src prepare_evaluation < report.json
```

Output:

```json
{
  "features": {},
  "weak_labels": {},
  "rubric_version": "arteta_v1",
  "prompt": "..."
}
```

Acceptance:

- A caller can get features, weak labels, and prompt from one CLI command.
- The prompt output uses `PromptBuilder`, not the legacy monolithic prompt.
- Existing `build_narrative_prompt` legacy behavior remains available.

### Phase 2: Persist Feature Snapshots in JSON

Update `save_evaluation` to accept and persist:

- `features`
- `weak_labels`
- `versions`

Current `weak_labels` and version support exists; extend it to include `features`.

CLI input shape:

```json
{
  "report": {},
  "features": {},
  "weak_labels": {},
  "versions": {
    "features": "v1",
    "weak_label": "v1",
    "rubric": "arteta_v1",
    "prompt_builder": "v1"
  },
  "evaluation": {}
}
```

Acceptance:

- New JSON entries contain `features`.
- New JSON entries contain `features_version`, `weak_label_version`, `rubric_version`, and `prompt_builder_version`.
- Strict validation remains enabled for evaluation writes.
- Legacy entries remain readable.

### Phase 3: Add JSON Replay Script

Create:

```text
scripts/replay_history.py
```

First version should support weak-label replay only.

CLI:

```bash
python scripts/replay_history.py \
  --kb data/knowledge.json \
  --mode weak-label-only \
  --output /tmp/hoplite_replay_report.json
```

Behavior:

- Load JSON entries.
- Skip entries without enough raw/report data to recompute features.
- For entries with stored `features`, recompute weak labels from stored features.
- Compare stored `weak_labels` to recomputed weak labels.
- Write a replay report.

Replay report shape:

```json
{
  "summary": {
    "total_entries": 10,
    "replayed": 8,
    "skipped": 2,
    "changed": 1
  },
  "changes": [
    {
      "match_id": "123",
      "field": "weak_labels.overall_signal",
      "old": "🟢",
      "new": "🟡"
    }
  ],
  "skipped": [
    {
      "match_id": "legacy-1",
      "reason": "missing features"
    }
  ]
}
```

Acceptance:

- Replay runs without LLM calls.
- Replay is deterministic.
- Replay never mutates `knowledge.json` unless an explicit future `--write` flag is added.

### Phase 4: Add Calibration Hints Module

Create:

```text
src/evaluation/calibration.py
```

Responsibilities:

- Read `KnowledgeBase`.
- Produce guarded calibration hints from JSON history.
- Mark confidence based on sample size and data completeness.

API:

```python
class CalibrationComputer:
    def __init__(self, kb_path: str | None = None): ...
    def build_hints(self, context: dict, limit: int = 5) -> dict: ...
```

Output shape:

```json
{
  "count": 5,
  "confidence": "medium",
  "sample_quality": {
    "with_features": 3,
    "with_human_review": 1,
    "legacy_only": 2
  },
  "record": {
    "wins": 3,
    "draws": 1,
    "losses": 1,
    "avg_arsenal_score": 1.8,
    "avg_opponent_score": 1.0
  },
  "model_signal_distribution": {},
  "dimension_signal_distribution": {},
  "common_missing_data": ["xG", "pressing"],
  "guardrails": [
    "Historical hints are reference only.",
    "Current-match features take priority.",
    "Fewer than 5 similar matches means calibration confidence is low or medium."
  ]
}
```

Rules:

- `count < 3` → `confidence=low`
- `3 <= count < 5` → `confidence=medium`
- `count >= 5` and most entries have features → `confidence=high`
- If most entries are legacy-only, cap confidence at medium.

Update `src/tools/prompt.py` or `PromptBuilder` integration to prefer `CalibrationComputer` over directly using `PatternComputer` for new structured prompts.

Acceptance:

- Calibration hints include sample quality.
- Calibration hints never override current match data.
- Tests cover empty, low-confidence, and sufficient-sample cases.

### Phase 5: Add Human Review Tool

Create:

```text
src/tools/review.py
```

Add dispatcher entry:

```bash
python -m src review_evaluation
```

Input:

```json
{
  "match_id": "123",
  "reviewer": "shuo",
  "review_status": "corrected",
  "corrected_overall_signal": "🟡",
  "corrected_model_signals": {
    "1": "🟢",
    "2": "🟡",
    "3": "🟡",
    "4": "🟡",
    "5": "🟢",
    "6": "🟡"
  },
  "corrected_dimension_signals": {
    "execution": "🟡",
    "adjustment": "🟡",
    "satisfaction": "🟡"
  },
  "comments": "Win was useful but control was mixed."
}
```

Behavior:

- Locate matching entry by `match_id`.
- Set `human_override`.
- Preserve original weak labels and LLM evaluation.
- Add `reviewed_at`.

Acceptance:

- Human review can override labels.
- `PatternComputer` and `CalibrationComputer` prefer `human_override` where available.
- Original evaluation remains unchanged.

### Phase 6: Documentation Update

Update:

- `README.md`
- `SKILL.md`
- optionally `prompts/arteta_framework.md`

Required documentation changes:

1. State that `rubrics/arteta_v1.yaml` is the machine-readable canonical rubric.
2. State that `prompts/arteta_framework.md` is human-readable or legacy prompt reference.
3. Document the v2 JSON output schema.
4. Document the new CLI workflow:

```text
fetch_match_data
→ analyze_match
→ prepare_evaluation / build_structured_prompt
→ LLM evaluation
→ save_evaluation
→ optional review_evaluation
→ replay_history
```

5. Explain that persistence is currently JSON-based.
6. Explain that DB migration is intentionally deferred.

Acceptance:

- A new user following README does not accidentally use the legacy prompt path for v2 evaluation.
- SKILL instructions match the current code.

### Phase 7: End-to-End Tests

Add tests that cover the real JSON pipeline:

1. Raw/report input → features → weak labels → structured prompt.
2. Fake strict v2 LLM output → `save_evaluation`.
3. JSON entry contains `features`, `weak_labels`, `evaluation`, and version fields.
4. Legacy LLM output without v2 fields is rejected by `save_evaluation`.
5. Human review writes `human_override`.
6. Replay weak-label-only report runs and reports skipped legacy entries.
7. Calibration hints include sample quality and guardrails.
8. Substitute scorer regression:
   - substitution player appears in `extract_sub_impact` as `player`
   - same player scores later
   - `features.goals_by_substitutes > 0`
   - model 6 confidence is high

Minimum verification:

```bash
uv run --with pytest --with pytest-mock --with pyyaml --with requests --with pandas pytest
```

## 7. Implementation Order

Recommended DS execution order:

1. Add `prepare_evaluation` / structured prompt CLI.
2. Persist `features` in `save_evaluation`.
3. Add end-to-end JSON pipeline tests.
4. Add `CalibrationComputer`.
5. Add `review_evaluation`.
6. Add `scripts/replay_history.py`.
7. Update README and SKILL.
8. Run full test suite.

## 8. Important Constraints

- Keep JSON as the source of persistence for this phase.
- Do not add DB code.
- Do not remove legacy compatibility yet.
- Do not weaken strict validation in `save_evaluation`.
- Do not make historical calibration a hard override.
- Preserve original LLM evaluation when human review is added.
- Keep all new writes deterministic and testable.

## 9. Done Definition

This follow-up is complete when:

- The v2 structured pipeline can be run from CLI.
- New saved JSON entries include features, weak labels, v2 evaluation fields, and versions.
- Human review can be written into JSON.
- Replay can run against JSON without LLM calls.
- Calibration hints are generated by a dedicated module.
- README and SKILL describe the new JSON-based workflow.
- Full test suite passes.

