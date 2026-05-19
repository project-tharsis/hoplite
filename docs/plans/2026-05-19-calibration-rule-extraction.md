# Calibration Rule Extraction & WK v1.1 — Implementation Plan

> **For Hermes:** Use subagent-driven-development skill. Batch P1-P4 together (coupled through WK output → replay comparison → blind spots → prompt rendering). P5 is verification-only.

**Goal:** Turn first human review pattern (dominant stats + loss ≠ 🟢) into WK v1.1 rule, replay comparison, calibration blind spots, and prompt rendering — all verified against the 30-entry seed set.

**Architecture Decision:** Narrow Satisfaction Guard + Overall Veto (DDR at `docs/superpowers/specs/2026-05-19-calibration-rule-extraction-design.md`).

**Preconditions:**
- [x] Python 3.11+ with venv at ~/hoplite/.venv
- [x] 336 existing tests all pass
- [x] knowledge.json has 30 seed entries with features + weak_labels + 3 with human_override
- [x] Spec at commit 25344d9 is the authoritative reference

**Tech Stack:** Python 3.11, pytest, yaml, json

---

### Task 1: Add WK v1.1 test fixtures (TDD: write failing tests first)

**Objective:** Write 5 new tests for the result-aware loss guard — they must FAIL because `_apply_result_aware_guards` doesn't exist yet.

**Files:**
- Modify: `tests/test_weak_labeler.py` (append before last line)

**Step 1: Add test helper to build `lower_loss_features`**

```python
# Helper: build a MatchFeatures for loss-to-lower with dominant stats
def _lower_loss_dominant_features():
    """1531572-style: all stats dominant, but result=L, opponent=lower."""
    from src.features.extractor import MatchFeatures
    return MatchFeatures(
        result="L", opponent_quality="lower", venue="away",
        competition_stage="regular", opponent_name="Southampton",
        arsenal_goals=1, opponent_goals=2, score_margin=-1,
        goals_conceded=2, yellow_cards_for=1, red_cards_for=0,
        possession_for=64.0, possession_against=36.0, possession_delta=28.0,
        shots_for=23, shots_against=8, shot_delta=15,
        shots_on_target_for=7, shots_on_target_against=4, shot_on_target_delta=3,
        xg_for=2.10, xg_against=0.80, xg_delta=1.30,
        pass_accuracy_for=89.0, pass_accuracy_against=79.0, pass_accuracy_delta=10.0,
        corners_for=9, corners_against=4, corner_delta=5,
        fouls_for=11, fouls_against=9,
        substitution_windows=[{"minute": 60, "player": "Trossard", "scored_after": True}],
        arsenal_sub_count=5, goals_after_arsenal_subs=1, goals_by_substitutes=0,
        missing_data=["pressing", "pressing_recoveries", "transition"],
    )
```

**Step 2: Add the 5 tests**

```python
def test_loss_to_lower_with_dominant_stats_is_red():
    """1531572-style: WK must veto satisfaction and overall to 🔴."""
    from src.labels.weak_labeler import WeakLabeler
    f = _lower_loss_dominant_features()
    wl = WeakLabeler().label(f)
    assert wl.dimension_signals["satisfaction"] == "🔴", \
        f"Expected satisfaction=🔴, got {wl.dimension_signals['satisfaction']}"
    assert wl.overall_signal == "🔴", \
        f"Expected overall=🔴, got {wl.overall_signal}"
    assert wl.weak_label_version == "v1.1"


def test_loss_to_mid_table_cannot_be_green():
    """1379109-style: loss to mid_table→satisfaction=🔴, overall must not be 🟢."""
    from src.labels.weak_labeler import WeakLabeler
    from src.features.extractor import MatchFeatures
    f = MatchFeatures(
        result="L", opponent_quality="mid_table", venue="away",
        arsenal_goals=1, opponent_goals=2, score_margin=-1,
        goals_conceded=2, yellow_cards_for=2, red_cards_for=0,
        possession_for=53.0, possession_against=47.0, possession_delta=6.0,
        shots_for=15, shots_against=15, shot_delta=0,
        shots_on_target_for=9, shots_on_target_against=6, shot_on_target_delta=3,
        xg_for=1.92, xg_against=2.16, xg_delta=-0.24,
        pass_accuracy_for=85.0, pass_accuracy_against=82.0, pass_accuracy_delta=3.0,
        corners_for=3, corners_against=3, corner_delta=0,
        fouls_for=8, fouls_against=10,
        substitution_windows=[{"minute": 46, "player": "Sub", "scored_after": True}],
        arsenal_sub_count=5, goals_after_arsenal_subs=1,
        missing_data=[],
    )
    wl = WeakLabeler().label(f)
    assert wl.dimension_signals["satisfaction"] == "🔴"
    assert wl.overall_signal != "🟢", f"overall must not be 🟢, got {wl.overall_signal}"
    assert wl.weak_label_version == "v1.1"


def test_loss_to_top6_cannot_be_green():
    """Loss to top6 may be 🔴 or 🟡, but never 🟢."""
    from src.labels.weak_labeler import WeakLabeler
    from src.features.extractor import MatchFeatures
    f = MatchFeatures(
        result="L", opponent_quality="top6", venue="away",
        arsenal_goals=0, opponent_goals=1, score_margin=-1,
        goals_conceded=1, yellow_cards_for=2, red_cards_for=0,
        possession_for=47.0, possession_against=53.0, possession_delta=-6.0,
        shots_for=11, shots_against=9, shot_delta=2,
        shots_on_target_for=1, shots_on_target_against=3, shot_on_target_delta=-2,
        xg_for=0.49, xg_against=0.52, xg_delta=-0.03,
        pass_accuracy_for=82.0, pass_accuracy_against=85.0, pass_accuracy_delta=-3.0,
        corners_for=8, corners_against=3, corner_delta=5,
        fouls_for=10, fouls_against=7,
        substitution_windows=[{"minute": 5, "player": "Early", "scored_after": False}],
        arsenal_sub_count=4, goals_after_arsenal_subs=0,
        missing_data=[],
    )
    wl = WeakLabeler().label(f)
    assert wl.overall_signal != "🟢", f"overall must not be 🟢 for top6 loss, got {wl.overall_signal}"
    # satisfaction was 🟢 (M1=🔴 M3=🟢 M5=🔴 → vote=🔴 or guard caps at 🟡)
    assert wl.dimension_signals["satisfaction"] != "🟢", \
        f"top6 loss satisfaction must not be 🟢, got {wl.dimension_signals['satisfaction']}"


def test_win_with_dominant_stats_unchanged():
    """1208154-style: W must not be affected by loss guard."""
    from src.labels.weak_labeler import WeakLabeler
    from src.features.extractor import MatchFeatures
    f = MatchFeatures(
        result="W", opponent_quality="top6", venue="home",
        arsenal_goals=2, opponent_goals=0, score_margin=2,
        goals_conceded=0, yellow_cards_for=1, red_cards_for=0,
        possession_for=50.0, possession_against=50.0, possession_delta=0.0,
        shots_for=14, shots_against=5, shot_delta=9,
        shots_on_target_for=6, shots_on_target_against=2, shot_on_target_delta=4,
        xg_for=2.16, xg_against=0.22, xg_delta=1.94,
        pass_accuracy_for=87.0, pass_accuracy_against=87.0, pass_accuracy_delta=0.0,
        corners_for=13, corners_against=0, corner_delta=13,
        fouls_for=12, fouls_against=8,
        substitution_windows=[{"minute": 71, "player": "Sub", "scored_after": True}],
        arsenal_sub_count=3, goals_after_arsenal_subs=1,
        missing_data=[],
    )
    wl = WeakLabeler().label(f)
    # Win should produce normal signals. M1=🟢 (1 yellow), M2=🟢, M3=🟢 (CS), M4=🟢, M5=🟢, M6=🟡
    assert wl.dimension_signals["satisfaction"] != "🔴", \
        f"Win must not be vetoed red: satisfaction={wl.dimension_signals['satisfaction']}"
    assert wl.overall_signal != "🔴", \
        f"Win must not be vetoed red: overall={wl.overall_signal}"
    assert wl.weak_label_version == "v1.1"


def test_weak_label_version_is_v1_1():
    """Any label output must have version=v1.1."""
    from src.labels.weak_labeler import WeakLabeler
    from src.features.extractor import MatchFeatures
    f = MatchFeatures(result="D", opponent_quality="mid_table", venue="home",
        arsenal_goals=1, opponent_goals=1, score_margin=0,
        goals_conceded=1, yellow_cards_for=0, red_cards_for=0,
        possession_for=55.0, possession_against=45.0, possession_delta=10.0,
        shots_for=10, shots_against=10, shot_delta=0,
        shots_on_target_for=3, shots_on_target_against=3, shot_on_target_delta=0,
        xg_for=1.0, xg_against=1.0, xg_delta=0.0,
        pass_accuracy_for=80.0, pass_accuracy_against=80.0, pass_accuracy_delta=0.0,
        corners_for=5, corners_against=5, corner_delta=0,
        fouls_for=10, fouls_against=10,
        missing_data=[],
    )
    wl = WeakLabeler().label(f)
    assert wl.weak_label_version == "v1.1"
```

**Step 3: Run tests to verify failure**

Run: `pytest tests/test_weak_labeler.py -k "loss_to_lower" -v`
Expected: FAIL — `assert wl.dimension_signals["satisfaction"] == "🔴"` (satisfaction is not red yet)

**Step 4: Run all 5 new tests**

Run: `pytest tests/test_weak_labeler.py -k "v1_1 or loss_to or win_with" -v`
Expected: 5 FAIL (no `_apply_result_aware_guards` yet, no version bump)

---

### Task 2: Implement `_apply_result_aware_guards` in WeakLabeler

**Objective:** Add the guard method that enforces the loss-veto rules from the spec.

**Files:**
- Modify: `src/labels/weak_labeler.py` (add method + call it in `label()`)

**Step 1: Add the guard method (insert after line 107, before `return wl`)**

```python
    # ── Result-aware loss guards (v1.1) ─────────────────────────────

    def _apply_result_aware_guards(self, features: MatchFeatures, wl: WeakLabels) -> None:
        """Apply overall veto for losses based on opponent quality.

        Spec: loss to lower/mid_table → satisfaction=🔴 + overall=🔴.
              loss to top6/elite → satisfaction capped at 🟡, overall capped at 🟡.
              Must not upgrade an already 🔴 signal.
        """
        if features.result != "L":
            return

        quality = features.opponent_quality

        if quality in ("lower", "mid_table"):
            # Hard veto: satisfaction=🔴, overall=🔴
            wl.dimension_signals["satisfaction"] = RED
            wl.overall_signal = RED
            # Add evidence to Model 5 (identity) and Model 3 (defence) to explain veto
            wl.evidence_refs.setdefault("add_capability_keep_identity", []).append("result_aware_veto:loss_to_non_elite")
            wl.evidence_refs.setdefault("defence_as_attacking_identity", []).append("result_aware_veto:loss_to_non_elite")

        elif quality in ("top6", "european_elite"):
            # Soft cap: satisfaction never 🟢, overall never 🟢
            if wl.dimension_signals.get("satisfaction") == GREEN:
                wl.dimension_signals["satisfaction"] = YELLOW
            # Only downgrade overall if it was 🟢; don't touch 🔴
            if wl.overall_signal == GREEN:
                wl.overall_signal = YELLOW

        else:
            # Unknown quality: minimal guard — just prevent overall green
            if wl.overall_signal == GREEN:
                wl.overall_signal = YELLOW
```

**Step 2: Call it in `label()` after dimension+overall computation, before confidence penalty**

Replace line 101-103 (the gap between overall computation and confidence penalty):

```python
        # ── Apply result-aware loss guards (v1.1) ────────────────────
        self._apply_result_aware_guards(features, wl)

        # ── Apply missing data penalty to confidence ──────────────────
```

**Step 3: Bump `weak_label_version`**

In `label()`, find `wl.weak_label_version = "v1"` (line 45 of the class `WeakLabels`) and change to:

```python
    weak_label_version: str = "v1.1"
```

**Step 4: Run the 5 new tests**

Run: `pytest tests/test_weak_labeler.py -k "v1_1 or loss_to or win_with" -v`
Expected: 5 PASS

---

### Task 3: Verify no regression on existing WK tests

**Objective:** Ensure the existing 647-line test file still passes.

**Files:**
- Test: `tests/test_weak_labeler.py` (existing tests)

**Step 1: Run full weak_labeler test suite**

Run: `pytest tests/test_weak_labeler.py -v`
Expected: all existing tests still PASS (or explain any changes)

**Step 2: If any regression, fix inline**

The most likely regression: an existing test that expects `overall_signal == "🟢"` for a loss scenario. That's a bug in the old test — update the expected value to match the new v1.1 behavior.

---

### Task 4: Add replay `--compare-human` tests

**Objective:** Write tests for the new replay mode — FAIL because flag doesn't exist yet.

**Files:**
- Modify: `tests/test_replay_history.py` (append before last line)

**Step 1: Add test for `--compare-human` output**

```python
def test_replay_compare_human_includes_reviewed_entries(tmp_path):
    """replay with --compare-human must include human_comparisons."""
    import json
    from scripts.replay_history import replay_weak_label_only

    kb_path = tmp_path / "kb.json"
    entries = [
        {
            "match_id": "reviewed-1",
            "features": {
                "result": "L", "opponent_quality": "lower", "venue": "away",
                "competition_stage": "regular", "opponent_name": "Southampton",
                "arsenal_goals": 1, "opponent_goals": 2, "score_margin": -1,
                "goals_conceded": 2, "yellow_cards_for": 1, "red_cards_for": 0,
                "possession_for": 64.0, "possession_against": 36.0, "possession_delta": 28.0,
                "shots_for": 23, "shots_against": 8, "shot_delta": 15,
                "shots_on_target_for": 7, "shots_on_target_against": 4, "shot_on_target_delta": 3,
                "xg_for": 2.10, "xg_against": 0.80, "xg_delta": 1.30,
                "pass_accuracy_for": 89.0, "pass_accuracy_against": 79.0, "pass_accuracy_delta": 10.0,
                "corners_for": 9, "corners_against": 4, "corner_delta": 5,
                "fouls_for": 11, "fouls_against": 9,
                "substitution_windows": [], "arsenal_sub_count": 0,
                "goals_after_arsenal_subs": 0, "goals_by_substitutes": 0,
                "score_state_timeline": [], "set_piece_goals_for": 0, "set_piece_goals_against": 0,
                "predicted_plan_match_features": {}, "missing_data": [],
            },
            "weak_labels": {
                "overall_signal": "🟡", "model_signals": {}, "dimension_signals": {},
            },
            "evaluation": {
                "overall_signal": "🔴", "model_signals": {}, "dimension_signals": {},
            },
            "human_override": {
                "reviewer": "shuo", "review_status": "confirmed",
                "corrected_overall_signal": "🔴",
                "corrected_model_signals": {"1": "🟢", "5": "🔴"},
                "corrected_dimension_signals": {"satisfaction": "🔴"},
            },
        },
    ]
    with open(kb_path, "w") as f:
        json.dump(entries, f)

    # Run replay with compare-human
    from scripts.replay_history import replay_weak_label_only, replay_compare_human
    report = replay_compare_human(str(kb_path))

    assert "human_comparisons" in report
    assert len(report["human_comparisons"]) == 1
    comp = report["human_comparisons"][0]
    assert comp["match_id"] == "reviewed-1"
    assert comp["wk"]["overall_signal"] == "🔴"  # v1.1 guard
    assert comp["llm"]["overall_signal"] == "🔴"
    assert comp["human"]["overall_signal"] == "🔴"


def test_replay_compare_human_missing_subfields_becomes_null(tmp_path):
    """Missing human subfields → null, not exception."""
    import json
    kb_path = tmp_path / "kb.json"
    entries = [{
        "match_id": "partial",
        "features": {
            "result": "L", "opponent_quality": "lower", "venue": "away",
            "competition_stage": "regular", "opponent_name": "Unknown",
            "arsenal_goals": 1, "opponent_goals": 2, "score_margin": -1,
            "goals_conceded": 2, "yellow_cards_for": 0, "red_cards_for": 0,
            "possession_for": 60.0, "possession_against": 40.0, "possession_delta": 20.0,
            "shots_for": 20, "shots_against": 5, "shot_delta": 15,
            "shots_on_target_for": 5, "shots_on_target_against": 2, "shot_on_target_delta": 3,
            "xg_for": 2.0, "xg_against": 0.5, "xg_delta": 1.5,
            "pass_accuracy_for": 85.0, "pass_accuracy_against": 75.0, "pass_accuracy_delta": 10.0,
            "corners_for": 5, "corners_against": 2, "corner_delta": 3,
            "fouls_for": 10, "fouls_against": 10,
            "substitution_windows": [], "arsenal_sub_count": 0,
            "goals_after_arsenal_subs": 0, "goals_by_substitutes": 0,
            "score_state_timeline": [], "set_piece_goals_for": 0, "set_piece_goals_against": 0,
            "predicted_plan_match_features": {}, "missing_data": [],
        },
        "weak_labels": {"overall_signal": "🟡", "model_signals": {}, "dimension_signals": {}},
        "evaluation": {"overall_signal": "🔴", "model_signals": {}, "dimension_signals": {}},
        "human_override": {
            "reviewer": "shuo",
            # missing corrected_overall_signal, corrected_dimension_signals
        },
    }]
    with open(kb_path, "w") as f:
        json.dump(entries, f)

    from scripts.replay_history import replay_compare_human
    report = replay_compare_human(str(kb_path))
    comp = report["human_comparisons"][0]
    assert comp["human"]["overall_signal"] is None  # missing → null


def test_replay_does_not_mutate_kb(tmp_path):
    """Replay must never write to KB."""
    import json
    kb_path = tmp_path / "kb.json"
    entries = [{
        "match_id": "immutable",
        "features": {
            "result": "L", "opponent_quality": "lower", "venue": "away",
            "competition_stage": "regular", "opponent_name": "Test",
            "arsenal_goals": 0, "opponent_goals": 1, "score_margin": -1,
            "goals_conceded": 1, "yellow_cards_for": 0, "red_cards_for": 0,
            "possession_for": 55.0, "possession_against": 45.0, "possession_delta": 10.0,
            "shots_for": 10, "shots_against": 5, "shot_delta": 5,
            "shots_on_target_for": 3, "shots_on_target_against": 1, "shot_on_target_delta": 2,
            "xg_for": 1.0, "xg_against": 0.5, "xg_delta": 0.5,
            "pass_accuracy_for": 83.0, "pass_accuracy_against": 78.0, "pass_accuracy_delta": 5.0,
            "corners_for": 4, "corners_against": 3, "corner_delta": 1,
            "fouls_for": 10, "fouls_against": 10,
            "substitution_windows": [], "arsenal_sub_count": 0,
            "goals_after_arsenal_subs": 0, "goals_by_substitutes": 0,
            "score_state_timeline": [], "set_piece_goals_for": 0, "set_piece_goals_against": 0,
            "predicted_plan_match_features": {}, "missing_data": [],
        },
        "weak_labels": {"overall_signal": "🟡"},
        "human_override": {"reviewer": "shuo", "corrected_overall_signal": "🔴"},
    }]
    before = json.dumps(entries)
    with open(kb_path, "w") as f:
        json.dump(entries, f)

    from scripts.replay_history import replay_compare_human
    replay_compare_human(str(kb_path))

    with open(kb_path) as f:
        after = f.read()
    assert before == after, "KB was mutated by replay"
```

**Step 2: Run tests**

Run: `pytest tests/test_replay_history.py -k "compare_human or does_not_mutate" -v`
Expected: FAIL — `replay_compare_human` not defined

---

### Task 5: Implement `replay_compare_human` in replay_history.py + add CLI flag

**Objective:** Add the compare-human function and wire it through CLI.

**Files:**
- Modify: `scripts/replay_history.py`

**Step 1: Add `replay_compare_human` function (after `replay_weak_label_only`)**

```python
def replay_compare_human(kb_path: str) -> dict:
    """Replay WK v1.1, compare against LLM eval and human_override.

    Read-only. Returns the same shape as replay_weak_label_only
    plus ``human_comparisons`` list.
    """
    with open(kb_path, encoding="utf-8") as f:
        entries = json.load(f)

    labeler = WeakLabeler()
    all_changes: list[dict] = []
    changed_count = 0
    replayed = 0
    skipped: list[dict] = []
    human_comparisons: list[dict] = []

    for entry in entries:
        match_id = str(entry.get("match_id", "unknown"))
        stored_features = entry.get("features")

        if not stored_features:
            skipped.append({"match_id": match_id, "reason": "missing features"})
            continue

        try:
            mf = features_from_dict(stored_features)
        except Exception as e:
            skipped.append({"match_id": match_id, "reason": f"features parse error: {e}"})
            continue

        # Recompute WK
        recomputed = labeler.label(mf)
        recomputed_dict = {
            "model_signals": recomputed.model_signals,
            "dimension_signals": recomputed.dimension_signals,
            "overall_signal": recomputed.overall_signal,
        }

        # Compare with stored WK
        stored_wl = entry.get("weak_labels", {})
        changes = _compare_weak_labels(stored_wl, recomputed_dict)
        for change in changes:
            change["match_id"] = match_id
            all_changes.append(change)
        if changes:
            changed_count += 1
        replayed += 1

        # Human comparison
        ho = entry.get("human_override")
        if ho:
            eval_ = entry.get("evaluation", {})
            try:
                disagreements = _compute_human_disagreements(recomputed_dict, eval_, ho)
            except Exception:
                disagreements = []
            human_comparisons.append({
                "match_id": match_id,
                "wk": {
                    "overall_signal": recomputed.overall_signal,
                    "dimension_signals": recomputed.dimension_signals,
                    "model_signals": recomputed.model_signals,
                },
                "llm": {
                    "overall_signal": eval_.get("overall_signal"),
                    "dimension_signals": eval_.get("dimension_signals", {}),
                    "model_signals": eval_.get("model_signals", {}),
                },
                "human": {
                    "overall_signal": ho.get("corrected_overall_signal"),
                    "dimension_signals": ho.get("corrected_dimension_signals", {}),
                    "model_signals": ho.get("corrected_model_signals", {}),
                },
                "disagreements": disagreements,
            })

    return {
        "summary": {
            "total_entries": len(entries),
            "replayed": replayed,
            "skipped": len(skipped),
            "changed": changed_count,
            "human_reviewed": sum(1 for e in entries if e.get("human_override")),
            "human_compared": len(human_comparisons),
        },
        "changes": all_changes,
        "human_comparisons": human_comparisons,
        "skipped": skipped,
    }


def _compute_human_disagreements(
    wk: dict, llm: dict, human: dict
) -> list[dict]:
    """Compare WK, LLM, and human signals. Return list of disagreements."""
    disagreements: list[dict] = []

    # overall_signal
    h_overall = human.get("corrected_overall_signal")
    if h_overall:
        wk_os = wk.get("overall_signal")
        llm_os = llm.get("overall_signal")
        if wk_os != h_overall or llm_os != h_overall:
            disagreements.append({
                "field": "overall_signal",
                "wk": wk_os,
                "llm": llm_os,
                "human": h_overall,
            })

    # dimension_signals
    h_dims = human.get("corrected_dimension_signals", {})
    for dim_key in sorted(set(list(wk.get("dimension_signals", {}).keys()) + list(llm.get("dimension_signals", {}).keys()) + list(h_dims.keys()))):
        wk_v = wk.get("dimension_signals", {}).get(dim_key)
        llm_v = llm.get("dimension_signals", {}).get(dim_key)
        h_v = h_dims.get(dim_key)
        if h_v is not None and (wk_v != h_v or llm_v != h_v):
            disagreements.append({
                "field": f"dimension_signals.{dim_key}",
                "wk": wk_v,
                "llm": llm_v,
                "human": h_v,
            })

    # model_signals
    h_models = human.get("corrected_model_signals", {})
    for m_key in sorted(set(list(wk.get("model_signals", {}).keys()) + list(llm.get("model_signals", {}).keys()) + list(h_models.keys()))):
        wk_v = wk.get("model_signals", {}).get(m_key)
        llm_v = llm.get("model_signals", {}).get(m_key)
        h_v = h_models.get(m_key)
        if h_v is not None and (wk_v != h_v or llm_v != h_v):
            disagreements.append({
                "field": f"model_signals.{m_key}",
                "wk": wk_v,
                "llm": llm_v,
                "human": h_v,
            })

    return disagreements
```

**Step 2: Wire `--compare-human` to CLI**

In `main()`, add:

```python
    parser.add_argument("--compare-human", action="store_true",
                        help="Include human override comparison in output")
```

And in the mode dispatch (after line 155):

```python
    if args.mode == "weak-label-only":
        if args.compare_human:
            report = replay_compare_human(kb_path)
        else:
            report = replay_weak_label_only(kb_path)
```

**Step 3: Run the 3 replay tests**

Run: `pytest tests/test_replay_history.py -k "compare_human or does_not_mutate" -v`
Expected: 3 PASS

**Step 4: Run full replay test suite**

Run: `pytest tests/test_replay_history.py -v`
Expected: all PASS

---

### Task 6: Add calibration blind spots tests

**Objective:** Write tests for `KNOWN_BLIND_SPOTS` in calibration — FAIL because field doesn't exist yet.

**Files:**
- Modify: `tests/evaluation/test_calibration.py` (append before last line)

**Step 1: Add tests**

```python
def test_build_hints_includes_known_blind_spots(tmp_path):
    """build_hints() must include known_blind_spots field."""
    import json
    from src.evaluation.calibration import CalibrationComputer

    kb_path = tmp_path / "kb.json"
    entries = [{
        "match_id": "1",
        "features": {"result": "L", "opponent_quality": "lower", "missing_data": []},
        "pre_match_context": {"opponent_quality": "lower", "venue": "away", "competition_stage": "regular"},
        "evaluation": {"model_signals": {}, "dimension_signals": {}, "overall_signal": "🔴"},
    }]
    with open(kb_path, "w") as f:
        json.dump(entries, f)

    cc = CalibrationComputer(str(kb_path))
    hints = cc.build_hints({"opponent_quality": "lower", "venue": "away"})
    assert "known_blind_spots" in hints
    spots = hints["known_blind_spots"]
    assert len(spots) >= 1
    assert spots[0]["id"] == "dominant_stats_loss"


def test_empty_hints_includes_known_blind_spots():
    """_empty_hints() must include known_blind_spots (empty list)."""
    from src.evaluation.calibration import CalibrationComputer
    empty = CalibrationComputer._empty_hints()
    assert "known_blind_spots" in empty
    spots = empty["known_blind_spots"]
    assert len(spots) >= 1
    assert spots[0]["id"] == "dominant_stats_loss"
```

**Step 2: Run tests**

Run: `pytest tests/evaluation/test_calibration.py -k "blind" -v`
Expected: FAIL — `known_blind_spots` not in hints

---

### Task 7: Implement KNOWN_BLIND_SPOTS in CalibrationComputer

**Objective:** Add the blind spots constant and include it in output.

**Files:**
- Modify: `src/evaluation/calibration.py`

**Step 1: Add constant (after `GUARDRAILS`)**

```python
    KNOWN_BLIND_SPOTS: list[dict] = [
        {
            "id": "dominant_stats_loss",
            "description": "WK can overrate matches where Arsenal dominates shots/xG/possession but loses.",
            "guardrail": "Do not let shot/xG/possession dominance override result satisfaction. A loss to lower/mid_table opposition cannot be overall green.",
            "source": "human_review",
            "weak_label_version": "v1.1",
        }
    ]
```

**Step 2: Include in `build_hints()` return dict (after line 111 `"guardrails": ...`)**

Add:

```python
            "known_blind_spots": list(self.KNOWN_BLIND_SPOTS),
```

**Step 3: Include in `_empty_hints()` return dict**

Change line 160 `"guardrails": list(CalibrationComputer.GUARDRAILS),` to:

```python
            "guardrails": list(CalibrationComputer.GUARDRAILS),
            "known_blind_spots": list(CalibrationComputer.KNOWN_BLIND_SPOTS),
```

**Step 4: Run calibration tests**

Run: `pytest tests/evaluation/test_calibration.py -v`
Expected: all PASS (including the 2 new blind-spot tests)

---

### Task 8: Add prompt rendering test for known_blind_spots

**Objective:** Test that prompt builder renders blind spots.

**Files:**
- Modify: `tests/test_prompt_builder.py` (append before last line)

**Step 1: Add test**

```python
def test_calibration_hints_render_known_blind_spots():
    """Prompt must include known_blind_spots when present."""
    from src.features.extractor import MatchFeatures
    from src.labels.weak_labeler import WeakLabels
    from src.evaluation.prompt_builder import PromptBuilder

    features = MatchFeatures(
        result="L", opponent_quality="lower", venue="away",
        competition_stage="regular", opponent_name="Southampton",
        arsenal_goals=1, opponent_goals=2, score_margin=-1,
        goals_conceded=2, yellow_cards_for=0, red_cards_for=0,
        possession_for=64.0, possession_against=36.0, possession_delta=28.0,
        shots_for=23, shots_against=8, shot_delta=15,
        shots_on_target_for=7, shots_on_target_against=4, shot_on_target_delta=3,
        xg_for=2.10, xg_against=0.80, xg_delta=1.30,
        pass_accuracy_for=89.0, pass_accuracy_against=79.0, pass_accuracy_delta=10.0,
        corners_for=9, corners_against=4, corner_delta=5,
        fouls_for=11, fouls_against=9,
        missing_data=[],
    )
    wl = WeakLabels()
    wl.overall_signal = "🔴"
    wl.model_signals = {}
    wl.dimension_signals = {"execution": "🟢", "adjustment": "🟢", "satisfaction": "🔴"}

    from rubrics.arteta_v1 import load_rubric
    rubric = load_rubric()
    builder = PromptBuilder(rubric, language="zh")
    hints = {
        "count": 5,
        "confidence": "medium",
        "sample_quality": {"with_features": 2, "with_human_review": 1, "legacy_only": 3},
        "record": {"wins": 2, "draws": 1, "losses": 2, "avg_arsenal_score": 1.8, "avg_opponent_score": 1.2},
        "model_signal_distribution": {},
        "common_missing_data": ["pressing"],
        "guardrails": ["Historical hints are reference only."],
        "known_blind_spots": [
            {
                "id": "dominant_stats_loss",
                "description": "WK can overrate losses with dominant stats.",
                "guardrail": "A loss to lower/mid_table cannot be green.",
            }
        ],
    }
    prompt = builder.build(features, wl, calibration_hints=hints)
    assert "dominant_stats_loss" in prompt
    assert "WK can overrate" in prompt or "A loss to lower" in prompt
```

**Step 2: Run test**

Run: `pytest tests/test_prompt_builder.py::test_calibration_hints_render_known_blind_spots -v`
Expected: FAIL — prompt doesn't render blind spots yet

---

### Task 9: Implement known_blind_spots rendering in prompt_builder

**Objective:** Render blind spots in the calibration section.

**Files:**
- Modify: `src/evaluation/prompt_builder.py` (in `_build_calibration_hints`)

**Step 1: Add blind spots rendering after guardrails block (after line 526, before the "注意" note)**

```python
        # Known blind spots (v1.1)
        blind_spots = hints.get("known_blind_spots", [])
        if blind_spots:
            lines.append("")
            if self.language == "zh":
                lines.append("已知WK盲区:")
            else:
                lines.append("Known WK blind spots:")
            for bs in blind_spots:
                bs_id = bs.get("id", "?")
                bs_desc = bs.get("description", "")
                bs_guard = bs.get("guardrail", "")
                lines.append(f"- {bs_id}: {bs_desc}")
                if bs_guard:
                    if self.language == "zh":
                        lines.append(f"  护栏: {bs_guard}")
                    else:
                        lines.append(f"  Guardrail: {bs_guard}")
```

**Step 2: Run the prompt builder test**

Run: `pytest tests/test_prompt_builder.py::test_calibration_hints_render_known_blind_spots -v`
Expected: PASS

**Step 3: Run full prompt builder test suite**

Run: `pytest tests/test_prompt_builder.py -v`
Expected: all PASS

---

### Task 10: Run full test suite

**Objective:** Verify no regressions across all 336+ existing tests.

**Step 1: Run full suite**

Run: `pytest tests/ -x -q`
Expected: all tests PASS (336+ original + ~10 new)

**Step 2: If any regression, fix inline**

Check for tests that expect old `overall_signal` values for loss scenarios.

---

### Task 11: Phase 5 — Seed Replay Dry Run

**Objective:** Generate the wk-v1.1-replay.json artifact. Do NOT mutate KB.

**Step 1: Run replay with compare-human**

```bash
source .venv/bin/activate && python scripts/replay_history.py \
  --kb data/knowledge.json \
  --mode weak-label-only \
  --compare-human \
  --output data/backfill/runs/seed-002/wk-v1.1-replay.json
```

**Step 2: Verify acceptance criteria**

Run verification script:

```python
import json
with open("data/backfill/runs/seed-002/wk-v1.1-replay.json") as f:
    report = json.load(f)

# 1. 1531572 WK must be 🔴 overall
comp_1531572 = next(c for c in report["human_comparisons"] if c["match_id"] == "1531572")
assert comp_1531572["wk"]["overall_signal"] == "🔴", f"1531572 WK overall should be 🔴, got {comp_1531572['wk']['overall_signal']}"
assert comp_1531572["wk"]["dimension_signals"]["satisfaction"] == "🔴"

# 2. 1379109 satisfaction = 🔴, overall ≠ 🟢
comp_1379109 = next(c for c in report["human_comparisons"] if c["match_id"] == "1379109")
assert comp_1379109["wk"]["dimension_signals"]["satisfaction"] == "🔴"
assert comp_1379109["wk"]["overall_signal"] != "🟢"

# 3. 1208154 (win) must not be forced red
comp_1208154 = next(c for c in report["human_comparisons"] if c["match_id"] == "1208154")
assert comp_1208154["wk"]["overall_signal"] != "🔴"

# 4. Human comparisons include all 3 reviewed entries
assert len(report["human_comparisons"]) == 3

# 5. No win changes
changes = report.get("changes", [])
win_changes = [ch for ch in changes if ch.get("field") == "weak_labels.overall_signal"]
for ch in win_changes:
    # any overall change should NOT be a win being downgraded
    print(f"  Change: {ch['match_id']} {ch['old']} → {ch['new']}")

print("All acceptance checks passed.")
print(f"Replayed: {report['summary']['replayed']}, Changed: {report['summary']['changed']}")
print(f"Human compared: {report['summary']['human_compared']}")
```

**Step 3: Commit the replay artifact**

```bash
git add data/backfill/runs/seed-002/wk-v1.1-replay.json
git commit -m "chore: WK v1.1 seed replay artifact (dry-run, KB not mutated)"
```

---

### Task 12: Final commit + push (main model)

After all tasks pass and artifact is generated:

```bash
git add -A
git commit -m "feat: WK v1.1 loss guard + replay compare-human + calibration blind spots

P1: result-aware loss veto (satisfaction guard + overall veto)
P2: replay --compare-human mode (WK/LLM/human three-way comparison)
P3: CalibrationComputer KNOWN_BLIND_SPOTS
P4: prompt builder renders blind spots to calibration section
P5: seed replay artifact at data/backfill/runs/seed-002/wk-v1.1-replay.json

Acceptance: 1531572 WK=🔴, 1379109 WK≠🟢, 1208154 unchanged, 3 human comparisons, no win regressions
Full test suite passes."
git push
```

---

### Task 13: Retire existing `prepare_results.jsonl` and `llm_jobs.jsonl` after `apply-features` writes (P4 only if seed WK was reviewed and approved)

**Do NOT do this now.** This task is a reminder for after the replay artifact is reviewed and the user approves applying WK v1.1 labels to the 30 seed entries.

```bash
python scripts/backfill_history.py \
  --kb data/knowledge.json \
  --manifest data/backfill/backfill_manifest.json \
  --mode apply-features \
  --run data/backfill/runs/seed-002 \
  --force --write
```

---

## Execution Strategy

**Batch P1-P4 together** (Tasks 1-10) — these are tightly coupled:
- P1 WK guard produces v1.1 outputs
- P2 replay comparison reads v1.1 outputs
- P3 calibration blind spots reference v1.1
- P4 prompt renders blind spots

Delegate to MIMO subagent with full context. Then QA gate: run full pytest, verify acceptance criteria.

**P5 (Task 11)** — main model runs the dry-run artifact generation and verification script.

**Task 12** — main model commits and pushes.
