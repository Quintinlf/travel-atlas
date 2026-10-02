"""Weighted multi-signal scoring (deterministic, config-driven)."""

from __future__ import annotations

from typing import Mapping, Sequence


def score_signals(
    signals: Mapping[str, float],
    weights: Mapping[str, float],
) -> float:
    """Weighted sum with zero-variance-safe redistribution across present weights.

    Components with identical values across a *batch* are dropped by
    :func:`score_batch`. This function scores a single candidate using the
    (already filtered) weight map.
    """
    active = {k: float(w) for k, w in weights.items() if w > 0 and k in signals}
    if not active:
        return 0.0
    total_w = sum(active.values())
    if total_w <= 0:
        return 0.0
    raw = sum(signals[k] * (w / total_w) for k, w in active.items())
    return round(100.0 * max(0.0, min(1.0, raw)), 1)


def score_batch(
    signal_rows: Sequence[Mapping[str, float]],
    weights: Mapping[str, float],
) -> list[float]:
    """Score a batch; drop components that do not vary, redistribute weight."""
    if not signal_rows:
        return []
    keys = [k for k, w in weights.items() if w > 0]
    varying: list[str] = []
    for key in keys:
        values = [row.get(key, 0.0) for row in signal_rows]
        if max(values) - min(values) > 1e-9:
            varying.append(key)
    if not varying:
        # No discriminative signal — use full weight map as-is.
        active_weights = dict(weights)
    else:
        base = sum(float(weights[k]) for k in varying)
        active_weights = {
            k: float(weights[k]) / base * sum(float(weights[x]) for x in keys)
            for k in varying
        }
    return [score_signals(row, active_weights) for row in signal_rows]


def confidence_from_signals(signals: Mapping[str, float], score: float) -> float:
    """0–1 confidence from score magnitude and evidence strength."""
    evidence = (
        signals.get("interest_tag_overlap", 0.0)
        + signals.get("saved_pin_boost", 0.0)
        + signals.get("atlas_claim_relevance", 0.0)
        + signals.get("pin_affinity", 0.0)
    ) / 4.0
    return round(min(1.0, 0.5 * (score / 100.0) + 0.5 * evidence), 3)
