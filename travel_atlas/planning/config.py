"""Default and file-backed planning configuration."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

DEFAULT_PLANNING_CONFIG: dict[str, Any] = {
    "max_recommendations_per_section": 8,
    "philosophy": "maximum_personal_joy_per_dollar",
    "exploration_mix": {"personalized": 0.9, "discovery": 0.1},
    "default_energy": "medium",
    "max_pins_per_day": {"slow": 2, "medium": 4, "fast": 6},
    "weights": {
        # Joy / dollar philosophy: personal interest + efficiency dominate.
        "interest_tag_overlap": 0.18,
        "joy_per_dollar": 0.14,
        "saved_pin_boost": 0.16,
        "pin_affinity": 0.10,
        "rating_history": 0.10,
        "theme_fit": 0.08,
        "atlas_claim_relevance": 0.06,
        "pace_fit": 0.05,
        "energy_fit": 0.05,
        "budget_fit": 0.04,
        "hidden_gem": 0.03,
        "transport_fit": 0.01,
        "wildcard": 0.0,  # applied only to discovery candidates
    },
    "wildcard_weights": {
        "interest_tag_overlap": 0.10,
        "joy_per_dollar": 0.08,
        "saved_pin_boost": 0.0,
        "pin_affinity": 0.05,
        "rating_history": 0.05,
        "theme_fit": 0.10,
        "atlas_claim_relevance": 0.12,
        "pace_fit": 0.05,
        "energy_fit": 0.05,
        "budget_fit": 0.05,
        "hidden_gem": 0.15,
        "transport_fit": 0.05,
        "wildcard": 0.15,
    },
    "category_costs": {
        "market_food": 25.0,
        "museum_history": 15.0,
        "temple_spirituality": 5.0,
        "nature_gardens": 0.0,
        "transport": 10.0,
        "accommodation": 80.0,
        "nightlife": 40.0,
        "shopping": 50.0,
        "general_travel": 20.0,
    },
    "category_durations": {
        "market_food": 1.5,
        "museum_history": 2.0,
        "temple_spirituality": 1.5,
        "nature_gardens": 2.0,
        "transport": 0.5,
        "accommodation": 0.5,
        "nightlife": 2.0,
        "shopping": 1.5,
        "general_travel": 1.0,
    },
    "budget_tendency_daily": {
        "frugal": 40.0,
        "moderate": 100.0,
        "comfortable": 200.0,
        "luxury": 400.0,
    },
    "food_facets": [
        "regional_foods",
        "seasonal_foods",
        "markets",
        "groceries",
        "cooking_classes",
        "historical_dishes",
        "desserts",
        "street_food",
        "local_drinks",
        "ingredients",
        "recipes_to_recreate",
    ],
}


def default_planning_config() -> dict[str, Any]:
    return deepcopy(DEFAULT_PLANNING_CONFIG)


def load_planning_config(path: Path | None = None) -> dict[str, Any]:
    """Merge YAML ``planning:`` section over defaults when PyYAML is available."""
    config = default_planning_config()
    if path is None:
        path = Path(__file__).resolve().parents[2] / "config" / "travel_config.yaml"
    if not path.exists():
        return config
    try:
        import yaml  # type: ignore
    except ImportError:
        return config
    with path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    section = raw.get("planning") or {}
    for key, value in section.items():
        if isinstance(value, dict) and isinstance(config.get(key), dict):
            config[key] = {**config[key], **value}
        else:
            config[key] = value
    return config
