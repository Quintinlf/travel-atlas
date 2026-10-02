"""Progressive learning queue tied to preparation band and destination."""

from __future__ import annotations

from typing import Any, Mapping

from travel_atlas.repository import AtlasRepository


_BAND_TOPICS: dict[str, list[tuple[str, str]]] = {
    "90": [
        ("general_travel", "Basic phrases"),
        ("market_food", "Food words"),
        ("transport", "Getting around"),
    ],
    "60": [
        ("market_food", "Convenience stores & markets"),
        ("transport", "Train etiquette"),
        ("temple_spirituality", "Temple / shrine manners"),
    ],
    "30": [
        ("museum_history", "Museum phrases"),
        ("market_food", "Ordering food"),
        ("transport", "Transit tickets"),
    ],
    "7": [
        ("general_travel", "Final phrase review"),
        ("transport", "Airport / station phrases"),
        ("market_food", "Emergency food phrases"),
    ],
    "travel": [
        ("general_travel", "Today's useful phrases"),
        ("market_food", "Lunch phrases"),
    ],
    "any": [
        ("general_travel", "Starter phrases"),
        ("market_food", "Food words"),
    ],
}


class LearningQueueService:
    def __init__(
        self,
        repository: AtlasRepository,
        translation: Any | None = None,
    ) -> None:
        self.repository = repository
        if translation is None:
            from travel_atlas.providers.translation import StubTranslationProvider

            translation = StubTranslationProvider()
        self.translation = translation

    def today_lesson(
        self,
        *,
        destination_label: str,
        prep_band: str,
        interests: list[str] | None = None,
        language_hint: str = "",
    ) -> dict[str, Any]:
        hint = language_hint
        if not hint and "japan" in destination_label.lower():
            hint = "japanese"
        topics = list(_BAND_TOPICS.get(prep_band) or _BAND_TOPICS["any"])
        # Prefer interest-aligned topic first.
        interests_l = {i.lower() for i in (interests or [])}
        if "market_food" in interests_l or "food" in interests_l:
            topics.sort(key=lambda t: 0 if t[0] == "market_food" else 1)
        elif "museum_history" in interests_l:
            topics.sort(key=lambda t: 0 if t[0] == "museum_history" else 1)

        primary_topic, primary_title = topics[0]
        result = self.translation.phrases(topic=primary_topic, language_hint=hint)
        phrases = list(result.payload.get("phrases") or [])[:8]

        atlas_bits: list[str] = []
        # Light Atlas claim titles for cultural context (reviewed only).
        for area in self.repository.list_areas():
            if area.get("name", "").lower() == destination_label.lower():
                for claim in self.repository.list_claims(area["id"]):
                    if claim.get("review_status") != "reviewed":
                        continue
                    value = claim.get("value") or {}
                    title = value.get("title") if isinstance(value, dict) else None
                    if title:
                        atlas_bits.append(str(title))
                    if len(atlas_bits) >= 2:
                        break
                break

        items = [f"{len(phrases)} phrases — {primary_title}"]
        if prep_band in {"60", "90"} and "japan" in destination_label.lower():
            items.append("Convenience stores")
            items.append("Train etiquette")
        for bit in atlas_bits[:1]:
            items.append(f"Atlas note: {bit}")

        return {
            "title": "Today's Lesson",
            "destination": destination_label,
            "prep_band": prep_band,
            "items": items[:4],
            "phrases": phrases,
            "estimated_minutes": int(result.payload.get("estimated_minutes") or 10),
            "provider_status": result.status,
        }
