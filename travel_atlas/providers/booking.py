"""Deep-link hotel compare + simulated booking helpers (no payments)."""

from __future__ import annotations

from urllib.parse import quote_plus

from .base import StubResult


class StubBookingProvider:
    key = "booking-stub-v1"

    def search(
        self,
        *,
        destination: str,
        kind: str = "hotel",
        check_in: str | None = None,
        check_out: str | None = None,
        extras: str = "",
    ) -> StubResult:
        q = quote_plus(destination)
        extra = quote_plus(" bidet") if extras else ""
        date_q = ""
        if check_in and check_out:
            date_q = f"&checkin={check_in}&checkout={check_out}"
        links = {
            "booking": f"https://www.booking.com/searchresults.html?ss={q}{extra}{date_q}",
            "expedia": f"https://www.expedia.com/Hotel-Search?destination={q}{extra}",
            "hotels_com": f"https://www.hotels.com/Hotel-Search?destination={q}{extra}",
            "airbnb": f"https://www.airbnb.com/s/{q}{extra}/homes",
            "google_hotels": f"https://www.google.com/travel/hotels/{q}{extra}",
        }
        if kind == "flight":
            links = {
                "google_flights": f"https://www.google.com/travel/flights?q=Flights%20to%20{q}",
                "kayak": f"https://www.kayak.com/flights/{q}",
            }
        return StubResult(
            provider=self.key,
            status="stub",
            payload={
                "message": (
                    "Deep-link compare only — open sites to sort by price. "
                    "Travel Atlas does not process payments; you can simulate reserved."
                ),
                "kind": kind,
                "destination": destination,
                "check_in": check_in,
                "check_out": check_out,
                "extras": extras,
                "sort_hint": "On each site, sort by price (lowest first) to find the cheapest."
                + (" Filter for bidet / washlet." if extras else ""),
            },
            links=links,
        )
