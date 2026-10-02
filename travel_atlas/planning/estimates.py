"""Duration and cost heuristics from taxonomy category + planning config."""

from __future__ import annotations

from typing import Any, Mapping

from src_phase1.models import SavedLocation

from travel_atlas.services.taxonomy import TAG_RULES


def classify_tags_readonly(pin: SavedLocation) -> list[str]:
    """In-memory taxonomy tags — never persists classifications."""
    fields = {
        "name": pin.name,
        "category": pin.category or "",
        "notes": pin.notes or "",
        "list_name": pin.list_name,
        "tags": " ".join(pin.tags or []),
    }
    normalized = {field: value.lower() for field, value in fields.items()}
    tags: list[str] = []
    for tag, terms in TAG_RULES.items():
        for field, text in normalized.items():
            if any(term in text for term in terms):
                tags.append(tag)
                break
    return sorted(set(tags)) or ["general_travel"]


def primary_category(tags: list[str]) -> str:
    priority = (
        "museum_history",
        "market_food",
        "nature_gardens",
        "temple_spirituality",
        "transport",
        "accommodation",
        "nightlife",
        "shopping",
        "general_travel",
    )
    for key in priority:
        if key in tags:
            return key
    return tags[0] if tags else "general_travel"


def estimate_duration(category: str, config: Mapping[str, Any]) -> float:
    durations = config.get("category_durations") or {}
    return float(durations.get(category, durations.get("general_travel", 1.0)))


def estimate_cost(category: str, config: Mapping[str, Any]) -> float:
    costs = config.get("category_costs") or {}
    return float(costs.get(category, costs.get("general_travel", 20.0)))


def daily_budget_cap(
    trip_budget: float | None,
    day_count: int,
    preferences: Mapping[str, Any],
    config: Mapping[str, Any],
) -> float | None:
    if trip_budget is not None and day_count > 0:
        return float(trip_budget) / max(day_count, 1)
    tendency = str(preferences.get("budget_tendency") or "moderate").lower()
    table = config.get("budget_tendency_daily") or {}
    value = table.get(tendency)
    return float(value) if value is not None else None


def packing_suggestions(
    *,
    preferences: Mapping[str, Any],
    pace: str,
    month: int | None,
    climate_hint: str | None,
) -> list[str]:
    items: list[str] = ["Comfortable walking shoes", "Reusable water bottle"]
    outdoor = preferences.get("outdoor_interests") or []
    if outdoor or preferences.get("outdoor_interest"):
        items.append("Weather-appropriate outer layer for outdoor time")
    if preferences.get("nightlife_interest"):
        items.append("One evening outfit suitable for nightlife")
    if preferences.get("shopping_interest"):
        items.append("Packable tote for markets and shopping")
    if pace == "fast":
        items.append("Compact daypack for long multi-stop days")
    elif pace == "slow":
        items.append("Light reading material for unhurried afternoons")
    if climate_hint:
        items.append(climate_hint)
    elif month in {12, 1, 2}:
        items.append("Layers for cooler winter temperatures")
    elif month in {6, 7, 8}:
        items.append("Sun protection and breathable clothing")
    return items
