"""Transit stub — walking time + taxi heuristics from Haversine distance."""

from __future__ import annotations

from src_phase1.pin_repository import haversine_km

from .base import StubResult

WALK_KPH = 4.5
TAXI_BASE = 3.5
TAXI_PER_KM = 1.8


class StubTransitProvider:
    key = "transit-stub-v1"

    def route(
        self,
        *,
        from_lat: float,
        from_lng: float,
        to_lat: float,
        to_lng: float,
    ) -> StubResult:
        km = haversine_km(from_lat, from_lng, to_lat, to_lng)
        walk_min = round((km / WALK_KPH) * 60)
        taxi = round(TAXI_BASE + km * TAXI_PER_KM, 2)
        metro_hint = "Look up nearest metro/rail stop offline or when online."
        if km < 0.8:
            how = f"Walk about {walk_min} minutes ({km:.1f} km)."
        elif km < 5:
            how = (
                f"Walk ~{walk_min} min or short transit/taxi "
                f"(~${taxi} taxi estimate)."
            )
        else:
            how = (
                f"Prefer metro/rail for {km:.1f} km. "
                f"Taxi estimate ~${taxi}. Walking would be ~{walk_min} min."
            )
        return StubResult(
            provider=self.key,
            status="stub",
            payload={
                "distance_km": round(km, 2),
                "walking_minutes": walk_min,
                "taxi_estimate_usd": taxi,
                "metro_stop": metro_hint,
                "how_to_get_there": how,
            },
        )
