"""Explainable, offline language lessons generated from saved places."""

from __future__ import annotations

from typing import Any

from src_phase1.models import SavedLocation

from travel_atlas.repository import AtlasRepository

from .knowledge_service import KnowledgeService
from .pin_service import PinService
from .taxonomy import (
    GENERIC_PHRASE_CATALOG,
    PHRASE_CATALOG,
    RELATED_CONCEPTS,
    TAG_RULES,
    TAXONOMY_VERSION,
)
from .types import Lesson


class LanguageService:
    def __init__(
        self,
        repository: AtlasRepository,
        pin_service: PinService,
        knowledge_service: KnowledgeService,
    ) -> None:
        self.repository = repository
        self.pin_service = pin_service
        self.knowledge_service = knowledge_service

    def classify_pin(self, pin: SavedLocation) -> dict[str, Any]:
        fields = {
            "name": pin.name,
            "category": pin.category or "",
            "notes": pin.notes or "",
            "list_name": pin.list_name,
            "tags": " ".join(pin.tags),
        }
        normalized = {field: value.lower() for field, value in fields.items()}
        tags: list[str] = []
        evidence: list[dict[str, str]] = []
        for tag, terms in TAG_RULES.items():
            matched = False
            for field, text in normalized.items():
                for term in terms:
                    if term in text:
                        tags.append(tag)
                        evidence.append({"tag": tag, "field": field, "term": term})
                        matched = True
                        break
                if matched:
                    break
        if not tags:
            tags = ["general_travel"]
            evidence = [{
                "tag": "general_travel",
                "field": "fallback",
                "term": "no category-specific match",
            }]
        source_hash = self.pin_service.source_hash(pin)
        return self.repository.get_or_save_classification(
            pin.id, TAXONOMY_VERSION, source_hash, sorted(set(tags)),
            0.9 if tags != ["general_travel"] else 0.4, evidence,
        )

    def generate_language_lesson(
        self, pin_ids: list[str], user_key: str = "local-default"
    ) -> list[Lesson]:
        lessons = []
        for pin_id in pin_ids:
            pin = self.pin_service.get_pin_details(pin_id)
            if pin:
                lessons.append(self._lesson_for_pin(pin, user_key))
        return lessons

    def personalized_lesson_queue(
        self, user_key: str = "local-default", limit: int = 5
    ) -> list[Lesson]:
        """Rank lesson candidates by explicit interests while preserving pin data."""
        interests = set(self.repository.get_profile(user_key)["interests"])
        candidates = []
        for pin in self.pin_service.list_pins():
            classification = self.classify_pin(pin)
            relevance = len(interests.intersection(classification["tags"]))
            candidates.append((relevance, pin.name.lower(), pin))
        candidates.sort(key=lambda item: (-item[0], item[1]))
        return [self._lesson_for_pin(pin, user_key) for _, _, pin in candidates[:limit]]

    def _lesson_for_pin(self, pin: SavedLocation, user_key: str) -> Lesson:
        classification = self.classify_pin(pin)
        topic_tag = classification["tags"][0]
        context = self.knowledge_service.get_context_for_pin(pin)
        resolution = context["resolution"]
        is_japan = resolution.area_id in {"country-jp", "city-tokyo"}
        phrases = PHRASE_CATALOG[topic_tag] if is_japan else GENERIC_PHRASE_CATALOG[topic_tag]
        language_code = "ja" if is_japan else "und"
        lesson_source = "offline_phrase_catalog_japanese" if is_japan else "generic_offline_travel_catalog"
        context_text = (
            f"At {pin.name}, saved in {pin.list_name}. "
            + (
                f"This lesson is connected to {resolution.area_name} Atlas knowledge."
                if resolution.area_id
                else "No destination-specific Atlas entry is bundled yet, so this uses generic offline travel language."
            )
        )
        explanation = {
            "classification_tags": classification["tags"],
            "matching_evidence": classification["evidence"],
            "resolution_method": resolution.method,
            "related_concepts": RELATED_CONCEPTS[topic_tag],
        }
        stored = self.repository.get_or_save_lesson(
            user_key=user_key,
            pin_id=pin.id,
            source_hash=classification["source_hash"],
            language_code=language_code,
            topic_tag=topic_tag,
            title=f"{pin.name}: useful {topic_tag.replace('_', ' ')} language",
            context_text=context_text,
            phrases=phrases,
            explanation=explanation,
            lesson_source=lesson_source,
        )
        return Lesson(
            id=stored["id"],
            pin_id=pin.id,
            title=stored["title"],
            context_text=stored["context_text"],
            phrases=stored["phrases"],
            explanation=stored["explanation"],
            lesson_source=stored["lesson_source"],
        )
