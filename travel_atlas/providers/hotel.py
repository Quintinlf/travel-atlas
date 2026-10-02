"""Hotel search stub — external links only."""

from __future__ import annotations

from urllib.parse import quote_plus

from .base import StubResult


class StubHotelProvider:
    key = "hotel-stub-v1"

    def search(self, *, destination: str) -> StubResult:
        q = quote_plus(destination)
        return StubResult(
            provider=self.key,
            status="unavailable",
            payload={"message": "Live hotel recommendations come later."},
            links={
                "booking": f"https://www.booking.com/searchresults.html?ss={q}",
                "airbnb": f"https://www.airbnb.com/s/{q}/homes",
            },
        )
