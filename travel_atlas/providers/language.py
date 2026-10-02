"""Language scheduler stub — locality-first lesson signals."""

from __future__ import annotations

from .base import StubResult


class StubLanguageProvider:
    key = "language-stub-v1"

    def next_lesson(
        self,
        *,
        destination: str,
        locality: str | None = None,
        interests: list[str] | None = None,
    ) -> StubResult:
        focus = locality or destination
        return StubResult(
            provider=self.key,
            status="stub",
            payload={
                "message": "Atlas schedules; connect an external LanguageProvider to teach.",
                "focus": focus,
                "locality_first": bool(locality),
                "suggested_title": f"Lesson for {focus}",
                "interests": list(interests or []),
            },
            links={},
        )
