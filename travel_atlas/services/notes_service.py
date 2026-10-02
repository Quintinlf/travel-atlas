"""User-authored destination notes stored as draft knowledge claims."""

from __future__ import annotations

import uuid

from travel_atlas.repository import AtlasRepository


class NotesService:
    USER_SOURCE_ID = "user-notes"

    def __init__(self, repository: AtlasRepository) -> None:
        self.repository = repository

    def list_personal_claims(self, area_id: str) -> list[dict]:
        return self.repository.list_user_claims(area_id)

    def save_personal_note(
        self,
        *,
        area_id: str,
        category_key: str,
        topic_key: str,
        title: str,
        body: str,
        season_start_month_day: str | None = None,
        season_end_month_day: str | None = None,
        season_label: str | None = None,
    ) -> dict:
        claim_id = f"user-{area_id}-{category_key}-{topic_key}"
        return self.repository.upsert_claim(
            {
                "id": claim_id,
                "area_id": area_id,
                "category_key": category_key,
                "topic_key": topic_key,
                "value": {"title": title, "body": body},
                "source_id": self.USER_SOURCE_ID,
                "confidence": "medium",
                "review_status": "draft",
                "season_start_month_day": season_start_month_day,
                "season_end_month_day": season_end_month_day,
                "season_label": season_label,
            }
        )
