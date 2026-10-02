"""Translation / phrase stub — offline phrase catalogs."""

from __future__ import annotations

from travel_atlas.services.taxonomy import GENERIC_PHRASE_CATALOG, PHRASE_CATALOG

from .base import StubResult


class StubTranslationProvider:
    key = "translation-stub-v1"

    def phrases(self, *, topic: str, language_hint: str = "") -> StubResult:
        catalog = PHRASE_CATALOG if language_hint.lower() in {"ja", "japanese", "japan"} else GENERIC_PHRASE_CATALOG
        key = topic if topic in catalog else "general_travel"
        if key not in catalog:
            key = next(iter(catalog))
        phrases = catalog.get(key) or catalog.get("general_travel") or []
        return StubResult(
            provider=self.key,
            status="ok",
            payload={
                "topic": key,
                "phrases": list(phrases)[:8],
                "language_hint": language_hint or "generic",
                "estimated_minutes": 10,
            },
        )
