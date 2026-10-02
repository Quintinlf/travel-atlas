"""Flight fare helpers for UI (Aviasales Data API)."""

from __future__ import annotations

from datetime import date
from typing import Any

from travel_atlas.providers.aviasales_flight import (
    AviasalesFlightProvider,
    aviasales_search_url,
    google_flights_roundtrip_url,
    kayak_roundtrip_url,
)


def _enrich_fares(fares: list[dict[str, Any]], *, adults: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in fares:
        per_adult = float(row.get("price_per_adult") or row.get("price") or 0)
        enriched = dict(row)
        enriched["price_per_adult"] = round(per_adult, 2)
        enriched["total_for_party"] = round(per_adult * max(1, adults), 2)
        out.append(enriched)
    return out


def search_roundtrip_fares(
    *,
    origin: str,
    destination: str,
    depart: date,
    return_on: date,
    currency: str = "usd",
    limit: int = 10,
    adults: int = 2,
    provider: AviasalesFlightProvider | None = None,
) -> dict[str, Any]:
    """Return fare rows + compare links for a round-trip window."""
    client = provider or AviasalesFlightProvider()
    aviasales = aviasales_search_url(
        origin=origin,
        destination=destination,
        depart=depart,
        return_on=return_on,
        marker=client.partner_id,
        adults=adults,
    )
    kayak = kayak_roundtrip_url(
        origin=origin,
        destination=destination,
        depart=depart,
        return_on=return_on,
        adults=adults,
    )
    google = google_flights_roundtrip_url(
        origin=origin,
        destination=destination,
        depart=depart,
        return_on=return_on,
        adults=adults,
    )
    links = {"aviasales": aviasales, "google_flights": google, "kayak": kayak}

    if not client.credentials_configured():
        return {
            "ok": False,
            "fares": [],
            "links": links,
            "adults": adults,
            "message": (
                "Set AVIASALES_API_KEY (Travelpayouts token). "
                "Optional: AVIASALES_MY_PARTNER_ID for affiliate links."
            ),
        }

    attempts: list[tuple[str, Any]] = []
    exact = client.prices_for_dates(
        origin=origin,
        destination=destination,
        departure_at=depart.isoformat(),
        return_at=return_on.isoformat(),
        currency=currency,
        one_way=False,
        limit=limit,
        adults=adults,
    )
    attempts.append(("prices_for_dates", exact))

    fares = list((exact.payload or {}).get("fares") or [])
    source = "prices_for_dates"
    message = (exact.payload or {}).get("message") or "ok"

    if not fares:
        latest = client.get_latest_prices(
            origin=origin,
            destination=destination,
            currency=currency,
            limit=limit,
            adults=adults,
        )
        attempts.append(("get_latest_prices", latest))
        fares = list((latest.payload or {}).get("fares") or [])
        if fares:
            source = "get_latest_prices"
            message = (latest.payload or {}).get("message") or message

    if not fares:
        month = depart.strftime("%Y-%m")
        grouped = client.grouped_prices(
            origin=origin,
            destination=destination,
            month=month,
            currency=currency,
            limit=limit,
            adults=adults,
        )
        attempts.append(("grouped_prices", grouped))
        fares = list((grouped.payload or {}).get("fares") or [])
        if fares:
            source = "grouped_prices"
            message = (grouped.payload or {}).get("message") or message

    enriched = _enrich_fares(fares, adults=adults)
    last = attempts[-1][1] if attempts else exact
    if last.status != "ok" and not enriched:
        return {
            "ok": False,
            "fares": [],
            "links": {**links, **(last.links or {})},
            "adults": adults,
            "message": (last.payload or {}).get("message") or last.status,
        }

    if not enriched:
        return {
            "ok": True,
            "fares": [],
            "links": links,
            "adults": adults,
            "fare_source": None,
            "message": (
                "No cached Aviasales fares for this route — open Kayak or Google "
                f"Flights for live {adults}-adult quotes. September benchmarks are "
                "often ~$379–415 per adult (~$758–830 for 2)."
            ),
            "origin": origin.upper(),
            "destination": destination.upper(),
        }

    return {
        "ok": True,
        "fares": enriched,
        "links": {**links, **(last.links or {})},
        "message": message,
        "fare_source": source,
        "adults": adults,
        "origin": origin.upper(),
        "destination": destination.upper(),
    }
