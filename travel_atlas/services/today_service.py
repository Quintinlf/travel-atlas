"""Compose the Today dashboard — What should I do today?

Today only appears for the currently active committed trip.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from travel_atlas.repository import AtlasRepository

from .learning_queue_service import LearningQueueService
from .lifecycle_service import LifecycleService
from .photo_service import PhotoService
from .prep_service import PrepService
from .reservation_service import ReservationService
from .trip_service import TripPlanService


class TodayService:
    def __init__(
        self,
        repository: AtlasRepository,
        trip_service: TripPlanService,
        lifecycle: LifecycleService,
        prep: PrepService,
        learning: LearningQueueService,
        reservation_service: ReservationService | None = None,
        photo_service: PhotoService | None = None,
    ) -> None:
        self.repository = repository
        self.trip_service = trip_service
        self.lifecycle = lifecycle
        self.prep = prep
        self.learning = learning
        self.reservations = reservation_service or ReservationService(repository)
        self.photos = photo_service or PhotoService(repository)

    def pick_active_trip(self, today: date | None = None) -> dict[str, Any] | None:
        """Return the active committed trip only — never a research/planning stub."""
        del today  # commitment + focus, not nearest departure
        focused = self.trip_service.get_active_focused_trip()
        if focused:
            return focused
        # Fallback: sole committed trip with active_focus unset.
        committed = self.trip_service.list_trips(kind="trip", committed_only=True)
        if len(committed) == 1:
            return self.trip_service.get_trip(committed[0]["id"])
        return None

    def build(
        self,
        *,
        trip: Mapping[str, Any] | None = None,
        today: date | None = None,
        interests: list[str] | None = None,
        user_key: str = "local-default",
    ) -> dict[str, Any]:
        today = today or date.today()
        active = trip if trip is not None else self.pick_active_trip(today)
        if active and not active.get("committed_at"):
            # Explicit trip passed but not committed — Today stays locked.
            if trip is None:
                active = None
            else:
                return {
                    "has_trip": False,
                    "message": (
                        "Today unlocks after you reserve a hotel or flight "
                        "(trip commitment)."
                    ),
                    "missions": [],
                    "requires_commitment": True,
                }
        if not active:
            return {
                "has_trip": False,
                "message": (
                    "Today is for your active committed trip. "
                    "Reserve a hotel or flight, then set Active Trip focus."
                ),
                "missions": [],
            }

        trip_id = str(active["id"])
        self.prep.seed_checklist(trip_id)
        kind, label = self.lifecycle.primary_destination(active)
        progress = self.prep.progress(trip_id, "90")  # provisional until lifecycle known
        journal = self.repository.list_journal_entries(user_key, destination_label=label)
        ratings = self.repository.list_recommendation_ratings(
            user_key, destination_label=label
        )
        photo_count = self.photos.count_for_trip(trip_id)
        life = self.lifecycle.resolve(
            active,
            today=today,
            journal_count=len(journal),
            rating_count=len(ratings),
            checklist_total=progress["total"],
            checklist_done=progress["done"],
            has_itinerary_stops=bool(active.get("days")),
            photo_count=photo_count,
            is_committed=bool(active.get("committed_at")),
        )
        progress = self.prep.progress(trip_id, life["prep_band"])
        life["prep_score"] = progress["prep_score"]

        missions = self.prep.open_missions(trip_id, life["prep_band"], limit=5)
        lesson = self.learning.today_lesson(
            destination_label=label,
            prep_band=life["prep_band"],
            interests=interests,
        )
        estimated = sum(int(m.get("minutes") or 3) for m in missions) + int(
            lesson.get("estimated_minutes") or 0
        )

        completed_keys: list[str] = []
        existing_log = self.repository.get_mission_log(trip_id, today.isoformat())
        if existing_log:
            completed_keys = list(existing_log.get("completed") or [])

        self.repository.save_mission_log(
            trip_id=trip_id,
            mission_date=today.isoformat(),
            missions=missions,
            completed=completed_keys,
            prep_score=progress["prep_score"],
        )

        days = life.get("days_until")
        headline = (
            f"{days} days until {label}"
            if days is not None and days >= 0
            else (
                f"Traveling — {label}"
                if life["stage"] == "traveling"
                else label
            )
        )

        reservation_cards = self.reservations.cards_for_trip(trip_id, today=today)
        opening_soon = self.reservations.opening_soon(trip_id, today=today)

        return {
            "has_trip": True,
            "trip_id": trip_id,
            "trip_name": active.get("name"),
            "destination_kind": kind,
            "destination_label": label,
            "lifecycle": life,
            "headline": headline,
            "missions": missions,
            "completed_mission_keys": completed_keys,
            "lesson": lesson,
            "this_week": self.prep.this_week_topics(life["prep_band"]),
            "prep_score": progress["prep_score"],
            "estimated_minutes": estimated,
            "checklist": progress["items"],
            "reservations": reservation_cards,
            "opening_soon": opening_soon,
            "photo_count": photo_count,
        }

    def complete_mission(
        self, trip_id: str, key: str, *, today: date | None = None
    ) -> dict[str, Any]:
        today = today or date.today()
        self.prep.toggle(trip_id, key, True)
        log = self.repository.get_mission_log(trip_id, today.isoformat()) or {
            "missions": [],
            "completed": [],
            "prep_score": 0,
        }
        completed = list(log.get("completed") or [])
        if key not in completed:
            completed.append(key)
        progress_items = self.repository.list_checklist_items(trip_id)
        done = sum(1 for item in progress_items if item.get("completed_at"))
        total = len(progress_items) or 1
        score = round(100.0 * done / total, 1)
        return self.repository.save_mission_log(
            trip_id=trip_id,
            mission_date=today.isoformat(),
            missions=list(log.get("missions") or []),
            completed=completed,
            prep_score=score,
        )
