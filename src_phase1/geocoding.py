"""Reverse geocoding: Google Geocoding API (primary) with offline fallback."""

from __future__ import annotations

import json
import os
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Provider = Literal["google", "offline", "wishlist"]


@dataclass(frozen=True)
class GeocodeResult:
    city: str | None
    region: str | None
    country: str | None
    provider: Provider


def _google_geocode(latitude: float, longitude: float, api_key: str) -> GeocodeResult | None:
    query = urllib.parse.urlencode({"latlng": f"{latitude},{longitude}", "key": api_key})
    url = f"https://maps.googleapis.com/maps/api/geocode/json?{query}"
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None

    if payload.get("status") != "OK" or not payload.get("results"):
        return None

    components = payload["results"][0].get("address_components") or []
    city = region = country = None
    for component in components:
        types = set(component.get("types") or [])
        name = (component.get("long_name") or "").strip() or None
        if not name:
            continue
        if "locality" in types or "postal_town" in types:
            city = city or name
        elif "administrative_area_level_1" in types:
            region = name
        elif "country" in types:
            country = name
    return GeocodeResult(city=city, region=region, country=country, provider="google")


def _offline_geocode(latitude: float, longitude: float) -> GeocodeResult | None:
    try:
        import reverse_geocode
    except ImportError:
        return None

    try:
        results = reverse_geocode.search([(latitude, longitude)])
    except Exception:
        return None
    if not results:
        return None
    place = results[0]
    city = (
        (place.get("city") or place.get("state") or place.get("county") or "").strip()
        or None
    )
    region = (place.get("state") or "").strip() or None
    country = (place.get("country") or "").strip() or None
    return GeocodeResult(city=city, region=region, country=country, provider="offline")


def reverse_geocode_pin(
    latitude: float,
    longitude: float,
    *,
    api_key: str | None = None,
) -> GeocodeResult | None:
    key = (api_key or os.environ.get("GOOGLE_MAPS_API_KEY", "")).strip()
    google_result: GeocodeResult | None = None
    if key:
        google_result = _google_geocode(latitude, longitude, key)
    offline_result = _offline_geocode(latitude, longitude)

    if google_result and offline_result:
        return GeocodeResult(
            city=google_result.city or offline_result.city,
            region=google_result.region or offline_result.region,
            country=google_result.country or offline_result.country,
            provider=google_result.provider,
        )
    return google_result or offline_result


class GeocodeCache:
    """Persistent geocode cache stored in atlas.db."""

    def __init__(self, atlas_db_path: Path) -> None:
        self.path = Path(atlas_db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def get(self, pin_id: str) -> GeocodeResult | None:
        if not self.path.exists():
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT resolved_city, resolved_region, resolved_country, provider "
                "FROM geocode_cache WHERE pin_id = ?",
                (pin_id,),
            ).fetchone()
        if not row:
            return None
        return GeocodeResult(
            city=row["resolved_city"],
            region=row["resolved_region"],
            country=row["resolved_country"],
            provider=row["provider"],
        )

    def save(self, pin_id: str, result: GeocodeResult) -> None:
        if not self.path.exists():
            return
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO geocode_cache(
                    pin_id, resolved_city, resolved_region, resolved_country, provider, resolved_at
                ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(pin_id) DO UPDATE SET
                    resolved_city=excluded.resolved_city,
                    resolved_region=excluded.resolved_region,
                    resolved_country=excluded.resolved_country,
                    provider=excluded.provider,
                    resolved_at=CURRENT_TIMESTAMP
                """,
                (pin_id, result.city, result.region, result.country, result.provider),
            )
            conn.commit()

    def delete(self, pin_id: str) -> None:
        if not self.path.exists():
            return
        with self._connect() as conn:
            conn.execute("DELETE FROM geocode_cache WHERE pin_id = ?", (pin_id,))
            conn.commit()
