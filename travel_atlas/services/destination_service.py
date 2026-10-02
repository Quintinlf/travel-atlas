"""Destination-first reports built from pins and Atlas knowledge."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta

from src_phase1.geo_grouping import (
    destination_label,
    destination_matches,
    normalize_uk_nation,
    top_level_destination,
)
from src_phase1.models import SavedLocation

from travel_atlas.repository import AtlasRepository

from .destination_itinerary import DestinationItineraryService
from .knowledge_service import KnowledgeService
from .language_service import LanguageService
from .notes_service import NotesService
from .pin_service import PinService
from .seasonal_context_service import SeasonalContextService


class DestinationService:
    PERSONAL_CATEGORIES = (
        "wellness_substances",
        "microbiome",
        "beliefs_spirituality",
    )

    def __init__(
        self,
        repository: AtlasRepository,
        pin_service: PinService,
        knowledge_service: KnowledgeService,
        language_service: LanguageService,
        notes_service: NotesService,
        itinerary_service: DestinationItineraryService,
        seasonal_context_service: SeasonalContextService | None = None,
    ) -> None:
        self.repository = repository
        self.pin_service = pin_service
        self.knowledge_service = knowledge_service
        self.language_service = language_service
        self.notes_service = notes_service
        self.itinerary_service = itinerary_service
        self.seasonal_context_service = seasonal_context_service

    def list_destinations(self) -> list[dict]:
        counts: Counter[tuple[str, str]] = Counter()
        for pin in self.pin_service.list_pins():
            counts[top_level_destination(pin)] += 1

        destinations = []
        for (kind, label), pin_count in counts.most_common():
            destinations.append(
                {
                    "kind": kind,
                    "label": label,
                    "display_name": destination_label(kind, label),
                    "pin_count": pin_count,
                    "planned": False,
                }
            )

        for area in self.repository.list_areas():
            if area["area_type"] not in {"country", "region"}:
                continue
            nation = normalize_uk_nation(area["name"])
            if nation:
                key: tuple[str, str] = ("uk_nation", nation)
            elif area["area_type"] == "country":
                key = ("country", area["name"])
            else:
                key = ("us_state", area["name"])
            if any(item["kind"] == key[0] and item["label"].lower() == key[1].lower() for item in destinations):
                continue
            destinations.append(
                {
                    "kind": key[0],
                    "label": key[1],
                    "display_name": destination_label(key[0], key[1]),
                    "pin_count": 0,
                    "planned": True,
                    "area_id": area["id"],
                }
            )
        return destinations

    def get_destination_report(
        self,
        *,
        destination_kind: str,
        destination_label_value: str,
        user_key: str = "local-default",
        start_date: date | None = None,
    ) -> dict:
        pins = [
            pin
            for pin in self.pin_service.list_pins()
            if destination_matches(pin, destination_kind, destination_label_value)
        ]
        grouped = self._group_pins_by_city(pins)
        area_id = self.knowledge_service.resolve_area_for_destination(
            destination_kind, destination_label_value
        )

        atlas_context = self.knowledge_service.get_destination_context(
            city=None,
            country=destination_label_value if destination_kind != "us_state" else None,
        )
        personal_claims = self.notes_service.list_personal_claims(area_id) if area_id else []
        itinerary = self.itinerary_service.build_destination_itinerary(
            destination_kind=destination_kind,
            destination_label=destination_label_value,
            start_date=start_date,
        )
        lessons = [
            self.language_service.generate_language_lesson([pin.id], user_key)[0]
            for pin in pins[:5]
        ]
        seasonal_context = None
        if start_date and self.seasonal_context_service:
            day_count = max(len(itinerary["days"]) - 1, 0)
            seasonal_context = self.seasonal_context_service.get_seasonal_context(
                area_id=area_id,
                start_date=start_date,
                end_date=start_date + timedelta(days=day_count),
            )
        return {
            "destination_kind": destination_kind,
            "destination_label": destination_label_value,
            "display_name": destination_label(destination_kind, destination_label_value),
            "pin_count": len(pins),
            "area_id": area_id,
            "pins_by_city": grouped,
            "atlas_context": atlas_context,
            "personal_claims": personal_claims,
            "itinerary": itinerary,
            "sample_lessons": lessons,
            "seasonal_context": seasonal_context,
        }

    @staticmethod
    def _group_pins_by_city(pins: list[SavedLocation]) -> dict[str, list[SavedLocation]]:
        grouped: dict[str, list[SavedLocation]] = defaultdict(list)
        for pin in pins:
            bucket = pin.city or pin.region or "Other places"
            grouped[bucket].append(pin)
        return dict(sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0].lower())))
