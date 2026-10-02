"""Reservation availability stub — opens_on stays manual for now."""

from __future__ import annotations

from .base import StubResult


class StubReservationAvailabilityProvider:
    key = "reservation-availability-stub-v1"

    def check(self, *, title: str, kind: str, on_date: str | None = None) -> StubResult:
        return StubResult(
            provider=self.key,
            status="stub",
            payload={
                "message": "Availability scrapers/APIs not wired — set opens_on manually.",
                "title": title,
                "kind": kind,
                "on_date": on_date,
                "status": "unknown",
            },
            links={},
        )
