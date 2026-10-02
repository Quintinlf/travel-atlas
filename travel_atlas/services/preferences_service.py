"""Persistent traveler preferences used to rank, never rewrite, user content."""

from __future__ import annotations

from typing import Any, Mapping

from travel_atlas.repository import AtlasRepository


class PreferencesService:
    def __init__(self, repository: AtlasRepository) -> None:
        self.repository = repository

    def get_preferences(self, user_key: str = "local-default") -> dict[str, Any]:
        return self.repository.get_profile(user_key)

    def update_preferences(
        self,
        interests: list[str],
        travel_style: str,
        accommodation_preferences: Mapping[str, Any],
        learning_goals: list[str],
        user_key: str = "local-default",
        preferences: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.repository.save_profile(
            user_key,
            sorted(set(interests)),
            travel_style,
            accommodation_preferences,
            sorted(set(learning_goals)),
            preferences,
        )

    def merge_preference_bag(
        self,
        preferences: Mapping[str, Any],
        user_key: str = "local-default",
    ) -> dict[str, Any]:
        """Merge expandable preference keys without a schema rewrite."""
        return self.repository.merge_preferences(user_key, preferences)
