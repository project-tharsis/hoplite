"""Validate LLM evaluation output before KB writeback."""

VALID_SIGNALS = {"🟢", "🟡", "🔴"}
REQUIRED_MODEL_KEYS = {"1", "2", "3", "4", "5", "6"}
REQUIRED_DIMENSION_KEYS = {"execution", "adjustment", "satisfaction"}


def validate_llm_result(data: dict) -> dict:
    """Validate LLM evaluation output.

    Raises ValueError on schema violations.
    Returns normalized dict on success.
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

    return {
        "overall_signal": overall,
        "model_signals": dict(model_signals),
        "dimension_signals": dict(dim_signals),
        "narrative": narrative,
    }
