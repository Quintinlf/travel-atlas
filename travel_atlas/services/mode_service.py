"""Application modes — orthogonal to per-trip lifecycle.

Modes: research | planning | active_trip | archive
"""

from __future__ import annotations

from typing import Any

from travel_atlas.repository import AtlasRepository

from .lifecycle_service import LifecycleService, normalize_stage
from .trip_service import TripPlanService

APPLICATION_MODES = (
    "research",
    "planning",
    "active_trip",
    "archive",
)

ACTIVE_LIFECYCLE = frozenset({"committed", "preparation", "traveling"})
ARCHIVE_LIFECYCLE = frozenset({"completed", "remembered"})
PLANNING_LIFECYCLE = frozenset({"idea", "planning"})


class ModeService:
    def __init__(
        self,
        repository: AtlasRepository,
        trip_service: TripPlanService,
        lifecycle: LifecycleService | None = None,
    ) -> None:
        self.repository = repository
        self.trip_service = trip_service
        self.lifecycle = lifecycle or LifecycleService(repository)

    def get_mode(self, user_key: str = "local-default") -> str:
        profile = self.repository.get_profile(user_key)
        prefs = dict(profile.get("preferences") or {})
        mode = prefs.get("app_mode")
        if mode in APPLICATION_MODES:
            return str(mode)
        return self.infer_mode(user_key=user_key)

    def set_mode(self, mode: str, user_key: str = "local-default") -> str:
        if mode not in APPLICATION_MODES:
            raise ValueError(f"Unknown application mode: {mode}")
        self.repository.merge_preferences(user_key, {"app_mode": mode})
        return mode

    def get_focused_trip_id(self, user_key: str = "local-default") -> str | None:
        profile = self.repository.get_profile(user_key)
        prefs = dict(profile.get("preferences") or {})
        focused = prefs.get("focused_trip_id")
        if focused:
            return str(focused)
        active = self.trip_service.get_active_focused_trip()
        return str(active["id"]) if active else None

    def set_focused_trip(
        self, trip_id: str | None, user_key: str = "local-default"
    ) -> None:
        self.repository.merge_preferences(
            user_key, {"focused_trip_id": trip_id}
        )
        if trip_id:
            trip = self.trip_service.get_trip(trip_id)
            if trip.get("committed_at"):
                self.trip_service.set_active_focus(trip_id)

    def infer_mode(self, user_key: str = "local-default") -> str:
        active = self.trip_service.get_active_focused_trip()
        if active:
            return "active_trip"
        trips = self.trip_service.list_trips(kind="trip")
        if any(t.get("committed_at") for t in trips):
            return "active_trip"
        if any(
            normalize_stage(t.get("lifecycle_stage")) in PLANNING_LIFECYCLE
            or not t.get("committed_at")
            for t in trips
        ) and trips:
            # Prefer planning when any non-archive trip exists without active focus.
            non_archive = [
                t
                for t in trips
                if normalize_stage(t.get("lifecycle_stage")) not in ARCHIVE_LIFECYCLE
            ]
            if non_archive:
                return "planning"
        if any(
            normalize_stage(t.get("lifecycle_stage")) in ARCHIVE_LIFECYCLE for t in trips
        ):
            return "archive"
        return "research"

    def resolve(
        self, user_key: str = "local-default"
    ) -> dict[str, Any]:
        mode = self.get_mode(user_key)
        focused_id = self.get_focused_trip_id(user_key)
        focused = None
        if focused_id:
            try:
                focused = self.trip_service.get_trip(focused_id)
            except ValueError:
                focused = None

        planning_trips = []
        active_trips = []
        archive_trips = []
        for summary in self.trip_service.list_trips(kind="trip"):
            stage = normalize_stage(summary.get("lifecycle_stage")) or "idea"
            if summary.get("committed_at") or stage in ACTIVE_LIFECYCLE:
                # Re-resolve with dates for accuracy when possible.
                try:
                    trip = self.trip_service.get_trip(summary["id"])
                    life = self.lifecycle.resolve(trip, is_committed=bool(trip.get("committed_at")))
                    stage = life["stage"]
                except ValueError:
                    pass
            if stage in ARCHIVE_LIFECYCLE:
                archive_trips.append(summary)
            elif stage in ACTIVE_LIFECYCLE or summary.get("committed_at"):
                active_trips.append(summary)
            else:
                planning_trips.append(summary)

        today_eligible = bool(
            focused
            and focused.get("committed_at")
            and (
                focused.get("active_focus")
                or (mode == "active_trip")
            )
        )
        # Today requires an active committed trip (focused or sole active_focus).
        active_focused = self.trip_service.get_active_focused_trip()
        today_eligible = active_focused is not None

        return {
            "mode": mode,
            "modes": list(APPLICATION_MODES),
            "focused_trip_id": focused_id,
            "focused_trip": focused,
            "planning_trips": planning_trips,
            "active_trips": active_trips,
            "archive_trips": archive_trips,
            "today_eligible": today_eligible,
            "default_page": (
                "today"
                if today_eligible
                else (
                    "trip-planner"
                    if mode == "planning"
                    else (
                        "destination-atlas"
                        if mode == "research"
                        else "command-center"
                    )
                )
            ),
        }

    def trips_for_mode(self, mode: str | None = None, user_key: str = "local-default") -> list[dict]:
        resolved = self.resolve(user_key)
        mode = mode or resolved["mode"]
        if mode == "planning":
            return list(resolved["planning_trips"])
        if mode == "active_trip":
            return list(resolved["active_trips"])
        if mode == "archive":
            return list(resolved["archive_trips"])
        return []
