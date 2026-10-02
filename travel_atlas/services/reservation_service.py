"""First-class reservations — not buried under logistics."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from travel_atlas.repository import AtlasRepository

RESERVATION_KINDS = (
    "flight",
    "hotel",
    "museum",
    "train",
    "restaurant",
    "event",
    "tour",
    "other",
)

RESERVATION_STATUSES = (
    "not_available",
    "available_soon",
    "book_now",
    "reserved",
    "completed",
    "cancelled",
)

# Hotel or flight purchase commits the trip.
COMMITMENT_KINDS = frozenset({"flight", "hotel"})


class ReservationService:
    def __init__(self, repository: AtlasRepository) -> None:
        self.repository = repository

    def create(
        self,
        trip_id: str,
        *,
        kind: str,
        title: str,
        status: str = "not_available",
        place_ref: str | None = None,
        opens_on: str | None = None,
        starts_at: str | None = None,
        ends_at: str | None = None,
        notify_at: str | None = None,
        booking_url: str | None = None,
        external_ref: str | None = None,
        notes: str | None = None,
        cost: float | None = None,
        itinerary_day: int | None = None,
    ) -> dict[str, Any]:
        if kind not in RESERVATION_KINDS:
            raise ValueError(f"Unknown reservation kind: {kind}")
        if status not in RESERVATION_STATUSES:
            raise ValueError(f"Unknown reservation status: {status}")
        res_id = str(uuid.uuid4())
        with self.repository.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO reservation(
                    id, trip_id, kind, title, place_ref, status,
                    opens_on, starts_at, ends_at, notify_at, booking_url,
                    external_ref, notes, cost, itinerary_day
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    res_id,
                    trip_id,
                    kind,
                    title,
                    place_ref,
                    status,
                    opens_on,
                    starts_at,
                    ends_at,
                    notify_at,
                    booking_url,
                    external_ref,
                    notes,
                    cost,
                    itinerary_day,
                ),
            )
        reservation = self.get(res_id)
        if status == "reserved" and kind in COMMITMENT_KINDS:
            self._apply_commitment(trip_id)
        return reservation

    def get(self, reservation_id: str) -> dict[str, Any]:
        with self.repository.database.connect() as conn:
            row = conn.execute(
                "SELECT * FROM reservation WHERE id = ?", (reservation_id,)
            ).fetchone()
        if not row:
            raise ValueError(f"Unknown reservation: {reservation_id}")
        return dict(row)

    def list_for_trip(self, trip_id: str) -> list[dict[str, Any]]:
        with self.repository.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM reservation
                WHERE trip_id = ?
                ORDER BY
                    CASE status
                        WHEN 'book_now' THEN 0
                        WHEN 'available_soon' THEN 1
                        WHEN 'reserved' THEN 2
                        WHEN 'not_available' THEN 3
                        WHEN 'completed' THEN 4
                        ELSE 5
                    END,
                    CASE WHEN opens_on IS NULL THEN 1 ELSE 0 END,
                    opens_on ASC,
                    title
                """,
                (trip_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def set_status(self, reservation_id: str, status: str) -> dict[str, Any]:
        if status not in RESERVATION_STATUSES:
            raise ValueError(f"Unknown reservation status: {status}")
        with self.repository.database.connect() as conn:
            conn.execute(
                """
                UPDATE reservation
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, reservation_id),
            )
            row = conn.execute(
                "SELECT trip_id, kind FROM reservation WHERE id = ?",
                (reservation_id,),
            ).fetchone()
        if not row:
            raise ValueError(f"Unknown reservation: {reservation_id}")
        if status == "reserved" and row["kind"] in COMMITMENT_KINDS:
            self._apply_commitment(row["trip_id"])
        return self.get(reservation_id)

    def mark_reserved(self, reservation_id: str) -> dict[str, Any]:
        return self.set_status(reservation_id, "reserved")

    def schedule_notify(
        self, reservation_id: str, notify_at: str | None = None
    ) -> dict[str, Any]:
        reservation = self.get(reservation_id)
        if notify_at is None and reservation.get("opens_on"):
            # Default: notify the day before opens_on.
            opens = date.fromisoformat(str(reservation["opens_on"])[:10])
            notify_at = (opens - timedelta(days=1)).isoformat()
        with self.repository.database.connect() as conn:
            conn.execute(
                """
                UPDATE reservation
                SET notify_at = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (notify_at, reservation_id),
            )
        return self.get(reservation_id)

    def opening_soon(
        self, trip_id: str, *, within_days: int = 14, today: date | None = None
    ) -> list[dict[str, Any]]:
        today = today or date.today()
        end = today + timedelta(days=within_days)
        results = []
        for res in self.list_for_trip(trip_id):
            if res["status"] in ("reserved", "completed", "cancelled"):
                continue
            opens = res.get("opens_on")
            if not opens:
                continue
            try:
                opens_d = date.fromisoformat(str(opens)[:10])
            except ValueError:
                continue
            if today <= opens_d <= end:
                days = (opens_d - today).days
                results.append(
                    {
                        **res,
                        "days_until_open": days,
                        "headline": (
                            f"Opens tomorrow"
                            if days == 1
                            else (
                                f"Opens today"
                                if days == 0
                                else f"Opens in {days} days"
                            )
                        ),
                    }
                )
        return results

    def cards_for_trip(
        self, trip_id: str, *, today: date | None = None
    ) -> list[dict[str, Any]]:
        """UI-friendly reservation cards with action hints."""
        today = today or date.today()
        cards = []
        for res in self.list_for_trip(trip_id):
            opens = res.get("opens_on")
            days_until_open: int | None = None
            if opens:
                try:
                    days_until_open = (
                        date.fromisoformat(str(opens)[:10]) - today
                    ).days
                except ValueError:
                    days_until_open = None
            status = res["status"]
            if status == "reserved":
                action = "Already Reserved"
            elif status == "book_now":
                action = "Reserve"
            elif status == "available_soon" and days_until_open is not None:
                action = f"Opens in {days_until_open} days"
            elif status == "not_available":
                action = "Not Available"
            else:
                action = status.replace("_", " ").title()
            cards.append(
                {
                    **res,
                    "days_until_open": days_until_open,
                    "action_label": action,
                    "can_notify": status in ("available_soon", "not_available", "book_now")
                    and not res.get("notify_at"),
                    "commits_trip": res["kind"] in COMMITMENT_KINDS,
                }
            )
        return cards

    def trip_has_commitment(self, trip_id: str) -> bool:
        with self.repository.database.connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM reservation
                WHERE trip_id = ?
                  AND kind IN ('flight', 'hotel')
                  AND status = 'reserved'
                LIMIT 1
                """,
                (trip_id,),
            ).fetchone()
        return row is not None

    def _apply_commitment(self, trip_id: str) -> None:
        with self.repository.database.connect() as conn:
            row = conn.execute(
                "SELECT committed_at FROM trip_plan WHERE id = ?", (trip_id,)
            ).fetchone()
            if row and row["committed_at"]:
                return
            stamp = datetime.now(UTC).isoformat(timespec="seconds")
            conn.execute(
                """
                UPDATE trip_plan
                SET committed_at = ?, lifecycle_stage = 'committed',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (stamp, trip_id),
            )
            # Auto-focus if nothing else is focused.
            focused = conn.execute(
                "SELECT 1 FROM trip_plan WHERE active_focus = 1 LIMIT 1"
            ).fetchone()
            if not focused:
                conn.execute(
                    "UPDATE trip_plan SET active_focus = 1 WHERE id = ?",
                    (trip_id,),
                )
