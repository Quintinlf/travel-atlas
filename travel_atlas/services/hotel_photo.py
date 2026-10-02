"""Hotel listing photo resolution — never random city-hotel Commons hits."""

from __future__ import annotations

import os
from dataclasses import dataclass

from src_phase1 import commons_media
from src_phase1.places_api import place_photo_url


@dataclass(frozen=True)
class HotelPhoto:
    url: str
    attribution: str
    source: str  # google | commons | none


def resolve_hotel_photo(
    *,
    property_name: str | None,
    city: str,
    country: str,
    lat: float = 0.0,
    lon: float = 0.0,
) -> HotelPhoto | None:
    """Cascade D: Google (if keyed) → name-matched Commons → None (placeholder).

    Never searches bare ``\"{city} hotel\"`` without a property name.
    """
    name = (property_name or "").strip()
    if not name:
        return None

    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if api_key:
        photo = _google_places_photo(name, city=city, country=country, lat=lat, lon=lon)
        if photo:
            return photo

    # Name-matched Commons only (same bar as pin media).
    hit = commons_media.find_photo(
        name,
        lat,
        lon,
        city=city,
        country=country,
        allow_nearby=False,
        require_name_match=True,
    )
    if hit:
        return HotelPhoto(
            url=hit.thumb_url,
            attribution=hit.attribution_line(),
            source="commons",
        )
    return None


def _google_places_photo(
    name: str,
    *,
    city: str,
    country: str,
    lat: float,
    lon: float,
) -> HotelPhoto | None:
    import json
    import urllib.error
    import urllib.request

    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if not api_key:
        return None
    query = f"{name} hotel {city} {country}".strip()
    payload: dict = {"textQuery": query, "maxResultCount": 1}
    if lat or lon:
        payload["locationBias"] = {
            "circle": {
                "center": {"latitude": lat, "longitude": lon},
                "radius": 15000.0,
            }
        }
    request = urllib.request.Request(
        "https://places.googleapis.com/v1/places:searchText",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "places.id,places.photos.name,places.displayName",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    places = body.get("places") or []
    if not places:
        return None
    photos = places[0].get("photos") or []
    photo_name = photos[0].get("name") if photos else None
    if not photo_name:
        return None
    url = place_photo_url(photo_name, max_width=800)
    if not url:
        return None
    return HotelPhoto(url=url, attribution="Google", source="google")
