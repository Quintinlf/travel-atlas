"""Location resolution and evidence-backed Atlas context retrieval."""

from __future__ import annotations

import re
from collections import defaultdict

from src_phase1.models import SavedLocation
from src_phase1.pin_repository import haversine_km

from travel_atlas.repository import AtlasRepository

from .types import AreaResolution

_COUNTRY_ALIASES = {
    "uk": "united kingdom",
    "u.k.": "united kingdom",
    "usa": "united states",
    "u.s.a.": "united states",
}

_AREA_SPECIFICITY = {"country": 1, "region": 2, "city": 3}


class KnowledgeService:
    def __init__(self, repository: AtlasRepository) -> None:
        self.repository = repository

    def resolve_pin(self, pin: SavedLocation) -> AreaResolution:
        if pin.city:
            city = self.repository.find_area_by_name(pin.city, "city")
            if city:
                return self._resolution(city, "exact_city", 1.0)
        if pin.latitude != 0 or pin.longitude != 0:
            nearest = self._nearest_area(pin.latitude, pin.longitude)
            if nearest:
                return self._resolution(nearest[0], "coordinate_proximity", nearest[1])
        if pin.country:
            country = self.repository.find_area_by_name(self._normalize_country(pin.country), "country")
            if country:
                return self._resolution(country, "country_fallback", 0.7)
        name_match = self._match_area_in_text(pin.name)
        if name_match:
            return self._resolution(name_match, "name_match", 0.6)
        return AreaResolution(None, None, None, "unresolved", 0.0, "uncovered")

    def _match_area_in_text(self, text: str) -> dict | None:
        """Match a known Atlas area name appearing as a whole word in the pin name.

        Saved-list CSV exports usually lack coordinates and city fields, so the
        place title (e.g. "Tokyo Tower", "Japan rail pass office") is often the
        only location signal available offline.
        """
        if not text:
            return None
        lowered = text.lower()
        best: dict | None = None
        for area in self.repository.list_areas():
            pattern = r"\b" + re.escape(area["name"].lower()) + r"\b"
            if re.search(pattern, lowered):
                # Prefer the most specific area type (city over country).
                if best is None or _AREA_SPECIFICITY[area["area_type"]] > _AREA_SPECIFICITY[best["area_type"]]:
                    best = area
        return best

    def resolve_area_for_destination(
        self, destination_kind: str, destination_label: str
    ) -> str | None:
        area = self.repository.find_area_by_name(destination_label, "country")
        if area is None and destination_kind == "us_state":
            area = self.repository.find_area_by_name(destination_label, "region")
        return area["id"] if area else None

    def get_destination_context(self, city: str | None, country: str | None = None) -> dict:
        probe = SavedLocation(
            id="context-probe", name=city or country or "Unknown", latitude=0, longitude=0,
            list_name="context", source_type="context", source_file="context", raw_json="{}",
            city=city, country=country,
        )
        return self.get_context_for_pin(probe)

    def get_context_for_pin(self, pin: SavedLocation) -> dict:
        resolution = self.resolve_pin(pin)
        if not resolution.area_id:
            return {
                "resolution": resolution,
                "claims_by_category": {},
                "coverage": [],
                "related_concepts": [],
            }
        coverage = self.repository.get_coverage(resolution.area_id)
        if not coverage:
            coverage = self.repository.recompute_coverage(resolution.area_id)
        grouped: dict[str, list[dict]] = defaultdict(list)
        related_concepts: list[str] = []
        for claim in self.repository.list_claims(resolution.area_id):
            grouped[claim["category_name"]].append(claim)
            related_concepts.extend([claim["topic_name"], claim["category_name"]])
        return {
            "resolution": resolution,
            "claims_by_category": dict(grouped),
            "coverage": coverage,
            "related_concepts": sorted(set(related_concepts)),
        }

    def _nearest_area(self, latitude: float, longitude: float) -> tuple[dict, float] | None:
        candidates = [
            area
            for area in self.repository.list_areas()
            if area["area_type"] in {"city", "region"}
            and area["latitude"] is not None
            and area["longitude"] is not None
        ]
        if not candidates:
            return None
        closest = min(
            candidates,
            key=lambda area: haversine_km(latitude, longitude, area["latitude"], area["longitude"]),
        )
        distance = haversine_km(latitude, longitude, closest["latitude"], closest["longitude"])
        if distance > 75:
            return None
        return closest, max(0.3, 1 - distance / 75)

    @staticmethod
    def _normalize_country(country: str) -> str:
        normalized = country.strip().lower()
        return _COUNTRY_ALIASES.get(normalized, normalized)

    @staticmethod
    def _resolution(area: dict, method: str, confidence: float) -> AreaResolution:
        return AreaResolution(
            area_id=area["id"],
            area_name=area["name"],
            area_type=area["area_type"],
            method=method,
            confidence=confidence,
            context_status="atlas_knowledge",
        )
