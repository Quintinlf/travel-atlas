"""Assembles time-aware sky events and seasonally matched knowledge for a place."""

from __future__ import annotations

from datetime import date, timedelta

from ..adapters import AstronomyAdapter, SkyEvent
from ..astronomy import AstralAstronomyAdapter
from ..repository import AtlasRepository
from ..seasonal_matching import date_range_touches_window
from .notes_service import NotesService

_MAX_LANDMARK_SCAN_DAYS = 60  # bounds cost for very long multi-week trips
_LANDMARK_KINDS = {"solstice", "equinox", "meteor_shower"}


class SeasonalContextService:
    def __init__(
        self,
        repository: AtlasRepository,
        astronomy_adapter: AstronomyAdapter | None = None,
    ) -> None:
        self.repository = repository
        self.astronomy_adapter = astronomy_adapter or AstralAstronomyAdapter()

    def get_seasonal_context(
        self,
        *,
        area_id: str | None,
        start_date: date,
        end_date: date | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> dict:
        end_date = end_date or start_date
        lat, lon = self._resolve_coordinates(area_id, latitude, longitude)

        anchor_events: list[SkyEvent] = []
        landmark_events: list[SkyEvent] = []
        if lat is not None and lon is not None:
            anchor_events = list(
                self.astronomy_adapter.fetch(latitude=lat, longitude=lon, on_date=start_date).events
            )
            landmark_events = self._landmark_events_in_range(lat, lon, start_date, end_date)

        seasonal_claims: list[dict] = []
        personal_notes: list[dict] = []
        if area_id:
            for claim in self.repository.list_seasonal_claims(area_id):
                if not date_range_touches_window(
                    start_date,
                    end_date,
                    claim["season_start_month_day"],
                    claim["season_end_month_day"],
                ):
                    continue
                bucket = (
                    personal_notes if claim["source_id"] == NotesService.USER_SOURCE_ID else seasonal_claims
                )
                bucket.append(claim)

        return {
            "area_id": area_id,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "anchor_sky_events": [self._event_to_dict(event) for event in anchor_events],
            "landmark_sky_events": [self._event_to_dict(event) for event in landmark_events],
            "seasonal_claims": seasonal_claims,
            "personal_notes": personal_notes,
        }

    def _resolve_coordinates(
        self, area_id: str | None, latitude: float | None, longitude: float | None
    ) -> tuple[float | None, float | None]:
        if latitude is not None and longitude is not None:
            return latitude, longitude
        if area_id:
            area = self.repository.get_area(area_id)
            if area and area.get("latitude") is not None and area.get("longitude") is not None:
                return area["latitude"], area["longitude"]
        return None, None

    def _landmark_events_in_range(
        self, lat: float, lon: float, start_date: date, end_date: date
    ) -> list[SkyEvent]:
        span_days = min((end_date - start_date).days, _MAX_LANDMARK_SCAN_DAYS)
        seen_keys: set[str] = set()
        events: list[SkyEvent] = []
        for offset in range(max(span_days, 0) + 1):
            snapshot = self.astronomy_adapter.fetch(
                latitude=lat, longitude=lon, on_date=start_date + timedelta(days=offset)
            )
            for event in snapshot.events:
                if event.kind in _LANDMARK_KINDS and event.key not in seen_keys:
                    seen_keys.add(event.key)
                    events.append(event)
        return events

    @staticmethod
    def _event_to_dict(event: SkyEvent) -> dict:
        return {
            "key": event.key,
            "kind": event.kind,
            "title": event.title,
            "description": event.description,
            "occurs_on": event.occurs_on.isoformat(),
            "detail": dict(event.detail),
        }
