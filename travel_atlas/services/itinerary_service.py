"""Day-plan suggestions built from nearby saved places (offline, no optimizer)."""

from __future__ import annotations

from src_phase1.models import SavedLocation
from src_phase1.pin_repository import haversine_km

from .pin_service import PinService


class ItineraryService:
    def __init__(self, pin_service: PinService) -> None:
        self.pin_service = pin_service

    def get_itinerary(self, day: int) -> dict:
        """Return a stable placeholder contract until saved itineraries exist."""
        return {
            "day": day,
            "stops": [],
            "message": "No saved itinerary yet. Use nearby saved places to begin exploring.",
        }

    def suggest_day_plan(self, pin: SavedLocation, nearby_limit: int = 5) -> dict:
        """Build a morning/afternoon/evening outline from the pin and nearby saves."""
        nearby = self.pin_service.nearby_pins(pin, limit=nearby_limit)
        ordered = sorted(
            nearby,
            key=lambda other: haversine_km(
                pin.latitude, pin.longitude, other.latitude, other.longitude
            ),
        )
        morning = [pin]
        afternoon = ordered[:2]
        evening = ordered[2:4]
        leftover = ordered[4:]

        def _stop(item: SavedLocation) -> dict:
            distance_km = round(
                haversine_km(pin.latitude, pin.longitude, item.latitude, item.longitude),
                1,
            )
            return {
                "pin_id": item.id,
                "name": item.name,
                "city": item.city,
                "country": item.country,
                "region": item.region,
                "latitude": item.latitude,
                "longitude": item.longitude,
                "distance_km_from_anchor": distance_km if item.id != pin.id else 0.0,
            }

        return {
            "anchor": _stop(pin),
            "morning": [_stop(item) for item in morning],
            "afternoon": [_stop(item) for item in afternoon],
            "evening": [_stop(item) for item in evening],
            "optional": [_stop(item) for item in leftover],
            "source": "nearby_saved_places",
            "message": (
                "Day outline built from your saved places near this pin. "
                "It is a suggestion scaffold, not a booked itinerary."
                if ordered
                else "No nearby saved places with coordinates yet — start with this pin alone."
            ),
        }
