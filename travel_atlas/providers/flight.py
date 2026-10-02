"""Flight search stub — external links only."""

from __future__ import annotations

from urllib.parse import quote_plus

from .base import StubResult


class StubFlightProvider:
    key = "flight-stub-v1"

    def search(self, *, destination: str) -> StubResult:
        q = quote_plus(destination)
        return StubResult(
            provider=self.key,
            status="unavailable",
            payload={"message": "Live airfare monitoring comes later."},
            links={
                "google_flights": f"https://www.google.com/travel/flights?q=Flights%20to%20{q}",
            },
        )
