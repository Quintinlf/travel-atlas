"""Interest coverage — success as 'things I care about', not attraction count."""

from __future__ import annotations

from typing import Mapping, Sequence

from travel_atlas.services.types import Recommendation, UserProfileView

from .signals import INTEREST_TAG_ALIASES, _interest_tokens


# Map traveler interest tokens onto coverage buckets shown in the UI.
COVERAGE_BUCKETS: dict[str, frozenset[str]] = {
    "Food": frozenset({"market_food", "food", "cuisine", "restaurant", "dining"}),
    "Museums": frozenset({"museum_history", "museum", "gallery", "science", "astronomy"}),
    "Gardens": frozenset({"nature_gardens", "garden", "park", "nature"}),
    "Shrines": frozenset({"temple_spirituality", "temple", "shrine", "spiritual"}),
    "Astronomy": frozenset({"astronomy", "science", "observatory", "planetarium"}),
    "Architecture": frozenset({"architecture", "palace", "castle", "heritage", "historic"}),
    "Outdoors": frozenset({"nature_gardens", "hiking", "outdoor", "trail"}),
    "Shopping": frozenset({"shopping", "market", "retail"}),
}


def relevant_buckets(profile: UserProfileView) -> list[str]:
    tokens = _interest_tokens(profile)
    if not tokens:
        return list(COVERAGE_BUCKETS.keys())
    chosen: list[str] = []
    for name, aliases in COVERAGE_BUCKETS.items():
        if tokens & aliases or any(
            a in t or t in a for t in tokens for a in aliases
        ):
            chosen.append(name)
    return chosen or list(COVERAGE_BUCKETS.keys())[:5]


def compute_coverage(
    recommendations: Sequence[Recommendation],
    profile: UserProfileView,
    *,
    planned_titles: Sequence[str] = (),
) -> dict:
    """Return overall + per-interest coverage percentages (0–100)."""
    buckets = relevant_buckets(profile)
    planned = {t.lower() for t in planned_titles}
    covered_cats: set[str] = set()
    for rec in recommendations:
        if rec.score < 40 and "pin_id" not in rec.source_refs:
            continue
        covered_cats.add(rec.category)
        for tag, aliases in INTEREST_TAG_ALIASES.items():
            if rec.category == tag or rec.category in aliases:
                covered_cats.update(aliases)
                covered_cats.add(tag)

    # Pins count as covered for their category; titles in itinerary too.
    for rec in recommendations:
        if "pin_id" in rec.source_refs or rec.title.lower() in planned:
            covered_cats.add(rec.category)

    per_interest: dict[str, float] = {}
    for name in buckets:
        aliases = COVERAGE_BUCKETS[name]
        hit = bool(covered_cats & aliases) or any(
            r.category in aliases or any(a in r.title.lower() for a in aliases)
            for r in recommendations
            if "pin_id" in r.source_refs or r.score >= 50
        )
        # Graduated: count matching recs up to a soft target of 3.
        matches = [
            r
            for r in recommendations
            if r.category in aliases
            or any(a in (r.title or "").lower() for a in aliases)
        ]
        ratio = min(1.0, len(matches) / 3.0) if matches else (1.0 if hit else 0.0)
        per_interest[name] = round(100.0 * ratio, 1)

    overall = (
        round(sum(per_interest.values()) / len(per_interest), 1) if per_interest else 0.0
    )
    return {
        "overall": overall,
        "per_interest": per_interest,
        "philosophy": "Maximum personal joy per dollar — coverage of your interests, not attraction count.",
    }
