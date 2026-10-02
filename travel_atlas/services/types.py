"""Service-level value objects independent of Streamlit and Django."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class AreaResolution:
    area_id: str | None
    area_name: str | None
    area_type: str | None
    method: str
    confidence: float
    context_status: str


@dataclass(frozen=True)
class PinContext:
    pin_id: str
    pin_name: str
    city: str | None
    country: str | None
    resolution: AreaResolution
    classification: dict[str, Any]
    claims_by_category: dict[str, list[dict[str, Any]]]
    coverage: list[dict[str, Any]]
    related_pins: list[dict[str, Any]]


@dataclass(frozen=True)
class Lesson:
    id: str
    pin_id: str
    title: str
    context_text: str
    phrases: list[dict[str, str]]
    explanation: dict[str, Any]
    lesson_source: str


@dataclass(frozen=True)
class SeasonalNote:
    """Typed view of a knowledge_claim row carrying a recurring annual window."""

    id: str
    area_id: str
    category_key: str
    topic_key: str
    title: str
    body: str
    source_id: str
    confidence: str
    review_status: str
    season_start_month_day: str
    season_end_month_day: str
    season_label: str | None


@dataclass(frozen=True)
class TripDefinition:
    """Trip constraints used by the planning engine (read-only input)."""

    destination_kind: str
    destination_label: str
    cities: tuple[str, ...] = ()
    start_date: str | None = None
    end_date: str | None = None
    day_count: int = 3
    budget: float | None = None
    transportation_preferences: tuple[str, ...] = ()
    lodging_preferences: tuple[str, ...] = ()
    travel_style: str = "balanced"
    pace: str = "medium"  # slow | medium | fast
    energy: str = "medium"  # low | medium | high — default medium effort
    theme_overrides: Mapping[int, str] = field(default_factory=dict)


@dataclass(frozen=True)
class UserProfileView:
    """Long-term traveler preferences; bag is expandable without schema rewrites."""

    user_key: str
    interests: tuple[str, ...]
    travel_style: str
    accommodation_preferences: Mapping[str, Any]
    learning_goals: tuple[str, ...]
    preferences: Mapping[str, Any]


@dataclass(frozen=True)
class MatchFactor:
    """One transparent contribution to 'Why this?'."""

    label: str
    points: float
    matched: bool = True


@dataclass(frozen=True)
class Recommendation:
    """A personalized suggestion answering what exists and why it matters here."""

    title: str
    category: str
    location: str
    estimated_duration_hours: float
    estimated_cost: float
    confidence: float
    explanation: str
    score: float
    signals: Mapping[str, float]
    source_refs: Mapping[str, str]
    match_breakdown: tuple[MatchFactor, ...] = ()
    priority_tier: str = "discovery"  # must_visit | interested | maybe | discovery
    user_rating: str | None = None
    joy_per_dollar: float | None = None


@dataclass(frozen=True)
class PlannerReport:
    """Full planning output for one destination + traveler context."""

    destination_kind: str
    destination_label: str
    summary: str
    experiences: tuple[Recommendation, ...]
    food: tuple[Recommendation, ...]
    museums: tuple[Recommendation, ...]
    transportation: tuple[Recommendation, ...]
    itinerary: tuple[Mapping[str, Any], ...]
    budget: Mapping[str, Any]
    packing: tuple[str, ...]
    skip: tuple[Recommendation, ...] = ()
    area_id: str | None = None
    coverage: Mapping[str, Any] = field(default_factory=dict)
    themes: tuple[Mapping[str, Any], ...] = ()
    wildcards: tuple[Recommendation, ...] = ()
    food_subsystem: Mapping[str, Any] = field(default_factory=dict)
    pin_backbone: tuple[Mapping[str, Any], ...] = ()
    energy: str = "medium"
    exploration_mix: Mapping[str, float] = field(
        default_factory=lambda: {"personalized": 0.9, "discovery": 0.1}
    )
