"""Shopping provider stub — deferred; protocol kept for extension."""

from __future__ import annotations

from .base import StubResult


class StubShoppingProvider:
    key = "shopping-stub-v1"

    def recommendations(
        self, *, destination: str, interests: list[str] | None = None
    ) -> StubResult:
        return StubResult(
            provider=self.key,
            status="unavailable",
            payload={
                "message": "Shopping / bring-home recommendations deferred.",
                "destination": destination,
                "interests": list(interests or []),
                "items": [],
            },
            links={},
        )
