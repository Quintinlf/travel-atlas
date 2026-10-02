"""Restaurant search stub — external links only."""

from __future__ import annotations

from urllib.parse import quote_plus

from .base import StubResult


class StubRestaurantProvider:
    key = "restaurant-stub-v1"

    def search(self, *, destination: str, query: str = "") -> StubResult:
        q = quote_plus(f"{query} {destination}".strip())
        return StubResult(
            provider=self.key,
            status="unavailable",
            payload={"message": "Live reservations come later."},
            links={"search": f"https://www.google.com/maps/search/{q}"},
        )
