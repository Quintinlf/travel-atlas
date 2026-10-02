"""Offline travel pack — cache manifest contract (no full offline maps stack)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from travel_atlas.repository import AtlasRepository

from .photo_service import PhotoService
from .reservation_service import ReservationService
from .trip_service import TripPlanService


class TravelPackService:
    """Serialize a focused trip for offline use; mark stale when inputs change."""

    def __init__(
        self,
        repository: AtlasRepository,
        trip_service: TripPlanService,
        reservation_service: ReservationService | None = None,
        photo_service: PhotoService | None = None,
    ) -> None:
        self.repository = repository
        self.trip_service = trip_service
        self.reservations = reservation_service or ReservationService(repository)
        self.photos = photo_service or PhotoService(repository)

    def build_manifest(self, trip_id: str) -> dict[str, Any]:
        trip = self.trip_service.get_trip(trip_id)
        reservations = self.reservations.list_for_trip(trip_id)
        photos = self.photos.list_for_trip(trip_id)
        # Emergency / safety claims if knowledge areas exist — best-effort.
        emergency: list[dict[str, Any]] = []
        lessons: list[dict[str, Any]] = []
        with self.repository.database.connect() as conn:
            lesson_rows = conn.execute(
                """
                SELECT id, title, topic_tag, language_code, lesson_source
                FROM language_lesson
                ORDER BY created_at DESC LIMIT 20
                """
            ).fetchall()
            lessons = [dict(r) for r in lesson_rows]

        payload = {
            "trip_id": trip_id,
            "trip_name": trip.get("name"),
            "definition": trip.get("definition") or {},
            "destinations": [
                {
                    "kind": d.get("destination_kind"),
                    "label": d.get("destination_label"),
                    "day_count": d.get("day_count"),
                    "start_date": d.get("start_date") or d.get("resolved_start_date"),
                }
                for d in trip.get("destinations") or []
            ],
            "itinerary_day_count": len(trip.get("days") or []),
            "reservations": [
                {
                    "id": r["id"],
                    "kind": r["kind"],
                    "title": r["title"],
                    "status": r["status"],
                    "opens_on": r.get("opens_on"),
                    "starts_at": r.get("starts_at"),
                    "booking_url": r.get("booking_url"),
                    "notes": r.get("notes"),
                }
                for r in reservations
            ],
            "photos": [
                {
                    "id": p["id"],
                    "caption": p.get("caption"),
                    "local_path": p.get("local_path"),
                    "place_ref": p.get("place_ref"),
                    "day_number": p.get("day_number"),
                }
                for p in photos
            ],
            "language_lessons": lessons,
            "emergency": emergency,
            "packed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        digest_src = json.dumps(
            {
                "trip": trip.get("updated_at"),
                "res": [r["id"] + r["status"] for r in reservations],
                "photos": [p["id"] for p in photos],
            },
            sort_keys=True,
        )
        payload["content_hash"] = hashlib.sha256(digest_src.encode()).hexdigest()[:16]
        payload["stale"] = False
        return payload

    def is_stale(self, trip_id: str, prior_hash: str | None) -> bool:
        if not prior_hash:
            return True
        return self.build_manifest(trip_id)["content_hash"] != prior_hash
