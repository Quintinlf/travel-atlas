"""Learn category weight multipliers from recommendation ratings."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from travel_atlas.repository import AtlasRepository

RATING_SCORES: dict[str, float] = {
    "loved": 1.0,
    "liked": 0.5,
    "neutral": 0.0,
    "disliked": -0.5,
    "skip": -1.0,
}

# Soft bounds so one trip cannot dominate forever.
MULTIPLIER_MIN = 0.55
MULTIPLIER_MAX = 1.75
LEARNING_RATE = 0.08


def apply_rating_to_weights(
    repository: AtlasRepository,
    user_key: str,
    category: str,
    rating_score: float,
) -> float:
    """Nudge category multiplier toward joy for highly rated categories."""
    current = repository.get_planning_weight_multipliers(user_key)
    old = float(current.get(category, 1.0))
    # Positive ratings raise weight; negative lower it.
    updated = old + LEARNING_RATE * rating_score
    updated = max(MULTIPLIER_MIN, min(MULTIPLIER_MAX, updated))
    sample = 0
    with repository.database.connect() as conn:
        row = conn.execute(
            """
            SELECT sample_count FROM planning_weight_state
            WHERE user_key = ? AND category = ?
            """,
            (user_key, category),
        ).fetchone()
        if row:
            sample = int(row["sample_count"])
    repository.upsert_planning_weight(user_key, category, updated, sample + 1)
    return updated


def merge_learned_weights(
    base_weights: dict[str, float],
    category_multipliers: dict[str, float],
    category: str,
) -> dict[str, float]:
    """Scale interest/saved-pin signals by learned category affinity."""
    mult = float(category_multipliers.get(category, 1.0))
    if abs(mult - 1.0) < 1e-6:
        return dict(base_weights)
    out = dict(base_weights)
    for key in ("interest_tag_overlap", "saved_pin_boost", "pin_affinity", "theme_fit"):
        if key in out:
            out[key] = out[key] * mult
    # Renormalize to preserve relative total mass of positive weights.
    total = sum(v for v in out.values() if v > 0)
    base_total = sum(v for v in base_weights.values() if v > 0)
    if total > 0 and base_total > 0:
        scale = base_total / total
        out = {k: v * scale for k, v in out.items()}
    return out
