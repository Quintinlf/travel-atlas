"""Personal notes and phrases stored in atlas.db."""

from __future__ import annotations

import uuid

from travel_atlas.repository import AtlasRepository


class AnnotationService:
    def __init__(self, repository: AtlasRepository) -> None:
        self.repository = repository

    def get_pin_note(self, pin_id: str) -> str:
        return self.repository.get_pin_annotation(pin_id)

    def save_pin_note(self, pin_id: str, note_text: str) -> None:
        self.repository.save_pin_annotation(pin_id, note_text)

    def list_custom_phrases(
        self, *, area_id: str | None = None, pin_id: str | None = None
    ) -> list[dict]:
        return self.repository.list_custom_phrases(area_id=area_id, pin_id=pin_id)

    def add_custom_phrase(
        self,
        *,
        phrase: str,
        translation: str = "",
        note: str | None = None,
        area_id: str | None = None,
        pin_id: str | None = None,
    ) -> dict:
        return self.repository.add_custom_phrase(
            id=str(uuid.uuid4()),
            area_id=area_id,
            pin_id=pin_id,
            phrase=phrase,
            translation=translation,
            note=note,
        )
