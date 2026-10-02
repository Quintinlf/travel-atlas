"""Aviasales / Travelpayouts Data API — flight prices for dates (not full Search API)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from typing import Any, Mapping

from .base import StubResult

_PRICES_URL = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
_LATEST_URL = "https://api.travelpayouts.com/aviasales/v3/get_latest_prices"
_GROUPED_URL = "https://api.travelpayouts.com/aviasales/v3/grouped_prices"


def _ddmmyy(value: date) -> str:
    return value.strftime("%d%m%y")


def parse_prices_for_dates(
    payload: Mapping[str, Any] | list[Any],
    *,
    source: str = "prices_for_dates",
) -> list[dict[str, Any]]:
    """Normalize Aviasales fare JSON into UI fare rows."""
    rows = payload
    if isinstance(payload, Mapping):
        rows = payload.get("data") or payload.get("tickets") or []
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        try:
            price = float(raw.get("price") or 0)
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        depart = str(raw.get("departure_at") or raw.get("depart_date") or "")[:10]
        ret = str(raw.get("return_at") or raw.get("return_date") or "")[:10]
        transfers = raw.get("transfers")
        if transfers is None:
            transfers = raw.get("number_of_changes")
        try:
            transfers_n = int(transfers) if transfers is not None else None
        except (TypeError, ValueError):
            transfers_n = None
        duration = raw.get("duration") or raw.get("duration_to")
        try:
            duration_min = int(duration) if duration is not None else None
        except (TypeError, ValueError):
            duration_min = None
        out.append(
            {
                "price": round(price, 2),
                "price_per_adult": round(price, 2),
                "currency": str(raw.get("currency") or "USD").upper(),
                "airline": str(raw.get("airline") or raw.get("airline_code") or ""),
                "flight_number": str(raw.get("flight_number") or ""),
                "origin": str(raw.get("origin") or raw.get("origin_airport") or ""),
                "destination": str(
                    raw.get("destination") or raw.get("destination_airport") or ""
                ),
                "departure_at": depart,
                "return_at": ret,
                "transfers": transfers_n,
                "duration_minutes": duration_min,
                "link": str(raw.get("link") or ""),
                "source": source,
            }
        )
    out.sort(key=lambda row: float(row["price"]))
    return out


def aviasales_search_url(
    *,
    origin: str,
    destination: str,
    depart: date,
    return_on: date | None,
    marker: str,
    adults: int = 2,
) -> str:
    """Deep link into Aviasales search with affiliate marker."""
    path = f"{origin.upper()}{_ddmmyy(depart)}{destination.upper()}"
    if return_on is not None:
        path += f"{_ddmmyy(return_on)}"
    path += str(max(1, adults))
    query = urllib.parse.urlencode({"marker": marker}) if marker else ""
    url = f"https://www.aviasales.com/search/{path}"
    return f"{url}?{query}" if query else url


def kayak_roundtrip_url(
    *,
    origin: str,
    destination: str,
    depart: date,
    return_on: date,
    adults: int = 2,
) -> str:
    base = (
        f"https://www.kayak.com/flights/{origin.upper()}-{destination.upper()}/"
        f"{depart.isoformat()}/{return_on.isoformat()}"
    )
    if adults > 1:
        return f"{base}/{adults}adults?sort=bestflight_a"
    return f"{base}?sort=bestflight_a"


def google_flights_roundtrip_url(
    *,
    origin: str,
    destination: str,
    depart: date,
    return_on: date,
    adults: int = 2,
) -> str:
    from urllib.parse import quote_plus

    q = quote_plus(
        f"Round trip flights from {origin} to {destination} "
        f"{depart.isoformat()} to {return_on.isoformat()} {adults} adults"
    )
    return f"https://www.google.com/travel/flights?q={q}"


class AviasalesFlightProvider:
    """Travelpayouts Data API (token + optional partner marker)."""

    key = "aviasales-flight-v1"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        partner_id: str | None = None,
        timeout_s: float = 20.0,
    ) -> None:
        if api_key is None:
            self.api_key = (os.environ.get("AVIASALES_API_KEY") or "").strip()
        else:
            self.api_key = api_key.strip()
        if partner_id is None:
            self.partner_id = (os.environ.get("AVIASALES_MY_PARTNER_ID") or "").strip()
        else:
            self.partner_id = partner_id.strip()
        self.timeout_s = timeout_s

    def credentials_configured(self) -> bool:
        return bool(self.api_key)

    def prices_for_dates(
        self,
        *,
        origin: str,
        destination: str,
        departure_at: str,
        return_at: str | None = None,
        currency: str = "usd",
        one_way: bool = False,
        limit: int = 10,
        direct: bool = False,
        adults: int = 2,
    ) -> StubResult:
        if not self.credentials_configured():
            return self._missing_credentials()
        params: dict[str, Any] = {
            "origin": origin.upper(),
            "destination": destination.upper(),
            "departure_at": departure_at,
            "currency": currency.lower(),
            "sorting": "price",
            "limit": max(1, min(int(limit), 30)),
            "one_way": "true" if one_way or not return_at else "false",
            "direct": "true" if direct else "false",
            "token": self.api_key,
        }
        if return_at and not one_way:
            params["return_at"] = return_at
        try:
            payload = self._get_json(_PRICES_URL, params)
        except Exception as exc:  # noqa: BLE001
            return StubResult(
                provider=self.key,
                status="unavailable",
                payload={"message": f"Aviasales price search failed: {exc}"},
            )
        fares = parse_prices_for_dates(payload, source="prices_for_dates")
        return self._fare_result(
            fares=fares,
            origin=origin,
            destination=destination,
            departure_at=departure_at,
            return_at=return_at,
            currency=currency,
            message="Aviasales Data API prices_for_dates.",
            adults=adults,
        )

    def get_latest_prices(
        self,
        *,
        origin: str,
        destination: str,
        currency: str = "usd",
        limit: int = 10,
        one_way: bool = False,
        adults: int = 2,
    ) -> StubResult:
        if not self.credentials_configured():
            return self._missing_credentials()
        params: dict[str, Any] = {
            "origin": origin.upper(),
            "destination": destination.upper(),
            "currency": currency.lower(),
            "limit": max(1, min(int(limit), 30)),
            "one_way": "true" if one_way else "false",
            "token": self.api_key,
        }
        try:
            payload = self._get_json(_LATEST_URL, params)
        except Exception as exc:  # noqa: BLE001
            return StubResult(
                provider=self.key,
                status="unavailable",
                payload={"message": f"Aviasales latest prices failed: {exc}"},
            )
        fares = parse_prices_for_dates(payload, source="get_latest_prices")
        return self._fare_result(
            fares=fares,
            origin=origin,
            destination=destination,
            departure_at=None,
            return_at=None,
            currency=currency,
            message="Aviasales Data API get_latest_prices.",
            adults=adults,
        )

    def grouped_prices(
        self,
        *,
        origin: str,
        destination: str,
        month: str,
        currency: str = "usd",
        grouping: str = "departure_at",
        limit: int = 10,
        adults: int = 2,
    ) -> StubResult:
        """Month-level minima, e.g. month='2026-09'."""
        if not self.credentials_configured():
            return self._missing_credentials()
        params: dict[str, Any] = {
            "origin": origin.upper(),
            "destination": destination.upper(),
            "departure_at": month,
            "grouping": grouping,
            "currency": currency.lower(),
            "limit": max(1, min(int(limit), 30)),
            "token": self.api_key,
        }
        try:
            payload = self._get_json(_GROUPED_URL, params)
        except Exception as exc:  # noqa: BLE001
            return StubResult(
                provider=self.key,
                status="unavailable",
                payload={"message": f"Aviasales grouped prices failed: {exc}"},
            )
        fares = parse_prices_for_dates(payload, source="grouped_prices")
        return self._fare_result(
            fares=fares,
            origin=origin,
            destination=destination,
            departure_at=month,
            return_at=None,
            currency=currency,
            message="Aviasales Data API grouped_prices.",
            adults=adults,
        )

    def _fare_result(
        self,
        *,
        fares: list[dict[str, Any]],
        origin: str,
        destination: str,
        departure_at: str | None,
        return_at: str | None,
        currency: str,
        message: str,
        adults: int,
    ) -> StubResult:
        depart_d = None
        return_d = None
        if departure_at and len(departure_at) >= 10:
            depart_d = date.fromisoformat(departure_at[:10])
        if return_at and len(return_at) >= 10:
            return_d = date.fromisoformat(return_at[:10])
        search_url = ""
        if depart_d is not None:
            search_url = aviasales_search_url(
                origin=origin,
                destination=destination,
                depart=depart_d,
                return_on=return_d,
                marker=self.partner_id,
                adults=adults,
            )
        return StubResult(
            provider=self.key,
            status="ok",
            payload={
                "message": message,
                "fares": fares,
                "origin": origin.upper(),
                "destination": destination.upper(),
                "departure_at": departure_at,
                "return_at": return_at,
                "currency": currency.upper(),
                "search_url": search_url,
                "partner_id": self.partner_id or None,
                "adults": adults,
            },
            links={"aviasales": search_url} if search_url else {},
        )

    def _missing_credentials(self) -> StubResult:
        return StubResult(
            provider=self.key,
            status="unavailable",
            payload={
                "message": (
                    "Set AVIASALES_API_KEY (Travelpayouts token). "
                    "Optional: AVIASALES_MY_PARTNER_ID for affiliate links."
                )
            },
        )

    def _get_json(self, url: str, params: Mapping[str, Any]) -> dict[str, Any]:
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        request = urllib.request.Request(
            f"{url}?{query}",
            method="GET",
            headers={
                "Accept": "application/json",
                "X-Access-Token": self.api_key,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Aviasales HTTP {exc.code}: {detail[:400]}") from exc
