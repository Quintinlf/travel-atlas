"""Nuitee / LiteAPI hotel rates (search/compare only)."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Mapping

from .base import StubResult

_HOST = "https://api.liteapi.travel/v3.0"

_TWO_QUEEN_RE = re.compile(
    r"(2\s*queen|two\s*queen|qq|double\s*queen|2\s*qn)",
    re.IGNORECASE,
)


def _retail_total(rate: Mapping[str, Any]) -> tuple[float, str] | None:
    retail = rate.get("retailRate") or {}
    totals = retail.get("total") or []
    if isinstance(totals, Mapping):
        totals = [totals]
    if not isinstance(totals, list) or not totals:
        return None
    first = totals[0] if isinstance(totals[0], Mapping) else {}
    try:
        amount = float(first.get("amount") or 0)
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None
    currency = str(first.get("currency") or "USD")
    return amount, currency


def _room_label(room: Mapping[str, Any], rate: Mapping[str, Any]) -> str:
    return str(rate.get("name") or room.get("name") or room.get("offerId") or "")


def _is_two_queen_room(name: str) -> bool:
    return bool(_TWO_QUEEN_RE.search(name))


def _photo_url(meta: Mapping[str, Any]) -> str | None:
    for key in ("main_photo", "mainPhoto", "thumbnail", "thumbnailUrl"):
        raw = meta.get(key)
        if raw and str(raw).startswith("http"):
            return str(raw)
    images = meta.get("hotelImages") or meta.get("images") or []
    if isinstance(images, list):
        for item in images:
            if not isinstance(item, Mapping):
                continue
            url = item.get("url") or item.get("thumbnailUrl")
            if url and str(url).startswith("http"):
                return str(url)
    return None


def _cheapest_rate(
    room_types: list[Any],
    *,
    prefer_two_queen: bool = True,
) -> tuple[dict[str, Any], float, str] | None:
    candidates: list[tuple[dict[str, Any], float, str, int]] = []
    for room in room_types:
        if not isinstance(room, Mapping):
            continue
        for rate in room.get("rates") or []:
            if not isinstance(rate, Mapping):
                continue
            parsed = _retail_total(rate)
            if parsed is None:
                continue
            amount, currency = parsed
            label = _room_label(room, rate)
            rank = 0
            if prefer_two_queen and _is_two_queen_room(label):
                rank = 2
            elif "queen" in label.casefold():
                rank = 1
            offer = {
                "id": str(rate.get("rateId") or room.get("offerId") or ""),
                "room_name": label,
                "price": {"total": amount, "currency": currency},
            }
            candidates.append((offer, amount, currency, rank))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (-item[3], item[1]))
    offer, amount, currency, _rank = candidates[0]
    return offer, amount, currency


class NuiteeHotelProvider:
    """LiteAPI hotel rates via Nuitee (X-API-Key). Sandbox keys start with sand_."""

    key = "nuitee-hotel-v1"

    def __init__(self, *, api_key: str | None = None, timeout_s: float = 45.0) -> None:
        if api_key is None:
            self.api_key = (os.environ.get("NUITEE_API_KEY") or "").strip()
        else:
            self.api_key = api_key.strip()
        self.timeout_s = timeout_s
        self.base_url = _HOST

    def credentials_configured(self) -> bool:
        return bool(self.api_key)

    def search_by_geocode(
        self,
        *,
        latitude: float,
        longitude: float,
        check_in: str,
        check_out: str,
        radius_km: float = 20.0,
        adults: int = 2,
        currency: str = "USD",
        guest_nationality: str = "US",
        limit: int = 40,
        bed_types: list[str] | None = None,
    ) -> StubResult:
        if not self.credentials_configured():
            return StubResult(
                provider=self.key,
                status="unavailable",
                payload={"message": "Set NUITEE_API_KEY (LiteAPI / Nuitee dashboard)."},
            )
        body: dict[str, Any] = {
            "latitude": float(latitude),
            "longitude": float(longitude),
            "radius": max(500, int(round(float(radius_km) * 1000))),
            "checkin": check_in,
            "checkout": check_out,
            "currency": currency,
            "guestNationality": guest_nationality,
            "occupancies": [{"adults": max(1, int(adults))}],
            "includeHotelData": True,
            "limit": limit,
        }
        if bed_types:
            body["bedTypes"] = [str(b).strip().lower() for b in bed_types if str(b).strip()]
        try:
            payload = self._post_json("/hotels/rates", body)
        except Exception as exc:  # noqa: BLE001
            return StubResult(
                provider=self.key,
                status="unavailable",
                payload={"message": f"Nuitee hotel search failed: {exc}"},
            )

        rates_rows = payload.get("data") or []
        if isinstance(rates_rows, Mapping):
            rates_rows = rates_rows.get("rates") or rates_rows.get("data") or []
        hotel_meta = {
            str(h.get("id") or h.get("hotelId") or ""): dict(h)
            for h in (payload.get("hotels") or [])
            if isinstance(h, Mapping) and (h.get("id") or h.get("hotelId"))
        }

        hotels: list[dict[str, Any]] = []
        offers: list[dict[str, Any]] = []
        for row in rates_rows:
            if not isinstance(row, Mapping):
                continue
            hotel_id = str(row.get("hotelId") or "")
            if not hotel_id:
                continue
            meta = hotel_meta.get(hotel_id) or {}
            name = str(meta.get("name") or row.get("name") or hotel_id)
            lat = meta.get("latitude") if meta else row.get("latitude")
            lon = meta.get("longitude") if meta else row.get("longitude")
            hotel = {
                "hotelId": hotel_id,
                "name": name,
                "latitude": lat,
                "longitude": lon,
                "geoCode": {"latitude": lat, "longitude": lon},
                "rating": meta.get("rating") or meta.get("starRating"),
                "main_photo": _photo_url(meta),
            }
            cheapest = _cheapest_rate(list(row.get("roomTypes") or []))
            if cheapest is None:
                continue
            offer, _amount, _currency = cheapest
            hotels.append(hotel)
            offers.append({"hotel": hotel, "offers": [offer]})

        return StubResult(
            provider=self.key,
            status="ok",
            payload={
                "message": "Nuitee / LiteAPI hotel rates.",
                "hotels": hotels,
                "offers": offers,
                "check_in": check_in,
                "check_out": check_out,
                "currency": currency,
                "adults": adults,
                "bed_types": bed_types or [],
            },
        )

    def _post_json(self, path: str, body: Mapping[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(dict(body)).encode("utf-8"),
            method="POST",
            headers={
                "X-API-Key": self.api_key,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Nuitee HTTP {exc.code}: {detail[:400]}") from exc
