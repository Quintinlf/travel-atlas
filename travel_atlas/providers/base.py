"""Shared provider result type and Protocol markers.

Planner and Command Center ask providers for signals — never for
implementation details. Swap stubs for live backends without UI changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable


@dataclass(frozen=True)
class StubResult:
    """Provider response. Live backends keep this shape so UI stays stable."""

    provider: str
    status: str  # ok | stub | unavailable
    payload: Mapping[str, Any]
    links: Mapping[str, str] = field(default_factory=dict)


@runtime_checkable
class WeatherProvider(Protocol):
    key: str

    def forecast(self, *, latitude: float, longitude: float, on_date: str | None = None) -> StubResult: ...


@runtime_checkable
class TransitProvider(Protocol):
    key: str

    def route(
        self,
        *,
        from_lat: float,
        from_lng: float,
        to_lat: float,
        to_lng: float,
    ) -> StubResult: ...


@runtime_checkable
class FlightProvider(Protocol):
    key: str

    def search(self, *, destination: str) -> StubResult: ...


@runtime_checkable
class HotelProvider(Protocol):
    key: str

    def search(self, *, destination: str) -> StubResult: ...


@runtime_checkable
class RestaurantProvider(Protocol):
    key: str

    def search(self, *, destination: str, query: str = "") -> StubResult: ...


@runtime_checkable
class TranslationProvider(Protocol):
    key: str

    def phrases(self, *, topic: str, language_hint: str = "") -> StubResult: ...


@runtime_checkable
class BookingProvider(Protocol):
    """Deep-link compare only — no payments / PCI in this phase."""

    key: str

    def search(
        self,
        *,
        destination: str,
        kind: str = "hotel",
        check_in: str | None = None,
        check_out: str | None = None,
    ) -> StubResult: ...


@runtime_checkable
class LanguageProvider(Protocol):
    """Atlas schedules; external language project teaches."""

    key: str

    def next_lesson(
        self,
        *,
        destination: str,
        locality: str | None = None,
        interests: list[str] | None = None,
    ) -> StubResult: ...


@runtime_checkable
class SafetyProvider(Protocol):
    key: str

    def advisories(self, *, destination: str) -> StubResult: ...


@runtime_checkable
class CalendarProvider(Protocol):
    key: str

    def upcoming(self, *, days: int = 14) -> StubResult: ...


@runtime_checkable
class PhotoProvider(Protocol):
    """Manual/local now; phone or cloud libraries later."""

    key: str

    def list_candidates(self, *, trip_id: str) -> StubResult: ...

    def import_photo(self, *, trip_id: str, source_uri: str) -> StubResult: ...


@runtime_checkable
class ReservationAvailabilityProvider(Protocol):
    key: str

    def check(self, *, title: str, kind: str, on_date: str | None = None) -> StubResult: ...


@runtime_checkable
class ShoppingProvider(Protocol):
    """Stub only — bring-home recommendations deferred."""

    key: str

    def recommendations(self, *, destination: str, interests: list[str] | None = None) -> StubResult: ...


@runtime_checkable
class AstrologyProvider(Protocol):
    """Protocol stub only — not implemented this phase."""

    key: str

    def signals(self, *, destination: str, on_date: str | None = None) -> StubResult: ...
