"""Persisted multi-destination trip plans with optional region parents."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any, Mapping

from travel_atlas.repository import AtlasRepository

from .alaska_aurora import (
    OPENER_VERSION as ALASKA_OPENER_VERSION,
    build_stayput_itinerary,
    is_alaska_leg,
)
from .destination_itinerary import DestinationItineraryService
from .knowledge_service import KnowledgeService
from .scotland_opener import OPENER_VERSION, build_opener_itinerary, is_scotland_leg
from .seasonal_context_service import SeasonalContextService


class TripPlanService:
    def __init__(
        self,
        repository: AtlasRepository,
        itinerary_service: DestinationItineraryService,
        knowledge_service: KnowledgeService | None = None,
        seasonal_context_service: SeasonalContextService | None = None,
    ) -> None:
        self.repository = repository
        self.itinerary_service = itinerary_service
        self.knowledge_service = knowledge_service
        self.seasonal_context_service = seasonal_context_service

    def create_trip(
        self,
        *,
        name: str,
        destinations: list[dict],
        definition: Mapping[str, Any] | None = None,
        seed_prep: bool = True,
        parent_trip_id: str | None = None,
        kind: str = "trip",
        lifecycle_stage: str = "idea",
    ) -> dict:
        if kind not in ("region", "trip"):
            raise ValueError("kind must be 'region' or 'trip'")
        trip_id = str(uuid.uuid4())
        definition_dict = dict(definition or {})
        # Normalize departure/return onto definition for Command Center countdown.
        if destinations and not definition_dict.get("departure_date"):
            first_start = destinations[0].get("start_date")
            if first_start:
                definition_dict["departure_date"] = first_start
        if definition_dict.get("departure_date") and not definition_dict.get("return_date"):
            total_days = sum(int(d.get("day_count") or 1) for d in destinations) or 1
            start = date.fromisoformat(str(definition_dict["departure_date"])[:10])
            definition_dict["return_date"] = (
                start + timedelta(days=max(total_days - 1, 0))
            ).isoformat()

        if definition_dict.get("departure_date") and lifecycle_stage == "idea":
            lifecycle_stage = "planning"

        definition_json = json.dumps(definition_dict)
        with self.repository.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO trip_plan(
                    id, name, definition_json, parent_trip_id, kind,
                    lifecycle_stage, committed_at, active_focus
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, 0)
                """,
                (
                    trip_id,
                    name,
                    definition_json,
                    parent_trip_id,
                    kind,
                    lifecycle_stage,
                ),
            )
            for index, destination in enumerate(destinations):
                conn.execute(
                    """
                    INSERT INTO trip_plan_destination(
                        trip_id, destination_kind, destination_label, order_index, day_count, start_date
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trip_id,
                        destination["kind"],
                        destination["label"],
                        index,
                        destination.get("day_count", 1),
                        destination.get("start_date"),
                    ),
                )
        if seed_prep and kind == "trip":
            from .prep_service import PrepService

            PrepService(self.repository).seed_checklist(trip_id)
            from .budget_board_service import BudgetBoardService

            BudgetBoardService(self.repository).seed_from_plan(
                trip_id,
                trip_budget=(
                    float(definition_dict["budget"])
                    if definition_dict.get("budget") is not None
                    else None
                ),
                day_count=sum(int(d.get("day_count") or 1) for d in destinations) or 3,
            )
        return self.get_trip(trip_id)

    def create_region(
        self,
        *,
        name: str,
        definition: Mapping[str, Any] | None = None,
    ) -> dict:
        return self.create_trip(
            name=name,
            destinations=[],
            definition=definition,
            seed_prep=False,
            kind="region",
            lifecycle_stage="planning",
        )

    def update_definition(self, trip_id: str, definition: Mapping[str, Any]) -> dict:
        with self.repository.database.connect() as conn:
            conn.execute(
                """
                UPDATE trip_plan
                SET definition_json = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (json.dumps(dict(definition)), trip_id),
            )
        return self.get_trip(trip_id)

    def set_parent(self, trip_id: str, parent_trip_id: str | None) -> dict:
        with self.repository.database.connect() as conn:
            conn.execute(
                """
                UPDATE trip_plan
                SET parent_trip_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (parent_trip_id, trip_id),
            )
        return self.get_trip(trip_id)

    def mark_committed(self, trip_id: str, *, when: datetime | None = None) -> dict:
        stamp = (when or datetime.now(UTC)).isoformat(timespec="seconds")
        with self.repository.database.connect() as conn:
            row = conn.execute(
                "SELECT committed_at FROM trip_plan WHERE id = ?", (trip_id,)
            ).fetchone()
            if row and row["committed_at"]:
                return self.get_trip(trip_id)
            conn.execute(
                """
                UPDATE trip_plan
                SET committed_at = ?, lifecycle_stage = 'committed',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (stamp, trip_id),
            )
        return self.get_trip(trip_id)

    def set_active_focus(self, trip_id: str) -> dict:
        """Mark one trip as the Active Trip focus for Today / Command Center."""
        with self.repository.database.connect() as conn:
            conn.execute("UPDATE trip_plan SET active_focus = 0 WHERE active_focus != 0")
            conn.execute(
                """
                UPDATE trip_plan
                SET active_focus = 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (trip_id,),
            )
        return self.get_trip(trip_id)

    def clear_active_focus(self) -> None:
        with self.repository.database.connect() as conn:
            conn.execute("UPDATE trip_plan SET active_focus = 0")

    def list_trips(
        self,
        *,
        kind: str | None = None,
        parent_trip_id: str | None = None,
        committed_only: bool = False,
        include_children: bool = True,
    ) -> list[dict]:
        clauses = ["1=1"]
        params: list[Any] = []
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if parent_trip_id is not None:
            clauses.append("parent_trip_id IS ?" if parent_trip_id == "" else "parent_trip_id = ?")
            if parent_trip_id != "":
                params.append(parent_trip_id)
        if committed_only:
            clauses.append("committed_at IS NOT NULL")
        if not include_children:
            clauses.append("parent_trip_id IS NULL")
        sql = f"""
            SELECT id, name, created_at, updated_at, parent_trip_id, kind,
                   lifecycle_stage, committed_at, active_focus
            FROM trip_plan
            WHERE {' AND '.join(clauses)}
            ORDER BY active_focus DESC, updated_at DESC
        """
        with self.repository.database.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def list_child_trips(self, parent_trip_id: str) -> list[dict]:
        return self.list_trips(parent_trip_id=parent_trip_id)

    def get_active_focused_trip(self) -> dict | None:
        with self.repository.database.connect() as conn:
            row = conn.execute(
                """
                SELECT id FROM trip_plan
                WHERE active_focus = 1 AND committed_at IS NOT NULL
                ORDER BY updated_at DESC LIMIT 1
                """
            ).fetchone()
        if not row:
            return None
        return self.get_trip(row["id"])

    def get_trip(self, trip_id: str) -> dict:
        with self.repository.database.connect() as conn:
            trip = conn.execute(
                "SELECT * FROM trip_plan WHERE id = ?", (trip_id,)
            ).fetchone()
            if not trip:
                raise ValueError(f"Unknown trip: {trip_id}")
            destinations = conn.execute(
                """
                SELECT destination_kind, destination_label, order_index, day_count, start_date
                FROM trip_plan_destination
                WHERE trip_id = ?
                ORDER BY order_index
                """,
                (trip_id,),
            ).fetchall()
            children = conn.execute(
                """
                SELECT id, name, kind, lifecycle_stage, committed_at
                FROM trip_plan
                WHERE parent_trip_id = ?
                ORDER BY name
                """,
                (trip_id,),
            ).fetchall()
        trip_dict = dict(trip)
        raw_definition = trip_dict.pop("definition_json", None) or "{}"
        definition = json.loads(raw_definition) if isinstance(raw_definition, str) else dict(raw_definition or {})
        day_offset = 0
        running_date: date | None = None
        combined_days: list[dict] = []
        destinations_out: list[dict] = []
        for destination in destinations:
            destination = dict(destination)
            explicit = destination["start_date"]
            leg_start = date.fromisoformat(explicit) if explicit else running_date
            if (
                definition.get("scotland_opener") == OPENER_VERSION
                and is_scotland_leg(destination)
            ):
                pins = []
                pin_service = getattr(self.itinerary_service, "pin_service", None)
                if pin_service is not None:
                    pins = pin_service.list_pins()
                itinerary = build_opener_itinerary(
                    pins,
                    start_date=leg_start,
                    day_count=int(destination["day_count"] or 3),
                )
            elif (
                definition.get("alaska_aurora") == ALASKA_OPENER_VERSION
                and is_alaska_leg(destination)
            ):
                itinerary = build_stayput_itinerary(
                    start_date=leg_start,
                    day_count=int(destination["day_count"] or 4),
                    base_key=str(definition.get("aurora_base") or "fairbanks"),
                )
            else:
                itinerary = self.itinerary_service.build_destination_itinerary(
                    destination_kind=destination["destination_kind"],
                    destination_label=destination["destination_label"],
                    days=destination["day_count"],
                    start_date=leg_start,
                )
            area_id = None
            seasonal_context = None
            if leg_start and self.knowledge_service and self.seasonal_context_service:
                area_id = self.knowledge_service.resolve_area_for_destination(
                    destination["destination_kind"], destination["destination_label"]
                )
                seasonal_context = self.seasonal_context_service.get_seasonal_context(
                    area_id=area_id,
                    start_date=leg_start,
                    end_date=leg_start + timedelta(days=max(destination["day_count"] - 1, 0)),
                )
            for day in itinerary["days"]:
                combined_days.append(
                    {
                        **day,
                        "day": day_offset + day["day"],
                        "destination_label": destination["destination_label"],
                        "destination_kind": destination["destination_kind"],
                    }
                )
            day_offset += len(itinerary["days"])
            destinations_out.append(
                {
                    **dict(destination),
                    "resolved_start_date": leg_start.isoformat() if leg_start else None,
                    "seasonal_context": seasonal_context,
                }
            )
            if leg_start:
                running_date = leg_start + timedelta(days=destination["day_count"])
        return {
            **trip_dict,
            "definition": definition,
            "destinations": destinations_out,
            "days": combined_days,
            "children": [dict(c) for c in children],
        }

    def region_budget_rollup(self, region_trip_id: str) -> dict[str, Any]:
        """Sum budget lines across child trips of a region parent."""
        children = self.list_child_trips(region_trip_id)
        estimated = 0.0
        actual = 0.0
        lines = 0
        with self.repository.database.connect() as conn:
            for child in children:
                rows = conn.execute(
                    """
                    SELECT estimated_amount, actual_amount
                    FROM trip_budget_line WHERE trip_id = ?
                    """,
                    (child["id"],),
                ).fetchall()
                for row in rows:
                    lines += 1
                    estimated += float(row["estimated_amount"] or 0)
                    if row["actual_amount"] is not None:
                        actual += float(row["actual_amount"])
        return {
            "region_trip_id": region_trip_id,
            "child_count": len(children),
            "line_count": lines,
            "estimated_total": round(estimated, 2),
            "actual_total": round(actual, 2),
        }
