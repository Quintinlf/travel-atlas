"""Multi-day itinerary generation for a destination."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from src_phase1.geo_grouping import destination_matches
from src_phase1.models import SavedLocation

from .itinerary_service import ItineraryService
from .pin_service import PinService


class DestinationItineraryService:
    def __init__(self, pin_service: PinService, itinerary_service: ItineraryService) -> None:
        self.pin_service = pin_service
        self.itinerary_service = itinerary_service

    def build_destination_itinerary(
        self,
        *,
        destination_kind: str,
        destination_label: str,
        days: int | None = None,
        start_date: date | None = None,
    ) -> dict:
        pins = [
            pin
            for pin in self.pin_service.list_pins()
            if destination_matches(pin, destination_kind, destination_label)
            and (pin.latitude != 0 or pin.longitude != 0)
        ]
        if not pins:
            return {
                "destination_kind": destination_kind,
                "destination_label": destination_label,
                "days": [],
                "message": "No mappable saved places in this destination yet.",
            }

        clusters = self._clusters_for_pins(pins)
        cluster_order = sorted(clusters, key=lambda item: len(item[1]), reverse=True)
        day_count = days or max(1, len(cluster_order))
        days_out: list[dict] = []
        for day_index in range(day_count):
            cluster_pins = cluster_order[day_index % len(cluster_order)][1]
            anchor = cluster_pins[0]
            day_plan = self.itinerary_service.suggest_day_plan(anchor)
            days_out.append(
                {
                    "day": day_index + 1,
                    "date": (start_date + timedelta(days=day_index)).isoformat() if start_date else None,
                    "anchor": day_plan["anchor"],
                    "morning": day_plan["morning"],
                    "afternoon": day_plan["afternoon"],
                    "evening": day_plan["evening"],
                    "optional": day_plan["optional"],
                }
            )
        return {
            "destination_kind": destination_kind,
            "destination_label": destination_label,
            "days": days_out,
            "message": (
                f"Built a {len(days_out)}-day outline from your saved places in "
                f"{destination_label}."
            ),
        }

    @staticmethod
    def _clusters_for_pins(pins: list[SavedLocation]) -> list[tuple[str, list[SavedLocation]]]:
        by_cluster: dict[str, list[SavedLocation]] = defaultdict(list)
        for pin in pins:
            key = pin.city or pin.region or pin.country or pin.name
            by_cluster[key].append(pin)
        return list(by_cluster.items())
