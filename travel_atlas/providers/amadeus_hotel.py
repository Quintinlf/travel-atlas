"""Amadeus Self-Service hotel list + offers (search/compare only)."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Mapping, Sequence

from .base import StubResult

_TEST_HOST = "https://test.api.amadeus.com"
_PROD_HOST = "https://api.amadeus.com"
_HOTEL_IDS_CHUNK = 20


class AmadeusHotelProvider:
    """OAuth client-credentials hotel search via Amadeus Self-Service APIs."""

    key = "amadeus-hotel-v1"

    def __init__(
        self,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
        env: str | None = None,
    ) -> None:
        self.client_id = (client_id or os.environ.get("AMADEUS_CLIENT_ID") or "").strip()
        self.client_secret = (
            client_secret or os.environ.get("AMADEUS_CLIENT_SECRET") or ""
        ).strip()
        raw_env = (env or os.environ.get("AMADEUS_ENV") or "test").strip().casefold()
        self.env = "production" if raw_env in {"production", "prod", "live"} else "test"
        self.base_url = _PROD_HOST if self.env == "production" else _TEST_HOST
        self._token: str | None = None
        self._token_expires_at = 0.0

    def credentials_configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def search(
        self,
        *,
        destination: str,
        check_in: str | None = None,
        check_out: str | None = None,
    ) -> StubResult:
        """HotelProvider-compatible stub entry (city name only). Prefer search_by_geocode."""
        _ = destination
        if not self.credentials_configured():
            return StubResult(
                provider=self.key,
                status="unavailable",
                payload={
                    "message": (
                        "Set AMADEUS_CLIENT_ID and AMADEUS_CLIENT_SECRET "
                        "(Amadeus Self-Service)."
                    )
                },
            )
        if not check_in or not check_out:
            return StubResult(
                provider=self.key,
                status="unavailable",
                payload={"message": "check_in and check_out are required (YYYY-MM-DD)."},
            )
        return StubResult(
            provider=self.key,
            status="stub",
            payload={
                "message": "Use search_by_geocode for Edinburgh Old Town radius search.",
                "check_in": check_in,
                "check_out": check_out,
            },
        )

    def search_by_geocode(
        self,
        *,
        latitude: float,
        longitude: float,
        check_in: str,
        check_out: str,
        radius_km: float = 1.0,
        adults: int = 1,
        currency: str = "GBP",
    ) -> StubResult:
        if not self.credentials_configured():
            return StubResult(
                provider=self.key,
                status="unavailable",
                payload={
                    "message": (
                        "Set AMADEUS_CLIENT_ID and AMADEUS_CLIENT_SECRET "
                        "(Amadeus Self-Service)."
                    )
                },
            )
        try:
            hotels = self.list_hotels_by_geocode(
                latitude=latitude,
                longitude=longitude,
                radius_km=radius_km,
            )
            hotel_ids = [
                str(h.get("hotelId") or h.get("hotel_id") or "")
                for h in hotels
                if h.get("hotelId") or h.get("hotel_id")
            ]
            offers = self.hotel_offers(
                hotel_ids=hotel_ids,
                check_in=check_in,
                check_out=check_out,
                adults=adults,
                currency=currency,
            )
        except Exception as exc:  # noqa: BLE001
            return StubResult(
                provider=self.key,
                status="unavailable",
                payload={"message": f"Amadeus hotel search failed: {exc}"},
            )
        return StubResult(
            provider=self.key,
            status="ok",
            payload={
                "message": "Amadeus hotel list + offers.",
                "env": self.env,
                "hotels": hotels,
                "offers": offers,
                "check_in": check_in,
                "check_out": check_out,
                "currency": currency,
            },
        )

    def list_hotels_by_geocode(
        self,
        *,
        latitude: float,
        longitude: float,
        radius_km: float = 1.0,
        radius_unit: str = "KM",
    ) -> list[dict[str, Any]]:
        query = urllib.parse.urlencode(
            {
                "latitude": latitude,
                "longitude": longitude,
                "radius": max(1, int(round(radius_km))),
                "radiusUnit": radius_unit,
            }
        )
        path = f"/v1/reference-data/locations/hotels/by-geocode?{query}"
        payload = self._get_json(path)
        data = payload.get("data") or []
        return [dict(item) for item in data if isinstance(item, Mapping)]

    def hotel_offers(
        self,
        *,
        hotel_ids: Sequence[str],
        check_in: str,
        check_out: str,
        adults: int = 1,
        currency: str = "GBP",
    ) -> list[dict[str, Any]]:
        cleaned = [hid.strip() for hid in hotel_ids if hid and str(hid).strip()]
        if not cleaned:
            return []
        out: list[dict[str, Any]] = []
        for start in range(0, len(cleaned), _HOTEL_IDS_CHUNK):
            chunk = cleaned[start : start + _HOTEL_IDS_CHUNK]
            query = urllib.parse.urlencode(
                {
                    "hotelIds": ",".join(chunk),
                    "checkInDate": check_in,
                    "checkOutDate": check_out,
                    "adults": adults,
                    "currency": currency,
                    "bestRateOnly": "true",
                }
            )
            path = f"/v3/shopping/hotel-offers?{query}"
            try:
                payload = self._get_json(path)
            except Exception:
                # Some chunks return 400 when no offers exist — skip quietly.
                continue
            data = payload.get("data") or []
            out.extend(dict(item) for item in data if isinstance(item, Mapping))
        return out

    def _ensure_token(self) -> str:
        now = time.time()
        if self._token and now < self._token_expires_at - 30:
            return self._token
        body = urllib.parse.urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/v1/security/oauth2/token",
            data=body,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        token = str(payload.get("access_token") or "")
        if not token:
            raise RuntimeError("Amadeus OAuth response missing access_token")
        expires_in = float(payload.get("expires_in") or 1799)
        self._token = token
        self._token_expires_at = now + expires_in
        return token

    def _get_json(self, path: str) -> dict[str, Any]:
        token = self._ensure_token()
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            method="GET",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Amadeus HTTP {exc.code}: {detail[:400]}") from exc
