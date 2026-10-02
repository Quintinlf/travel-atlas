"""Pure signal extractors for recommendation scoring."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from src_phase1.insights import real_note
from src_phase1.models import SavedLocation

from travel_atlas.services.types import TripDefinition, UserProfileView

from .estimates import estimate_cost, estimate_duration

# Map preference-bag / interest tokens onto taxonomy tags and claim topics.
INTEREST_TAG_ALIASES: dict[str, frozenset[str]] = {
    "market_food": frozenset({"market_food", "food", "cuisine", "restaurant", "dining"}),
    "museum_history": frozenset(
        {"museum_history", "museum", "history", "heritage", "gallery", "science", "astronomy"}
    ),
    "nature_gardens": frozenset({"nature_gardens", "nature", "outdoor", "park", "hiking", "garden"}),
    "temple_spirituality": frozenset({"temple_spirituality", "spiritual", "religion", "temple"}),
    "transport": frozenset({"transport", "train", "transit", "rail", "metro"}),
    "nightlife": frozenset({"nightlife", "bar", "club", "evening"}),
    "shopping": frozenset({"shopping", "market", "retail"}),
    "accommodation": frozenset({"accommodation", "hotel", "lodging"}),
}

CLAIM_TOPIC_ALIASES: dict[str, frozenset[str]] = {
    "food": frozenset({"cuisine", "food", "dining", "restaurants", "markets", "food_water_safety"}),
    "museum": frozenset({"museums", "history", "heritage", "culture", "art"}),
    "nature": frozenset({"outdoors", "nature", "parks", "hiking"}),
    "transport": frozenset({"getting_around", "transport", "transit", "trains"}),
}


def _interest_tokens(profile: UserProfileView) -> set[str]:
    tokens: set[str] = {t.lower() for t in profile.interests}
    bag = profile.preferences or {}
    for key in (
        "favorite_foods",
        "museum_types",
        "historical_interests",
        "outdoor_interests",
    ):
        value = bag.get(key)
        if isinstance(value, (list, tuple)):
            tokens.update(str(v).lower() for v in value)
        elif value:
            tokens.add(str(value).lower())
    for key in ("nightlife_interest", "shopping_interest"):
        if bag.get(key):
            tokens.add(key.replace("_interest", ""))
    transport = bag.get("transportation_preferences")
    if isinstance(transport, (list, tuple)):
        tokens.update(str(v).lower() for v in transport)
    elif transport:
        tokens.add(str(transport).lower())
    return tokens


def interest_tag_overlap(tags: Sequence[str], profile: UserProfileView) -> float:
    tokens = _interest_tokens(profile)
    if not tokens or not tags:
        return 0.0
    hits = 0
    for tag in tags:
        aliases = INTEREST_TAG_ALIASES.get(tag, frozenset({tag}))
        if tokens & aliases or any(a in token or token in a for token in tokens for a in aliases):
            hits += 1
    return min(1.0, hits / max(len(tags), 1))


def pin_affinity(pin: SavedLocation) -> float:
    score = 0.0
    note = real_note(pin)
    if note:
        score += min(1.0, len(note) / 200.0) * 0.6
        score += min(1.0, note.count("\n") / 5.0) * 0.2
    priority = getattr(pin, "user_priority", None) or 0
    try:
        score += min(1.0, float(priority) / 5.0) * 0.2
    except (TypeError, ValueError):
        pass
    return min(1.0, score)


def atlas_claim_relevance(
    category: str,
    claim_topics: Sequence[str],
    profile: UserProfileView,
) -> float:
    tokens = _interest_tokens(profile)
    if not tokens:
        return 0.0
    topic_set = {t.lower() for t in claim_topics}
    # Also fold category-level aliases.
    for key, aliases in CLAIM_TOPIC_ALIASES.items():
        if key in category or any(a in category for a in aliases):
            topic_set |= aliases
    if not topic_set:
        return 0.0
    overlap = 0
    for token in tokens:
        if any(token in topic or topic in token for topic in topic_set):
            overlap += 1
    return min(1.0, overlap / max(len(tokens), 1) * 3)


def saved_pin_boost(is_saved_pin: bool) -> float:
    return 1.0 if is_saved_pin else 0.0


def pace_fit(duration_hours: float, pace: str) -> float:
    targets = {"slow": 2.5, "medium": 1.75, "fast": 1.0}
    target = targets.get(pace, 1.75)
    # Prefer activities near the pace target duration.
    delta = abs(duration_hours - target)
    return max(0.0, 1.0 - delta / 3.0)


def budget_fit(
    cost: float,
    daily_cap: float | None,
) -> float:
    if daily_cap is None or daily_cap <= 0:
        return 0.5
    if cost <= daily_cap * 0.35:
        return 1.0
    if cost <= daily_cap:
        return 0.7
    if cost <= daily_cap * 1.5:
        return 0.3
    return 0.0


def hidden_gem(
    *,
    interest_overlap: float,
    peer_count: int,
    has_long_note: bool,
) -> float:
    """High personal fit with lower generic density among destination pins."""
    rarity = 1.0 / (1.0 + max(peer_count - 1, 0) * 0.15)
    personal = interest_overlap
    note_boost = 0.15 if has_long_note else 0.0
    return min(1.0, 0.55 * personal + 0.35 * rarity + note_boost)


def transport_fit(category: str, trip: TripDefinition, profile: UserProfileView) -> float:
    prefs = list(trip.transportation_preferences) + list(
        profile.preferences.get("transportation_preferences") or []
        if isinstance(profile.preferences.get("transportation_preferences"), (list, tuple))
        else ([profile.preferences.get("transportation_preferences")]
              if profile.preferences.get("transportation_preferences") else [])
    )
    prefs_l = {str(p).lower() for p in prefs if p}
    if not prefs_l:
        return 0.5 if category == "transport" else 0.4
    if category == "transport":
        return 1.0 if prefs_l else 0.6
    if any(p in {"walking", "walk"} for p in prefs_l) and category in {
        "nature_gardens", "market_food", "museum_history"
    }:
        return 0.8
    return 0.4


def joy_per_dollar(interest: float, pin_aff: float, cost: float, daily_cap: float | None) -> float:
    """Personal joy relative to spend — core planning philosophy signal."""
    joy = 0.65 * interest + 0.35 * pin_aff
    if cost <= 0:
        return joy
    ref = daily_cap if daily_cap and daily_cap > 0 else 100.0
    efficiency = max(0.0, 1.0 - (cost / (ref * 2.0)))
    return min(1.0, 0.55 * joy + 0.45 * efficiency * max(joy, 0.2))


def rating_history_signal(rating_score: float | None, is_skip: bool) -> float:
    if is_skip:
        return 0.0
    if rating_score is None:
        return 0.5
    # Map [-1, 1] → [0, 1]
    return max(0.0, min(1.0, 0.5 + 0.5 * rating_score))


def build_signal_vector(
    *,
    tags: Sequence[str],
    category: str,
    pin: SavedLocation | None,
    profile: UserProfileView,
    trip: TripDefinition,
    config: Mapping[str, Any],
    claim_topics: Sequence[str] = (),
    peer_count: int = 1,
    is_saved_pin: bool = False,
    theme_fit_value: float = 0.5,
    energy_fit_value: float = 0.5,
    rating_score: float | None = None,
    is_skip: bool = False,
    wildcard: bool = False,
) -> dict[str, float]:
    duration = estimate_duration(category, config)
    cost = estimate_cost(category, config)
    from .estimates import daily_budget_cap

    daily_cap = daily_budget_cap(
        trip.budget, trip.day_count, profile.preferences, config
    )
    overlap = interest_tag_overlap(tags, profile)
    affinity = pin_affinity(pin) if pin else 0.0
    note = real_note(pin) if pin else None
    signals = {
        "interest_tag_overlap": overlap,
        "pin_affinity": affinity,
        "atlas_claim_relevance": atlas_claim_relevance(category, claim_topics, profile),
        "saved_pin_boost": saved_pin_boost(is_saved_pin),
        "pace_fit": pace_fit(duration, trip.pace),
        "budget_fit": budget_fit(cost, daily_cap),
        "hidden_gem": hidden_gem(
            interest_overlap=overlap,
            peer_count=peer_count,
            has_long_note=bool(note and len(note) > 80),
        ),
        "transport_fit": transport_fit(category, trip, profile),
        "theme_fit": theme_fit_value,
        "energy_fit": energy_fit_value,
        "rating_history": rating_history_signal(rating_score, is_skip),
        "joy_per_dollar": joy_per_dollar(overlap, affinity, cost, daily_cap),
        "wildcard": 0.85 if wildcard else 0.0,
    }
    return signals


def pin_priority_tier(pin: SavedLocation | None, rating: str | None) -> str:
    """Saved pins are the backbone — tier them for the planner UI."""
    if rating == "loved":
        return "must_visit"
    if rating == "liked":
        return "interested"
    if rating in {"disliked", "skip"}:
        return "not_planned"
    if pin is None:
        return "discovery"
    priority = getattr(pin, "user_priority", 5) or 5
    try:
        p = int(priority)
    except (TypeError, ValueError):
        p = 5
    if p >= 8:
        return "must_visit"
    if p >= 6:
        return "interested"
    if p >= 4:
        return "maybe"
    return "maybe"
