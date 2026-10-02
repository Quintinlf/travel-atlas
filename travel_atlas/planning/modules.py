"""Pluggable planning modules — contribute candidates or section payloads."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from travel_atlas.services.types import Recommendation, TripDefinition, UserProfileView


@dataclass
class Candidate:
    """Raw candidate before scoring aggregation."""

    title: str
    category: str
    location: str
    tags: list[str]
    claim_topics: list[str] = field(default_factory=list)
    pin_id: str | None = None
    claim_id: str | None = None
    is_saved_pin: bool = False
    peer_count: int = 1
    pin: Any = None  # SavedLocation | None — avoided import cycle at type level


@dataclass
class ModuleSection:
    key: str
    title: str
    recommendations: tuple[Recommendation, ...] = ()
    payload: Mapping[str, Any] = field(default_factory=dict)
    coming_soon: bool = False


@runtime_checkable
class PlanningModule(Protocol):
    """Future airfare/hotels/trains/weather/ratings implement this Protocol."""

    key: str

    def contribute_candidates(
        self,
        *,
        trip: TripDefinition,
        profile: UserProfileView,
        context: Mapping[str, Any],
    ) -> Sequence[Candidate]:
        ...

    def build_section(
        self,
        *,
        recommendations: Sequence[Recommendation],
        trip: TripDefinition,
        profile: UserProfileView,
        context: Mapping[str, Any],
    ) -> ModuleSection:
        ...


class _BaseModule:
    key = "base"
    section_title = "Section"
    category_filter: frozenset[str] | None = None

    def contribute_candidates(
        self,
        *,
        trip: TripDefinition,
        profile: UserProfileView,
        context: Mapping[str, Any],
    ) -> Sequence[Candidate]:
        # Candidates are built once by the engine; modules only filter in build_section.
        return []

    def build_section(
        self,
        *,
        recommendations: Sequence[Recommendation],
        trip: TripDefinition,
        profile: UserProfileView,
        context: Mapping[str, Any],
    ) -> ModuleSection:
        filtered = recommendations
        if self.category_filter is not None:
            filtered = [r for r in recommendations if r.category in self.category_filter]
        limit = int(context.get("limit") or 8)
        return ModuleSection(
            key=self.key,
            title=self.section_title,
            recommendations=tuple(filtered[:limit]),
        )


class ExperiencesModule(_BaseModule):
    key = "experiences"
    section_title = "Recommended Experiences"
    # Everything except pure transport/accommodation noise.
    category_filter = None

    def build_section(
        self,
        *,
        recommendations: Sequence[Recommendation],
        trip: TripDefinition,
        profile: UserProfileView,
        context: Mapping[str, Any],
    ) -> ModuleSection:
        skip = {"transport", "accommodation"}
        # Prefer saved pins in the experiences section so personal places surface first.
        pins = [r for r in recommendations if r.category not in skip and "pin_id" in r.source_refs]
        claims = [
            r for r in recommendations if r.category not in skip and "pin_id" not in r.source_refs
        ]
        filtered = pins + claims
        limit = int(context.get("limit") or 8)
        return ModuleSection(
            key=self.key,
            title=self.section_title,
            recommendations=tuple(filtered[:limit]),
        )


class FoodModule(_BaseModule):
    key = "food"
    section_title = "Food"
    category_filter = frozenset({"market_food"})


class MuseumsModule(_BaseModule):
    key = "museums"
    section_title = "Museums"
    category_filter = frozenset({"museum_history"})


class TransportModule(_BaseModule):
    key = "transportation"
    section_title = "Transportation"
    category_filter = frozenset({"transport"})

    def build_section(
        self,
        *,
        recommendations: Sequence[Recommendation],
        trip: TripDefinition,
        profile: UserProfileView,
        context: Mapping[str, Any],
    ) -> ModuleSection:
        section = super().build_section(
            recommendations=recommendations,
            trip=trip,
            profile=profile,
            context=context,
        )
        prefs = list(trip.transportation_preferences)
        bag = profile.preferences.get("transportation_preferences")
        if isinstance(bag, (list, tuple)):
            prefs.extend(str(x) for x in bag)
        links = context.get("planning_links") or {}
        return ModuleSection(
            key=section.key,
            title=section.title,
            recommendations=section.recommendations,
            payload={
                "preferences": prefs,
                "planning_links": links,
                "note": (
                    "Prefer " + ", ".join(prefs)
                    if prefs
                    else "No transportation preference set — using general guidance."
                ),
            },
        )


class ItineraryModule(_BaseModule):
    key = "itinerary"
    section_title = "Suggested Itinerary"

    def contribute_candidates(
        self,
        *,
        trip: TripDefinition,
        profile: UserProfileView,
        context: Mapping[str, Any],
    ) -> Sequence[Candidate]:
        return []

    def build_section(
        self,
        *,
        recommendations: Sequence[Recommendation],
        trip: TripDefinition,
        profile: UserProfileView,
        context: Mapping[str, Any],
    ) -> ModuleSection:
        days = context.get("itinerary_days") or []
        return ModuleSection(
            key=self.key,
            title=self.section_title,
            recommendations=(),
            payload={"days": days},
        )


class BudgetModule(_BaseModule):
    key = "budget"
    section_title = "Budget Estimate"

    def contribute_candidates(self, **kwargs: Any) -> Sequence[Candidate]:
        return []

    def build_section(
        self,
        *,
        recommendations: Sequence[Recommendation],
        trip: TripDefinition,
        profile: UserProfileView,
        context: Mapping[str, Any],
    ) -> ModuleSection:
        budget_payload = context.get("budget") or {}
        return ModuleSection(
            key=self.key,
            title=self.section_title,
            recommendations=(),
            payload=budget_payload,
        )


class PackingModule(_BaseModule):
    key = "packing"
    section_title = "Packing Considerations"

    def contribute_candidates(self, **kwargs: Any) -> Sequence[Candidate]:
        return []

    def build_section(
        self,
        *,
        recommendations: Sequence[Recommendation],
        trip: TripDefinition,
        profile: UserProfileView,
        context: Mapping[str, Any],
    ) -> ModuleSection:
        items = context.get("packing") or []
        return ModuleSection(
            key=self.key,
            title=self.section_title,
            recommendations=(),
            payload={"items": list(items)},
        )


class WildcardModule(_BaseModule):
    """'I didn't know I'd like this' — adjacent surprises, not random noise."""

    key = "wildcards"
    section_title = "I Didn't Know I'd Like This"

    def contribute_candidates(self, **kwargs: Any) -> Sequence[Candidate]:
        return []

    def build_section(
        self,
        *,
        recommendations: Sequence[Recommendation],
        trip: TripDefinition,
        profile: UserProfileView,
        context: Mapping[str, Any],
    ) -> ModuleSection:
        return ModuleSection(
            key=self.key,
            title=self.section_title,
            recommendations=tuple(context.get("wildcards") or ()),
            payload={"note": "10% discovery mix — unexpected links to your interests."},
        )


class StubModule:
    """Placeholder so future features plug into the same registry."""

    def __init__(self, key: str, title: str) -> None:
        self.key = key
        self.section_title = title

    def contribute_candidates(
        self,
        *,
        trip: TripDefinition,
        profile: UserProfileView,
        context: Mapping[str, Any],
    ) -> Sequence[Candidate]:
        return []

    def build_section(
        self,
        *,
        recommendations: Sequence[Recommendation],
        trip: TripDefinition,
        profile: UserProfileView,
        context: Mapping[str, Any],
    ) -> ModuleSection:
        return ModuleSection(
            key=self.key,
            title=self.section_title,
            coming_soon=True,
            payload={"status": "coming_soon"},
        )


def default_modules() -> list[PlanningModule]:
    modules: list[PlanningModule] = [
        ExperiencesModule(),
        FoodModule(),
        MuseumsModule(),
        TransportModule(),
        ItineraryModule(),
        BudgetModule(),
        PackingModule(),
        WildcardModule(),
    ]
    for key, title in (
        ("airfare", "Airfare Monitoring"),
        ("hotels", "Hotel Recommendations"),
        ("trains", "Train Planning"),
        ("reservations", "Restaurant Reservations"),
        ("weather", "Weather Forecasts"),
        ("language", "Language Learning"),
        ("alerts", "Travel Alerts"),
        ("ratings", "Post-Trip Reviews"),
    ):
        modules.append(StubModule(key, title))  # type: ignore[arg-type]
    return modules
