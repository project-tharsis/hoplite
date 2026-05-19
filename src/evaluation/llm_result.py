"""Validate LLM evaluation output before KB writeback."""

import sys

VALID_SIGNALS = {"🟢", "🟡", "🔴"}
REQUIRED_MODEL_KEYS = {"1", "2", "3", "4", "5", "6"}
REQUIRED_DIMENSION_KEYS = {"execution", "adjustment", "satisfaction"}

# New fields from spec Section 9 — optional for backward compat
OPTIONAL_FIELDS = {
    "evidence": {
        "description": "Per-model evidence dict (model_id → list of evidence strings)",
        "expected_type": dict,
        "expected_keys": REQUIRED_MODEL_KEYS,
    },
    "confidence": {
        "description": "Per-model confidence level",
        "expected_type": dict,
        "expected_keys": REQUIRED_MODEL_KEYS,
        "valid_values": {"high", "medium", "low"},
    },
    "missing_or_weak_evidence": {
        "description": "List of missing or weak data points",
        "expected_type": list,
    },
    "weak_label_disagreements": {
        "description": "List of disagreements with weak labels",
        "expected_type": list,
    },
}


def validate_llm_result(data: dict, strict: bool = False) -> dict:
    """Validate LLM evaluation output.

    Raises ValueError on schema violations.
    Returns normalized dict on success.

    Optional fields (evidence, confidence, missing_or_weak_evidence,
    weak_label_disagreements) are validated when present but not required.
    A warning is printed to stderr when they are missing.
    """
    errors: list[str] = []

    # overall_signal
    overall = data.get("overall_signal", "")
    if overall not in VALID_SIGNALS:
        errors.append(f"overall_signal must be one of {VALID_SIGNALS}, got '{overall}'")

    # model_signals
    model_signals = data.get("model_signals", {})
    if not isinstance(model_signals, dict):
        errors.append("model_signals must be a dict")
    else:
        missing = REQUIRED_MODEL_KEYS - set(model_signals.keys())
        if missing:
            errors.append(f"model_signals missing keys: {sorted(missing)}")
        for k, v in model_signals.items():
            if v not in VALID_SIGNALS:
                errors.append(f"model_signals['{k}'] = '{v}' is not a valid signal")

    # dimension_signals
    dim_signals = data.get("dimension_signals", {})
    if not isinstance(dim_signals, dict):
        errors.append("dimension_signals must be a dict")
    else:
        missing = REQUIRED_DIMENSION_KEYS - set(dim_signals.keys())
        if missing:
            errors.append(f"dimension_signals missing keys: {sorted(missing)}")
        for k, v in dim_signals.items():
            if v not in VALID_SIGNALS:
                errors.append(f"dimension_signals['{k}'] = '{v}' is not a valid signal")

    # narrative
    narrative = data.get("narrative", "")
    if not isinstance(narrative, str) or not narrative.strip():
        errors.append("narrative must be a non-empty string")

    if errors:
        raise ValueError("LLM result validation failed:\n- " + "\n- ".join(errors))

    result = {
        "overall_signal": overall,
        "model_signals": dict(model_signals),
        "dimension_signals": dict(dim_signals),
        "narrative": narrative,
    }

    # ── Optional v2 fields (spec Section 9) ──────────────────────────
    missing_optional = []

    # evidence
    if "evidence" in data:
        evidence = data["evidence"]
        if isinstance(evidence, dict):
            for model_key in REQUIRED_MODEL_KEYS:
                vals = evidence.get(model_key, [])
                if vals and not isinstance(vals, list):
                    print(
                        f"[WARN] evidence['{model_key}'] should be a list, got {type(vals).__name__}",
                        file=sys.stderr,
                    )
            result["evidence"] = dict(evidence)
        else:
            print(f"[WARN] evidence should be a dict, got {type(evidence).__name__}", file=sys.stderr)
    else:
        missing_optional.append("evidence")

    # confidence
    if "confidence" in data:
        conf = data["confidence"]
        if isinstance(conf, dict):
            for model_key in REQUIRED_MODEL_KEYS:
                val = conf.get(model_key)
                if val is not None and val not in {"high", "medium", "low"}:
                    print(
                        f"[WARN] confidence['{model_key}'] = '{val}' not in [high, medium, low]",
                        file=sys.stderr,
                    )
            result["confidence"] = dict(conf)
        else:
            print(f"[WARN] confidence should be a dict, got {type(conf).__name__}", file=sys.stderr)
    else:
        missing_optional.append("confidence")

    # missing_or_weak_evidence
    if "missing_or_weak_evidence" in data:
        mwe = data["missing_or_weak_evidence"]
        if isinstance(mwe, list):
            result["missing_or_weak_evidence"] = list(mwe)
        else:
            print(
                f"[WARN] missing_or_weak_evidence should be a list, got {type(mwe).__name__}",
                file=sys.stderr,
            )
    else:
        missing_optional.append("missing_or_weak_evidence")

    # weak_label_disagreements
    if "weak_label_disagreements" in data:
        wld = data["weak_label_disagreements"]
        if isinstance(wld, list):
            result["weak_label_disagreements"] = list(wld)
        else:
            print(
                f"[WARN] weak_label_disagreements should be a list, got {type(wld).__name__}",
                file=sys.stderr,
            )
    else:
        missing_optional.append("weak_label_disagreements")

    if missing_optional:
        if strict:
            raise ValueError(
                "Strict mode: missing required v2 fields: "
                + ", ".join(missing_optional)
            )
        print(
            f"[WARN] Optional v2 fields missing: {missing_optional}. "
            "Consider including evidence, confidence, missing_or_weak_evidence, "
            "and weak_label_disagreements for full spec compliance.",
            file=sys.stderr,
        )

    return result
