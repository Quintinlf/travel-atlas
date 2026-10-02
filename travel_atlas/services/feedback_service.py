"""Persist recommendation ratings and trip journal entries; learn category weights.

Writes personalization tables only — never touches knowledge/ingest rows.
PlanningEngine remains read-only and consumes these via the repository.
"""

from __future__ import annotations

from typing import Any, Mapping

from travel_atlas.planning.learning import RATING_SCORES, apply_rating_to_weights
from travel_atlas.repository import AtlasRepository


class FeedbackService:
    def __init__(self, repository: AtlasRepository) -> None:
        self.repository = repository

    def rate(
        self,
        *,
        subject_kind: str,
        subject_id: str,
        rating: str,
        user_key: str = "local-default",
        destination_label: str | None = None,
        category: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        if rating not in RATING_SCORES:
            raise ValueError(f"Unknown rating: {rating}")
        score = RATING_SCORES[rating]
        row = self.repository.upsert_recommendation_rating(
            user_key=user_key,
            subject_kind=subject_kind,
            subject_id=subject_id,
            rating=rating,
            score=score,
            destination_label=destination_label,
            category=category,
            note=note,
        )
        if category:
            apply_rating_to_weights(self.repository, user_key, category, score)
        return row

    def list_ratings(
        self, user_key: str = "local-default", *, destination_label: str | None = None
    ) -> list[dict[str, Any]]:
        return self.repository.list_recommendation_ratings(
            user_key, destination_label=destination_label
        )

    def write_journal(
        self,
        *,
        body: str,
        user_key: str = "local-default",
        trip_id: str | None = None,
        destination_label: str | None = None,
        entry_date: str | None = None,
        day_number: int | None = None,
        enjoyed: list[str] | None = None,
        skip: list[str] | None = None,
    ) -> dict[str, Any]:
        return self.repository.save_journal_entry(
            user_key=user_key,
            body=body,
            trip_id=trip_id,
            destination_label=destination_label,
            entry_date=entry_date,
            day_number=day_number,
            enjoyed=enjoyed,
            skip=skip,
        )

    def list_journal(
        self, user_key: str = "local-default", *, destination_label: str | None = None
    ) -> list[dict[str, Any]]:
        return self.repository.list_journal_entries(
            user_key, destination_label=destination_label
        )

    def weight_multipliers(self, user_key: str = "local-default") -> dict[str, float]:
        return self.repository.get_planning_weight_multipliers(user_key)
