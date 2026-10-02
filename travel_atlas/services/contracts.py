"""Application contracts that future Django adapters and views can consume."""

from __future__ import annotations

from datetime import date
from typing import Any, Protocol

from .types import Lesson, PlannerReport, TripDefinition


class DestinationContextReader(Protocol):
    def get_destination_context(self, city: str | None, country: str | None = None) -> dict: ...


class PinDetailsReader(Protocol):
    def get_pin_details(self, pin_id: str) -> object | None: ...


class LanguageLessonGenerator(Protocol):
    def generate_language_lesson(
        self, pin_ids: list[str], user_key: str = "local-default"
    ) -> list[Lesson]: ...


class ItineraryReader(Protocol):
    def get_itinerary(self, day: int) -> dict: ...


class SeasonalContextReader(Protocol):
    def get_seasonal_context(
        self,
        *,
        area_id: str | None,
        start_date: date,
        end_date: date | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> dict: ...


class PlanningEngineProtocol(Protocol):
    """Read-only personalized planning surface for Django or Streamlit."""

    def plan(
        self,
        *,
        destination_kind: str,
        destination_label: str,
        trip: TripDefinition | None = None,
        user_key: str = "local-default",
    ) -> PlannerReport: ...

    def answer(
        self,
        question_key: str,
        *,
        destination_kind: str,
        destination_label: str,
        trip: TripDefinition | None = None,
        user_key: str = "local-default",
    ) -> Any: ...
