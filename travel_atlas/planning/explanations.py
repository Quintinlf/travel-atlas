"""Template + structured explanations for transparent recommendations."""

from __future__ import annotations

from typing import Mapping, Sequence

from travel_atlas.services.types import MatchFactor

_SIGNAL_LABELS: dict[str, str] = {
    "interest_tag_overlap": "Saved interest match",
    "pin_affinity": "Attention in notes / priority",
    "atlas_claim_relevance": "Atlas knowledge alignment",
    "saved_pin_boost": "Already in your saved pins",
    "pace_fit": "Fits trip pace",
    "budget_fit": "Fits budget posture",
    "hidden_gem": "Personal fit, less crowded",
    "transport_fit": "Transportation fit",
    "theme_fit": "Fits today's theme",
    "energy_fit": "Sustainable energy level",
    "rating_history": "Your past ratings",
    "joy_per_dollar": "Joy per dollar",
    "wildcard": "Unexpected discovery bonus",
}


def build_match_breakdown(
    signals: Mapping[str, float],
    *,
    score: float,
    interests: Sequence[str] = (),
    nearby_pin_count: int = 0,
) -> tuple[MatchFactor, ...]:
    """Convert 0–1 signals into point contributions that sum toward the score."""
    ranked = sorted(signals.items(), key=lambda item: item[1], reverse=True)
    factors: list[MatchFactor] = []
    for key, value in ranked:
        if value < 0.15:
            continue
        label = _SIGNAL_LABELS.get(key, key.replace("_", " ").title())
        if key == "interest_tag_overlap" and interests:
            label = f"Saved interest: {', '.join(list(interests)[:2])}"
        points = round(value * (score / max(sum(max(0.0, v) for _, v in ranked), 1e-6)) * max(value, 0.01), 1)
        # Simpler point model: scale signal into points proportional to score share.
        points = round(value * 25.0, 1)
        factors.append(MatchFactor(label=label, points=points, matched=value >= 0.35))
    if nearby_pin_count:
        factors.append(
            MatchFactor(
                label=f"Nearby {nearby_pin_count} saved pin(s)",
                points=min(16.0, nearby_pin_count * 4.0),
                matched=True,
            )
        )
    factors.sort(key=lambda f: f.points, reverse=True)
    return tuple(factors[:10])


def explain_recommendation(
    *,
    title: str,
    signals: Mapping[str, float],
    interests: Sequence[str] = (),
    pace: str = "medium",
    top_n: int = 2,
    match_breakdown: Sequence[MatchFactor] = (),
) -> str:
    if match_breakdown:
        top = list(match_breakdown)[:top_n]
        bits = [f"{f.label} (+{f.points:g})" for f in top]
        if len(bits) == 1:
            return f"Visit {title} because {bits[0]}."
        return f"Visit {title} because {bits[0]}, and {bits[1]}."

    # Fallback short prose when breakdown unavailable.
    _SIGNAL_TEMPLATES = {
        "interest_tag_overlap": "it matches interests you have already expressed ({detail})",
        "saved_pin_boost": "it is already among your saved pins for this destination",
        "theme_fit": "it fits today's planning theme",
        "rating_history": "your past ratings favor this kind of place",
        "joy_per_dollar": "it offers strong personal joy relative to cost",
        "hidden_gem": "it looks like a personal fit that is less crowded among your saved places",
        "pace_fit": "its duration fits the {pace} pace you chose for this trip",
        "budget_fit": "its estimated cost fits your budget posture",
    }
    ranked = sorted(signals.items(), key=lambda item: item[1], reverse=True)
    reasons: list[str] = []
    for key, value in ranked:
        if value < 0.25 or key not in _SIGNAL_TEMPLATES:
            continue
        detail = ", ".join(interests[:3]) if interests else "your stated interests"
        reasons.append(_SIGNAL_TEMPLATES[key].format(detail=detail, pace=pace))
        if len(reasons) >= top_n:
            break
    if not reasons:
        return (
            f"Visit {title} because it is available in this destination "
            "and may suit a general traveler."
        )
    if len(reasons) == 1:
        return f"Visit {title} because {reasons[0]}."
    return f"Visit {title} because {reasons[0]}, and {reasons[1]}."


def format_why_block(
    *,
    score: float,
    match_breakdown: Sequence[MatchFactor],
) -> dict:
    """Structured payload for UI 'Why this?' panels."""
    return {
        "overall_match": round(score, 1),
        "factors": [
            {"label": f.label, "points": f.points, "matched": f.matched}
            for f in match_breakdown
        ],
    }
