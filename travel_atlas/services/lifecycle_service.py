"""Derive trip lifecycle stage, countdown, and preparation band.

Lifecycle (per trip): idea → planning → committed → preparation →
traveling → completed → remembered.

Commitment is purchase-gated (hotel or flight reservation with status
``reserved``). Dates refine stages inside that gate (prep bands, traveling).
"""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from travel_atlas.repository import AtlasRepository

from .checklist_templates import LEGACY_STAGE_MAP, LIFECYCLE_STAGES


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def departure_from_trip(trip: Mapping[str, Any]) -> date | None:
    definition = trip.get("definition") or {}
    explicit = _parse_date(definition.get("departure_date") or definition.get("start_date"))
    if explicit:
        return explicit
    for dest in trip.get("destinations") or []:
        d = _parse_date(dest.get("start_date") or dest.get("resolved_start_date"))
        if d:
            return d
    return None


def return_from_trip(trip: Mapping[str, Any], departure: date | None) -> date | None:
    definition = trip.get("definition") or {}
    explicit = _parse_date(definition.get("return_date") or definition.get("end_date"))
    if explicit:
        return explicit
    if departure is None:
        return None
    day_count = 0
    for dest in trip.get("destinations") or []:
        day_count += int(dest.get("day_count") or 1)
    if day_count <= 0:
        day_count = int(definition.get("day_count") or 3)
    from datetime import timedelta

    return departure + timedelta(days=max(day_count - 1, 0))


def prep_band_for_days(days_until: int | None) -> str:
    if days_until is None:
        return "any"
    if days_until <= 0:
        return "travel"
    if days_until <= 7:
        return "7"
    if days_until <= 30:
        return "30"
    if days_until <= 60:
        return "60"
    if days_until <= 90:
        return "90"
    return "any"


def normalize_stage(stage: str | None) -> str | None:
    if not stage:
        return None
    if stage in LIFECYCLE_STAGES:
        return stage
    return LEGACY_STAGE_MAP.get(stage)


class LifecycleService:
    def __init__(self, repository: AtlasRepository) -> None:
        self.repository = repository

    def resolve(
        self,
        trip: Mapping[str, Any],
        *,
        today: date | None = None,
        journal_count: int = 0,
        rating_count: int = 0,
        checklist_total: int = 0,
        checklist_done: int = 0,
        has_itinerary_stops: bool = False,
        photo_count: int = 0,
        is_committed: bool | None = None,
    ) -> dict[str, Any]:
        today = today or date.today()
        definition = dict(trip.get("definition") or {})
        override = normalize_stage(
            definition.get("stage_override") or trip.get("lifecycle_stage")
        )
        # Explicit column / override wins only when it is a manual override key.
        manual_override = normalize_stage(definition.get("stage_override"))

        departure = departure_from_trip(trip)
        ret = return_from_trip(trip, departure)

        days_until: int | None = None
        days_since_return: int | None = None
        if departure:
            days_until = (departure - today).days
        if ret:
            days_since_return = (today - ret).days

        committed_at = trip.get("committed_at")
        if is_committed is None:
            is_committed = bool(committed_at)

        if manual_override and manual_override in LIFECYCLE_STAGES:
            stage = manual_override
        elif ret and departure and departure <= today <= ret:
            stage = "traveling"
        elif days_since_return is not None and days_since_return > 0:
            # Post-trip memory arc.
            if photo_count > 0 or (journal_count + rating_count) >= 3 or (
                days_since_return > 30 and (journal_count + rating_count) >= 1
            ):
                stage = "remembered"
            else:
                stage = "completed"
        elif is_committed:
            if days_until is not None and 1 <= days_until <= 90:
                stage = "preparation"
            else:
                stage = "committed"
        elif departure is not None or has_itinerary_stops or checklist_done > 0:
            stage = "planning"
        else:
            stage = "idea"

        # Stored lifecycle_stage without manual override still informs idea→planning
        # when dates are absent but the user advanced the stage in the UI.
        if (
            not manual_override
            and stage == "idea"
            and override in ("planning", "committed", "preparation")
            and not is_committed
        ):
            stage = "planning" if override == "planning" else stage

        band = prep_band_for_days(days_until)
        if stage == "traveling":
            band = "travel"
        elif stage in ("idea", "planning") and not is_committed:
            # Prep checklist still useful while planning, but bands stay soft.
            if days_until is None:
                band = "any"

        prep_score = 0.0
        if checklist_total > 0:
            prep_score = round(100.0 * checklist_done / checklist_total, 1)

        return {
            "stage": stage,
            "stages": list(LIFECYCLE_STAGES),
            "days_until": days_until,
            "days_since_return": days_since_return,
            "departure_date": departure.isoformat() if departure else None,
            "return_date": ret.isoformat() if ret else None,
            "prep_band": band,
            "prep_score": prep_score,
            "trip_id": trip.get("id"),
            "trip_name": trip.get("name"),
            "is_committed": bool(is_committed),
            "committed_at": committed_at,
        }

    def primary_destination(self, trip: Mapping[str, Any]) -> tuple[str, str]:
        dests = trip.get("destinations") or []
        if not dests:
            return "country", "Unknown"
        first = dests[0]
        return (
            str(first.get("destination_kind") or first.get("kind") or "country"),
            str(first.get("destination_label") or first.get("label") or "Unknown"),
        )

    def persist_stage(self, trip_id: str, stage: str) -> None:
        stage = normalize_stage(stage) or stage
        if stage not in LIFECYCLE_STAGES:
            raise ValueError(f"Unknown lifecycle stage: {stage}")
        with self.repository.database.connect() as conn:
            conn.execute(
                """
                UPDATE trip_plan
                SET lifecycle_stage = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (stage, trip_id),
            )
