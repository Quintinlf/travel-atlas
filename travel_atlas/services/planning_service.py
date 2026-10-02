"""Offline planning helpers: prefilled search links and accommodation prefs.

This is intentionally not the personalized PlanningEngine. Use
``travel_atlas.planning.PlanningEngine`` for scored recommendations and
itineraries. This class only builds external search URLs.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus

from src_phase1.models import SavedLocation

from .preferences_service import PreferencesService
from .types import AreaResolution


class PlanningService:
    def __init__(self, preferences_service: PreferencesService) -> None:
        self.preferences_service = preferences_service

    def destination_label(
        self, pin: SavedLocation, resolution: AreaResolution | None = None
    ) -> str:
        if pin.city and pin.country:
            return f"{pin.city}, {pin.country}"
        if pin.city:
            return pin.city
        if pin.country:
            return pin.country
        if resolution and resolution.area_name:
            return resolution.area_name
        return pin.name

    def planning_links(
        self, pin: SavedLocation, resolution: AreaResolution | None = None
    ) -> dict[str, str]:
        """Return prefilled external search URLs. Nothing is fetched."""
        destination = self.destination_label(pin, resolution)
        query = quote_plus(destination)
        return {
            "google_flights": f"https://www.google.com/travel/flights?q=Flights%20to%20{query}",
            "booking": f"https://www.booking.com/searchresults.html?ss={query}",
            "airbnb": f"https://www.airbnb.com/s/{query}/homes",
            "destination": destination,
        }

    def accommodation_context(self, user_key: str = "local-default") -> dict[str, Any]:
        preferences = self.preferences_service.get_preferences(user_key)
        return {
            "travel_style": preferences.get("travel_style", "balanced"),
            "accommodation_preferences": preferences.get("accommodation_preferences", {}),
            "interests": preferences.get("interests", []),
        }

    def health_reference_links(
        self, pin: SavedLocation, resolution: AreaResolution | None = None
    ) -> dict[str, str]:
        """Official reference URLs for the destination country (require internet)."""
        country = pin.country or (
            resolution.area_name
            if resolution and resolution.area_type == "country"
            else None
        )
        slug = quote_plus((country or pin.name).lower().replace(" ", "-"))
        country_query = quote_plus(country or pin.name)
        return {
            "cdc": "https://wwwnc.cdc.gov/travel/destinations/list",
            "cdc_search": f"https://wwwnc.cdc.gov/travel/destinations/traveler/none/{slug}",
            "who": "https://www.who.int/health-topics/travel-and-health",
            "who_search": (
                "https://www.who.int/home/search?indexCatalogue=genericsearchindex1"
                f"&searchQuery={country_query}"
            ),
            "country": country or "unknown",
        }
