# Calibration Rule Extraction & WK v1.1 Patch Spec

## Problem

Human review confirmed the first reusable WK blind spot:

> dominant stats + loss against lower/mid_table opposition must not become 🟢.

The current WK can still overrate this shape because execution/control and adjustment can both be 🟢, causing overall to stay 🟢 even when satisfaction is poor. The goal of this spec is to turn the first reviewed pattern into:

1. A deterministic WK v1.1 rule.
2. A replay comparison mode that can compare WK, LLM, and human override.
3. A CalibrationComputer blind-spot hint rendered into prompts.
4. A seed replay report that proves the patch fixes the known failure without broad regressions.

Clarification: `PatternComputer` and `CalibrationComputer` already consume `human_override` for historical distributions. The missing piece is not basic human_override consumption. The missing pieces are replay comparison against human review and explicit blind-spot extraction into future prompts.

## Non-Goals

- Do not rewrite the full weak-label scoring system.
- Do not add a learned model.
- Do not mutate the 70+ validation set in this spec.
- Do not make `validate-rest` write to KB. It remains dry-run/read-only.
- Do not overwrite stored seed weak labels until the replay diff is reviewed and approved.

## Decision

Implement a narrow **Result-Aware Satisfaction Guard + Overall Veto**.

This is intentionally smaller than a full result-quality matrix. It only handles losses, because the confirmed review failures are all about WK over-optimism when Arsenal loses despite strong control data.

## Rule Contract

### WK v1.1 Version

`WeakLabels.weak_label_version` must change from `v1` to `v1.1`.

Any output produced by the patched `WeakLabeler` must set:

```json
{
  "weak_label_version": "v1.1"
}
```

### Loss Guard

Apply this after existing model signals and dimension votes are computed.

```text
IF features.result == "L":
  IF features.opponent_quality in ("lower", "mid_table"):
    dimension_signals["satisfaction"] = 🔴
    overall_signal = 🔴
    add evidence/metadata that result-aware veto fired

  ELSE IF features.opponent_quality in ("top6", "european_elite"):
    IF dimension_signals["satisfaction"] == 🟢:
      dimension_signals["satisfaction"] = 🟡
    IF overall_signal == 🟢:
      overall_signal = 🟡
    do not upgrade 🔴 to 🟡

  ELSE:
    IF overall_signal == 🟢:
      overall_signal = 🟡
```

Important semantics:

- Strong/dominant stats can keep `execution=🟢`.
- Timely substitutions can keep `adjustment=🟢`.
- But loss to `lower` or `mid_table` opposition vetoes overall optimism.
- Loss to `top6` or `european_elite` may be 🟡, but the rule must never upgrade an already 🔴 signal.
- This is an overall veto, not only a satisfaction tweak. Without the overall veto, a loss can still be voted 🟢 by two green dimensions.

## Phase 1: WK v1.1 Patch

Modify `src/labels/weak_labeler.py`.

Expected shape:

```python
def _apply_result_aware_guards(self, features: MatchFeatures, wl: WeakLabels) -> None:
    ...
```

Call this helper after the existing dimension and overall votes, before confidence penalty returns.

The helper must be deterministic and must not inspect LLM evaluation or human_override.

Acceptance:

- `1531572` style features (`result=L`, `opponent_quality=lower`, dominant stats) produce:
  - `dimension_signals["satisfaction"] == 🔴`
  - `overall_signal == 🔴`
  - `weak_label_version == "v1.1"`
- `1379109` style features (`result=L`, `opponent_quality=mid_table`) produce:
  - `dimension_signals["satisfaction"] == 🔴`
  - `overall_signal == 🔴` if there are at least two red/vetoed dimensions, or at minimum not 🟢.
- `top6/european_elite` losses:
  - cannot produce `overall_signal == 🟢`
  - can remain 🔴 if other rules already made them 🔴
  - can be 🟡 if the match was competitive.
- Wins and draws are unaffected by this guard.

## Phase 2: Replay Human Comparison

Modify `scripts/replay_history.py`.

Add CLI flag:

```bash
--compare-human
```

When enabled, replay must include entries with `human_override` and output a comparison object per reviewed match.

Output shape:

```json
{
  "summary": {
    "total_entries": 111,
    "replayed": 30,
    "changed": 4,
    "human_reviewed": 3,
    "human_compared": 3
  },
  "changes": [],
  "human_comparisons": [
    {
      "match_id": "1531572",
      "wk": {
        "overall_signal": "🔴",
        "dimension_signals": {
          "execution": "🟢",
          "adjustment": "🟢",
          "satisfaction": "🔴"
        },
        "model_signals": {}
      },
      "llm": {
        "overall_signal": "🔴",
        "dimension_signals": {},
        "model_signals": {}
      },
      "human": {
        "overall_signal": "🔴",
        "dimension_signals": {},
        "model_signals": {}
      },
      "disagreements": [
        {
          "field": "dimension_signals.satisfaction",
          "wk": "🔴",
          "llm": "🔴",
          "human": "🔴"
        }
      ]
    }
  ],
  "skipped": []
}
```

Notes:

- `wk` means recomputed WK v1.1 from stored features.
- `llm` means stored `entry.evaluation`.
- `human` means `entry.human_override.corrected_*`.
- If a human_override is missing a subfield, use `null` for that subfield and keep the row.
- Replay remains read-only and must never mutate KB.

## Phase 3: Calibration Blind Spots

Modify `src/evaluation/calibration.py`.

Add:

```python
KNOWN_BLIND_SPOTS = [
    {
        "id": "dominant_stats_loss",
        "description": "WK can overrate matches where Arsenal dominates shots/xG/possession but loses.",
        "guardrail": "Do not let shot/xG/possession dominance override result satisfaction. A loss to lower/mid_table opposition cannot be overall green.",
        "source": "human_review",
        "weak_label_version": "v1.1",
    }
]
```

`CalibrationComputer.build_hints()` and `_empty_hints()` must include:

```json
{
  "known_blind_spots": [...]
}
```

## Phase 4: Prompt Rendering

Modify `src/evaluation/prompt_builder.py`.

Render `known_blind_spots` inside the calibration section after guardrails.

Chinese output should include a compact section like:

```text
已知WK盲区:
- dominant_stats_loss: WK can overrate matches where Arsenal dominates shots/xG/possession but loses.
  护栏: Do not let shot/xG/possession dominance override result satisfaction. A loss to lower/mid_table opposition cannot be overall green.
```

Acceptance:

- `prepare_evaluation` prompt includes `dominant_stats_loss`.
- Prompt includes the guardrail text.
- Existing calibration confidence/sample quality rendering remains unchanged.

## Phase 5: Seed Replay Dry Run

Run:

```bash
uv run --with pyyaml --with requests --with pandas \
  python scripts/replay_history.py \
  --kb data/knowledge.json \
  --mode weak-label-only \
  --compare-human \
  --output data/backfill/runs/seed-002/wk-v1.1-replay.json
```

This writes a replay artifact only. It must not update `data/knowledge.json`.

Acceptance:

- `1531572` recomputed WK is 🔴 overall.
- `1531572` satisfaction is 🔴.
- `1379109` satisfaction is 🔴 and overall is not 🟢.
- `1208154` remains eligible for LLM upgrade; WK must not be forced down by the loss guard because it is a win.
- `1314297` remains unaffected by xG missing fallback because it is not a loss.
- No win changes solely because of this guard.
- Replay output includes all 3 human-reviewed matches in `human_comparisons`.

## Test Requirements

Add or update tests before implementation.

Required tests:

1. `tests/test_weak_labeler.py`
   - loss to lower with dominant stats produces satisfaction 🔴 and overall 🔴.
   - loss to mid_table produces satisfaction 🔴 and overall not 🟢.
   - loss to top6 cannot be overall 🟢 but can remain 🔴 when model votes justify 🔴.
   - win with dominant stats is unchanged.
   - `weak_label_version == "v1.1"`.

2. `tests/test_replay_history.py`
   - `--compare-human` includes reviewed entries.
   - missing human subfields become `null`, not exceptions.
   - replay does not mutate KB.

3. `tests/evaluation/test_calibration.py`
   - `build_hints()` includes `known_blind_spots`.
   - `_empty_hints()` includes the same field.

4. `tests/test_prompt_builder.py` or `tests/e2e/test_json_pipeline.py`
   - calibration prompt renders `dominant_stats_loss`.
   - calibration prompt renders the result-satisfaction guardrail.

Verification command:

```bash
uv run --with pytest --with pytest-mock --with pyyaml --with requests --with pandas pytest
```

## Done Definition

This spec is done only when all are true:

- WK outputs `weak_label_version=v1.1`.
- Result-aware loss guard is implemented with overall veto.
- Replay supports `--compare-human`.
- Calibration hints expose `known_blind_spots`.
- Prompt renders known blind spots.
- Seed replay artifact is written.
- `1531572` is no longer WK 🟢.
- No win is changed by the loss guard.
- Full test suite passes.
- `data/knowledge.json` is not rewritten as part of this spec unless explicitly approved after reviewing the replay artifact.

## Future Work

After this spec lands and the replay artifact is reviewed, a separate spec can decide whether to:

1. Apply WK v1.1 weak labels to the 30 seed entries.
2. Expand raw/report backfill to the remaining 70+ validation matches.
3. Add more blind spots from future human review cycles.
