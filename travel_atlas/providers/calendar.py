"""Calendar stub — OS calendar integration later."""

from __future__ import annotations

from .base import StubResult


class StubCalendarProvider:
    key = "calendar-stub-v1"

    def upcoming(self, *, days: int = 14) -> StubResult:
        return StubResult(
            provider=self.key,
            status="stub",
            payload={
                "message": "OS calendar sync is not wired yet.",
                "days": days,
                "events": [],
            },
            links={},
        )
