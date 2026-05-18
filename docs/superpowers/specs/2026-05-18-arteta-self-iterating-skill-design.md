# Hoplite Refactor Spec: Arteta Self-Iterating Tactical Skill

Date: 2026-05-18
Status: Draft for implementation review
Owner: Hoplite
Audience: DeepSeek implementation agent

## 1. Product Goal

Hoplite should become a self-iterating Arsenal tactical evaluation skill based on Mikel Arteta's football philosophy.

The system should evaluate every Arsenal match through Arteta's six mental models, persist the evaluation into a database, compare future matches against historical patterns, and improve its calibration over time.

The target product is not just a prompt that writes a post-match recap. It is a versioned evaluation system:

- Raw match data is normalized into stable features.
- Features generate weak labels from match outcomes and statistics.
- Arteta's philosophy is represented as a versioned rubric.
- The LLM explains and narrates, but does not invent missing facts.
- Every evaluation is stored with enough metadata to replay, audit, compare, and calibrate.
- Human review is used as a high-weight audit sample, not as the primary source of truth.

## 2. Truth Model

The primary truth source is automatic weak labeling from historical match data.

Weak labels are generated from:

- Result and score margin
- Opponent quality
- Venue
- Competition stage
- xG delta when available
- Shot and shot-on-target delta
- Possession and pass-security signals
- Goals conceded
- Set-piece balance
- Substitution timing and subsequent match events
- Historical baseline for similar contexts

Human review exists, but only as sampled calibration.

Human review can override a final label for a given match and should be stored separately from the automatic weak label and LLM evaluation. This preserves auditability and makes it possible to measure where the automatic system disagrees with human judgment.

## 3. Non-Goals

- Do not fine-tune a model in this phase.
- Do not build a frontend in this phase.
- Do not treat a win as automatic tactical success.
- Do not continue expanding a single monolithic prompt as the main architecture.
- Do not let historical pattern injection override current-match facts.
- Do not delete or mutate the existing JSON knowledge base without migration and backup.

## 4. Current System Problems

The current repository has a useful prototype architecture, but several parts are too tightly coupled for self-iteration.

### 4.1 Prompt Carries Too Much Responsibility

`src/tools/prompt.py` currently injects raw stats, key events, set-piece data, substitution data, historical patterns, the full Arteta framework, writing rules, and output schema into one prompt.

This makes the prompt easy to run but hard to test, calibrate, or version.

### 4.2 Framework Rules Are Too Rigid

`prompts/arteta_framework.md` contains useful model definitions, but some signal rules are hard thresholds.

Example: model 2 can lean too heavily on possession and shot count. A match can show 57% possession but still fail to control risk if Arsenal loses the shot and corner battle.

The rubric should support weighted evidence and confidence, not just threshold-based red/yellow/green classification.

### 4.3 Substitution Events Are Under-Extracted

API-Football events can use `subst` as the event type. `extract_sub_impact` only accepts `substitution`.

This causes matches with actual substitutions to produce `sub_impact=[]`, which then weakens or distorts model 6 and the in-game adjustment dimension.

### 4.4 JSON Knowledge Base Is Too Weak for Iteration

`data/knowledge.json` is good for a prototype, but self-iteration needs:

- Versioned rubrics
- Versioned features
- Multiple evaluations per match
- Human review records
- Replay runs
- Pattern snapshots
- Queryable evidence

SQLite is sufficient for the next stage.

### 4.5 Historical Patterns Are Prompt Hints, Not Calibration Assets

Historical patterns are currently injected directly into the LLM prompt.

This is useful context, but it can also bias the LLM into copying historical outcomes. Historical information should become structured calibration hints with guardrails.

## 5. Target Architecture

The target pipeline is:

```text
Raw match data
→ Event normalization
→ Feature extraction
→ Weak label generation
→ Historical calibration hints
→ LLM evaluation
→ Validation
→ Database write
→ Pattern snapshot
→ Rubric and skill calibration
```

## 6. Core Data Objects

### 6.1 MatchRaw

Stores raw match data before interpretation.

Fields:

- fixture_id
- date
- competition
- home_team
- away_team
- home_score
- away_score
- home_xg
- away_xg
- home_stats
- away_stats
- events
- lineups
- formations
- source_metadata

### 6.2 NormalizedEvent

Canonical event representation.

Fields:

- minute
- event_type: `goal | card | substitution | var | other`
- team_side: `arsenal | opponent`
- team_name
- player
- detail
- raw_type
- raw_detail
- source

Normalization rules:

- `subst`, `substitution`, and equivalent source values map to `substitution`.
- Goal and card variants map to canonical goal/card values.
- Unknown event types map to `other` while preserving raw values.

### 6.3 MatchFeatures

Stable features derived from MatchRaw and NormalizedEvent.

Fields:

- result: `W | D | L`
- score_margin
- opponent_quality
- venue
- competition_stage
- arsenal_goals
- opponent_goals
- possession_for
- possession_against
- possession_delta
- shots_for
- shots_against
- shot_delta
- shots_on_target_for
- shots_on_target_against
- shot_on_target_delta
- xg_for
- xg_against
- xg_delta
- pass_accuracy_for
- pass_accuracy_against
- pass_accuracy_delta
- corners_for
- corners_against
- corner_delta
- fouls_for
- fouls_against
- yellow_cards_for
- red_cards_for
- goals_conceded
- opponent_shots_on_target
- set_piece_goals_for
- set_piece_goals_against
- substitution_windows
- arsenal_sub_count
- goals_after_arsenal_subs
- score_state_timeline
- predicted_plan_match_features
- missing_data

`missing_data` is required. If xG, pressing, transition, or substitution impact data is unavailable, the system must say so explicitly.

### 6.4 WeakLabels

Automatic labels generated from MatchFeatures.

Fields:

- model_signals: model id to signal
- dimension_signals: dimension to signal
- overall_signal
- confidence: per model and per dimension
- evidence_refs: feature references used for each label
- missing_data_penalty
- weak_label_version

Weak labels are not final truth. They are the baseline truth signal for automatic iteration.

### 6.5 ArtetaRubricVersion

Versioned representation of Arteta's football philosophy.

Stored in `rubrics/arteta_v1.yaml`.

Each model includes:

- id
- name
- philosophy
- observable_features
- positive_indicators
- negative_indicators
- weak_label_rules
- confidence_rules
- data_limitations
- narrative_guidance

### 6.6 EvaluationResult

LLM output after reading features, weak labels, rubric, and calibration hints.

Fields:

- overall_signal
- model_signals
- dimension_signals
- evidence
- confidence
- missing_or_weak_evidence
- weak_label_disagreements
- narrative
- evaluator_version
- rubric_version
- feature_version

### 6.7 HumanReview

Optional sampled human audit.

Fields:

- match_id
- reviewer
- review_status: `accepted | corrected | rejected`
- corrected_model_signals
- corrected_dimension_signals
- corrected_overall_signal
- comments
- timestamp

Human review overrides the final label for that match but does not delete weak labels or LLM labels.

## 7. Database Design

Use SQLite for the first production refactor.

Create `src/storage/db.py` and `migrations/001_initial.sql`.

Required tables:

### matches

- id
- fixture_id
- date
- competition
- home_team
- away_team
- arsenal_score
- opponent_score
- result
- opponent
- opponent_quality
- venue
- competition_stage
- created_at

### match_events

- id
- match_id
- minute
- event_type
- team_side
- team_name
- player
- detail
- raw_type
- raw_detail
- source

### match_stats

- id
- match_id
- stat_key
- arsenal_value
- opponent_value
- source

### match_features

- id
- match_id
- feature_version
- features_json
- missing_data_json
- created_at

### weak_labels

- id
- match_id
- weak_label_version
- model_signals_json
- dimension_signals_json
- overall_signal
- confidence_json
- evidence_refs_json
- created_at

### rubric_versions

- id
- rubric_version
- file_path
- content_hash
- created_at

### evaluations

- id
- match_id
- evaluator_version
- rubric_version
- feature_version
- overall_signal
- model_signals_json
- dimension_signals_json
- evidence_json
- confidence_json
- missing_or_weak_evidence_json
- weak_label_disagreements_json
- narrative
- created_at

### human_reviews

- id
- match_id
- evaluation_id
- reviewer
- review_status
- corrected_overall_signal
- corrected_model_signals_json
- corrected_dimension_signals_json
- comments
- created_at

### pattern_snapshots

- id
- snapshot_version
- context_key
- filters_json
- summary_json
- created_at

## 8. Arteta Rubric Design

Move the canonical model logic from `prompts/arteta_framework.md` into a structured rubric file.

Path:

```text
rubrics/arteta_v1.yaml
```

The Markdown framework can remain as human-facing documentation, but Python should read the YAML rubric.

### 8.1 Model 1: Culture as OS

Judges discipline, standards, and emotional control.

Important features:

- yellow_cards_for
- red_cards_for
- fouls_for
- score_state_timeline
- card timing
- goals conceded near key intervals

Weak-label idea:

- Green when cards are controlled and no red card.
- Yellow when discipline cost exists but does not destabilize the match.
- Red when red cards or badly timed cards change match state.

### 8.2 Model 2: Where the Game Is Played

Judges territorial, rhythm, and risk control.

Important features:

- possession_delta
- shot_delta
- xg_delta
- pass_accuracy_delta
- corner_delta
- opponent_shots_on_target

Weak-label idea:

- Do not label green from possession alone.
- Green requires evidence that Arsenal controlled both ball and risk.
- Yellow covers mixed-control matches such as high possession but losing shot volume.
- Red covers matches where Arsenal is forced into defensive containment.

### 8.3 Model 3: Defence as Attacking Identity

Judges whether defending created a platform for attack.

Important features:

- goals_conceded
- opponent_shots_on_target
- xg_against
- score_state_timeline
- goals after defensive stability

Weak-label idea:

- Green for clean sheets or low-risk concessions.
- Yellow for 1-2 goals conceded when attack still functions.
- Red for defensive collapse or repeated high-quality chances conceded.

### 8.4 Model 4: Marginal Gains Expertized

Judges set pieces, penalties, and specialist edges.

Important features:

- set_piece_goals_for
- set_piece_goals_against
- corners_for
- corners_against
- penalty events

Weak-label idea:

- Green when set-piece edge is positive or specialists create measurable value.
- Yellow when set-piece data is neutral or incomplete.
- Red when set-piece concessions are decisive.

### 8.5 Model 5: Add Capability, Keep Identity

Judges whether Arsenal adds new capability without losing core identity.

Important features:

- pass_accuracy_for
- possession_for
- scorer diversity
- tactical feature availability
- xg quality if available

Weak-label idea:

- Green when traditional control and new attacking outputs coexist.
- Yellow when one side exists but the other is weak.
- Red when core control identity collapses.

### 8.6 Model 6: Role Clarity > Pressure

Judges substitution timing, role clarity, and tactical coherence after changes.

Important features:

- substitution_windows
- arsenal_sub_count
- goals_after_arsenal_subs
- score state at substitution
- goals conceded after substitution

Weak-label idea:

- Green when substitutions are timely and followed by stable or improved game state.
- Yellow when substitutions are reasonable but impact is unclear.
- Red when substitutions are late, incoherent, or followed by tactical loss of control.

## 9. Prompt Design

Create `src/evaluation/prompt_builder.py`.

The new prompt should not dump the full raw match JSON by default.

Inputs:

- MatchFeatures
- WeakLabels
- ArtetaRubricVersion
- HistoricalCalibrationHints

The LLM should receive:

- Concise match summary
- Feature table
- Missing data list
- Weak-label baseline
- Rubric excerpt
- Historical calibration hints
- Required JSON schema

The LLM must explain disagreements with weak labels.

Required output:

```json
{
  "overall_signal": "🟡",
  "model_signals": {
    "1": "🟢",
    "2": "🟡",
    "3": "🟡",
    "4": "🟡",
    "5": "🟡",
    "6": "🟡"
  },
  "dimension_signals": {
    "execution": "🟡",
    "adjustment": "🟡",
    "satisfaction": "🟡"
  },
  "evidence": {
    "2": ["57% possession", "12 shots for vs 15 against", "5 corners for vs 7 against"]
  },
  "confidence": {
    "2": "medium"
  },
  "missing_or_weak_evidence": ["xG missing", "pressing recoveries unavailable"],
  "weak_label_disagreements": [],
  "narrative": "Chinese post-match review..."
}
```

## 10. Historical Calibration

Historical data should produce calibration hints, not direct commands.

Create `src/evaluation/calibration.py`.

Calibration hints may include:

- Similar-context record
- Average goals for and against
- Common weak-label distribution
- LLM-vs-weak-label disagreement rate
- Human-review correction rate
- Common low-confidence models

Prompt rule:

Historical hints can shape confidence and comparison language, but current-match features take priority.

## 11. Self-Iteration Workflow

Each match evaluation follows:

1. Fetch or import raw match data.
2. Normalize events.
3. Extract features.
4. Generate weak labels.
5. Build historical calibration hints.
6. Run LLM evaluation.
7. Validate LLM output.
8. Save all artifacts to SQLite.
9. Optionally add human review.
10. Periodically replay history with the latest rubric version.
11. Compare versions and generate pattern snapshots.

## 12. Replay Workflow

Create `scripts/replay_history.py`.

Capabilities:

- Recompute features for historical matches.
- Regenerate weak labels with a selected weak-label version.
- Rebuild evaluation prompts.
- Optionally skip LLM calls and only compute weak-label baseline.
- Compare old and new rubric outputs.
- Write pattern snapshots.

CLI shape:

```bash
python scripts/replay_history.py \
  --db data/hoplite.sqlite \
  --rubric rubrics/arteta_v1.yaml \
  --mode weak-label-only
```

## 13. Migration Plan

Create `scripts/migrate_knowledge_json.py`.

Input:

```text
data/knowledge.json
```

Output:

```text
data/hoplite.sqlite
```

Rules:

- Preserve the original JSON file.
- Import available match metadata.
- Import legacy evaluations as `evaluations` with `evaluator_version=legacy-json`.
- If a legacy record lacks match metadata, import it with nullable fields and mark it as `incomplete`.
- Do not use incomplete records for high-confidence calibration unless explicitly requested.

## 14. Implementation Phases

### Phase 1: Stabilize Data and Events

Tasks:

- Add event normalization.
- Fix `subst` to `substitution`.
- Add tests for goal, card, substitution, unknown event types.
- Ensure substitution impact is non-empty when substitution events exist.

Acceptance:

- A match with `subst` events produces substitution windows.
- Raw event values are preserved for audit.

### Phase 2: Add Feature Extraction

Tasks:

- Create `src/features/extractor.py`.
- Add `MatchFeatures` dataclass or typed dictionary.
- Compute all required first-pass features.
- Track missing data.

Acceptance:

- Arsenal 3-2 Bournemouth does not become automatically all green.
- xG absence appears in `missing_data`.
- Feature extraction is deterministic.

### Phase 3: Add Weak Labeling

Tasks:

- Create `src/labels/weak_labeler.py`.
- Implement Arteta v1 weak-label rules.
- Return signals, confidence, and evidence refs.

Acceptance:

- Weak label output includes all six models and three dimensions.
- Mixed-control matches can produce yellow even when Arsenal wins.
- Weak labels are reproducible without LLM calls.

### Phase 4: Add SQLite Storage

Tasks:

- Create migration SQL.
- Create storage read/write helpers.
- Add JSON KB migration script.

Acceptance:

- New match evaluation writes raw match, features, weak labels, and evaluation.
- Legacy KB can be migrated without deleting the JSON file.

### Phase 5: Refactor Prompt and Validator

Tasks:

- Create `prompt_builder.py`.
- Extend `validate_llm_result`.
- Require evidence, confidence, missing evidence, and disagreement fields.

Acceptance:

- Invalid outputs fail validation.
- Valid outputs include traceable evidence per model or dimension.

### Phase 6: Replay and Calibration

Tasks:

- Create replay script.
- Create calibration hint generator.
- Create pattern snapshot writer.

Acceptance:

- Historical matches can be replayed under a chosen rubric version.
- Pattern hints do not override current-match features.

## 15. Testing Requirements

Add or update tests for:

- Event normalization
- Substitution impact extraction
- Feature extraction
- Missing data tracking
- Weak label generation
- SQLite migration
- SQLite write/read
- Prompt builder schema
- LLM result validation
- Replay weak-label-only mode
- Calibration hint generation

Minimum command:

```bash
python -m pytest
```

## 16. Example Acceptance Scenario

Input match:

Arsenal 3-2 Bournemouth, away, Premier League, mid-table opponent.

Key data:

- Arsenal possession 57%
- Arsenal shots 12, opponent shots 15
- Arsenal shots on target 5, opponent 3
- Arsenal corners 5, opponent 7
- xG missing
- Arsenal conceded at 10' and 76'
- Arsenal substitutions around 66-67'
- Arsenal scored at 71'

Expected behavior:

- Overall should not be forced green just because Arsenal won.
- Model 2 should likely be yellow because control evidence is mixed.
- Model 3 should likely be yellow because Arsenal conceded twice.
- Model 6 should use substitution timing and the 71' goal as evidence, but confidence should remain medium unless direct substitution involvement is known.
- Missing xG and missing pressing data must be stated.
- Final narrative should explain why the win was useful but not fully controlled.

## 17. DeepSeek Execution Instructions

Implement in small commits by phase.

Do not start by rewriting all prompt text.

Recommended order:

1. Event normalization and tests.
2. Feature extraction and tests.
3. Weak labeler and tests.
4. SQLite storage and migration.
5. Prompt builder and validator.
6. Replay and calibration.

Do not introduce fine-tuning, frontend, or external hosted databases.

Keep the existing CLI usable while adding the new pipeline.

Preserve backwards compatibility where practical:

- Existing `analyze_match` should still return a report.
- Existing `build_narrative_prompt` can become a compatibility wrapper.
- Existing `data/knowledge.json` should remain readable until migration is complete.

## 18. Open Decisions

These should be resolved during implementation planning:

- Exact weak-label thresholds for each model.
- Whether SQLite becomes mandatory or optional behind a config flag.
- How many historical matches are needed before calibration hints are considered high confidence.
- How human review is entered: CLI-only first, or direct database insert helper.

Default choices:

- Start with conservative weak-label thresholds.
- Make SQLite the default new storage.
- Require at least five similar matches before strong historical calibration.
- Implement human review as CLI-only in the first version.

