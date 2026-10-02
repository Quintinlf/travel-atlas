"""Attach actionable logistics cards to recommendations (offline stubs)."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from src_phase1.models import SavedLocation
from src_phase1.pin_repository import haversine_km

from travel_atlas.providers.transit import StubTransitProvider
from travel_atlas.services.types import Recommendation


_RESERVATION_CATEGORIES = frozenset({"museum_history", "temple_spirituality"})
_HOURS_BY_CATEGORY = {
    "museum_history": "Typically 09:00–17:00 (verify locally)",
    "market_food": "Markets often morning–early afternoon; restaurants vary",
    "nature_gardens": "Daylight hours; check seasonal closures",
    "temple_spirituality": "Often 08:00–16:00; some open later",
    "transport": "System hours vary by city",
    "general_travel": "Check locally before you go",
}


class LogisticsService:
    def __init__(self, transit: StubTransitProvider | None = None) -> None:
        self.transit = transit or StubTransitProvider()

    def enrich(
        self,
        rec: Recommendation,
        *,
        pins: Sequence[SavedLocation] = (),
        hotel_lat: float | None = None,
        hotel_lng: float | None = None,
    ) -> dict[str, Any]:
        pin = None
        pin_id = rec.source_refs.get("pin_id")
        if pin_id:
            pin = next((p for p in pins if p.id == pin_id), None)

        walking_minutes = None
        taxi_estimate = None
        how = "Add a hotel/base location or use destination transit maps."
        metro_stop = "Nearest metro/rail — look up offline when available."
        provider_status = "stub"

        origin_lat = hotel_lat
        origin_lng = hotel_lng
        if origin_lat is None and pins:
            # Use centroid of destination pins as soft base.
            coords = [(p.latitude, p.longitude) for p in pins if p.latitude or p.longitude]
            if coords:
                origin_lat = sum(c[0] for c in coords) / len(coords)
                origin_lng = sum(c[1] for c in coords) / len(coords)

        if pin and origin_lat is not None and origin_lng is not None:
            result = self.transit.route(
                from_lat=origin_lat,
                from_lng=origin_lng,
                to_lat=pin.latitude,
                to_lng=pin.longitude,
            )
            provider_status = result.status
            walking_minutes = result.payload.get("walking_minutes")
            taxi_estimate = result.payload.get("taxi_estimate_usd")
            how = result.payload.get("how_to_get_there") or how
            metro_stop = result.payload.get("metro_stop") or metro_stop

        nearby_food = self._nearby(pins, pin, {"market_food"}, limit=2)
        nearby_grocery = self._nearby(
            pins, pin, {"market_food", "shopping"}, limit=2, name_hint="market"
        )

        return {
            "title": rec.title,
            "opening_hours": _HOURS_BY_CATEGORY.get(
                rec.category, _HOURS_BY_CATEGORY["general_travel"]
            ),
            "expected_cost": rec.estimated_cost,
            "walking_minutes": walking_minutes,
            "metro_stop": metro_stop,
            "taxi_estimate": taxi_estimate,
            "needs_reservation": rec.category in _RESERVATION_CATEGORIES,
            "typical_visit_hours": rec.estimated_duration_hours,
            "nearby_food": nearby_food,
            "nearby_grocery": nearby_grocery,
            "how_to_get_there": how,
            "provider_status": provider_status,
        }

    @staticmethod
    def _nearby(
        pins: Sequence[SavedLocation],
        anchor: SavedLocation | None,
        categories: set[str],
        *,
        limit: int = 2,
        name_hint: str | None = None,
    ) -> list[str]:
        if not anchor:
            return []
        scored: list[tuple[float, str]] = []
        for pin in pins:
            if pin.id == anchor.id:
                continue
            name_l = (pin.name or "").lower()
            cat_l = (pin.category or "").lower()
            blob = f"{name_l} {cat_l}"
            match = any(
                c.replace("_", " ") in blob or c.split("_")[0] in blob for c in categories
            )
            if name_hint and name_hint in name_l:
                match = True
            if not match and "food" not in blob and "market" not in blob and "cafe" not in blob:
                continue
            if not (pin.latitude or pin.longitude):
                continue
            dist = haversine_km(
                anchor.latitude, anchor.longitude, pin.latitude, pin.longitude
            )
            scored.append((dist, pin.name))
        scored.sort(key=lambda item: item[0])
        return [name for _, name in scored[:limit]]
