"""Google Places API (New) helpers with local caching."""

from __future__ import annotations

import json
import os
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from src_phase1 import commons_media
from src_phase1.google_place_identity import (
    MEDIA_STRATEGY_VERSION,
    extract_cid_decimal,
    extract_cid_decimal_from_pin_raw,
    resolve_place_identity,
    url_from_raw_json,
)
from src_phase1.models import SavedLocation


@dataclass(frozen=True)
class PlaceMedia:
    place_id: str | None
    photo_name: str | None
    maps_url: str
    #: Which source produced the image: "commons", "google", or None for no photo.
    provider: str | None = None
    #: Ready-to-render URL. Google photos are keyed at render time via
    #: ``place_photo_url(photo_name)`` instead, so this is set only for Commons.
    photo_url: str | None = None
    attribution: str | None = None
    license_name: str | None = None
    file_page_url: str | None = None
    #: "nearby" when a Commons photo was matched on coordinates rather than name.
    match_kind: str | None = None

    def is_approximate(self) -> bool:
        return self.match_kind == "nearby"


def google_maps_link(
    pin: SavedLocation,
    *,
    place_id: str | None = None,
) -> str:
    """Open the exact saved place — never ``Name, WrongCity`` search disambiguation.

    Priority:
    1. Google ``place_id``
    2. Takeout / Maps ``cid``
    3. ``Name/@lat,lng`` (name anchored at coordinates)
    4. Bare coordinates
    """
    if place_id:
        pid = place_id[len("places/") :] if place_id.startswith("places/") else place_id
        return f"https://www.google.com/maps/place/?q=place_id:{urllib.parse.quote(pid)}"

    cid = extract_cid_decimal_from_pin_raw(pin.raw_json)
    if cid is None:
        cid = extract_cid_decimal(url_from_raw_json(pin.raw_json))
    if cid is not None:
        return f"https://www.google.com/maps?cid={cid}"

    has_coords = pin.latitude != 0 or pin.longitude != 0
    name = (pin.name or "").strip()
    if name and has_coords:
        # Name anchored at coordinates — opens the titled place, not a city-suffixed search.
        slug = urllib.parse.quote(name, safe="")
        return (
            f"https://www.google.com/maps/place/{slug}/"
            f"@{pin.latitude},{pin.longitude},15z"
        )

    if name:
        # No coords: name only (do not append city/region — often wrong for Takeout).
        return (
            "https://www.google.com/maps/search/?api=1&query="
            + urllib.parse.quote_plus(name)
        )

    if has_coords:
        return (
            "https://www.google.com/maps/search/?api=1&query="
            f"{pin.latitude},{pin.longitude}"
        )
    return "https://www.google.com/maps/"

def place_photo_url(photo_name: str, *, max_width: int = 480, api_key: str | None = None) -> str | None:
    key = (api_key or os.environ.get("GOOGLE_MAPS_API_KEY", "")).strip()
    if not key or not photo_name:
        return None
    query = urllib.parse.urlencode({"maxWidthPx": max_width, "key": key})
    return f"https://places.googleapis.com/v1/{photo_name}/media?{query}"


class PlaceMediaCache:
    def __init__(self, atlas_db_path: Path) -> None:
        self.path = Path(atlas_db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def get(self, pin_id: str, source_hash: str, *, pin: SavedLocation | None = None) -> PlaceMedia | None:
        if not self.path.exists():
            return None
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT place_id, photo_name, provider, photo_url, attribution,
                       license_name, file_page_url, match_kind
                FROM place_media_cache
                WHERE pin_id = ? AND source_hash = ?
                """,
                (pin_id, source_hash),
            ).fetchone()
        if not row:
            return None
        return PlaceMedia(
            place_id=row["place_id"],
            photo_name=row["photo_name"],
            maps_url=google_maps_link(
                pin
                or SavedLocation(
                    id=pin_id,
                    name="",
                    latitude=0,
                    longitude=0,
                    list_name="",
                    source_type="cache",
                    source_file="cache",
                    raw_json="{}",
                ),
                place_id=row["place_id"],
            ),
            provider=row["provider"],
            photo_url=row["photo_url"],
            attribution=row["attribution"],
            license_name=row["license_name"],
            file_page_url=row["file_page_url"],
            match_kind=row["match_kind"],
        )

    def save(self, pin_id: str, source_hash: str, media: PlaceMedia) -> None:
        if not self.path.exists():
            return
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO place_media_cache(
                    pin_id, place_id, photo_name, source_hash, resolved_at,
                    provider, photo_url, attribution, license_name, file_page_url,
                    match_kind
                )
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(pin_id) DO UPDATE SET
                    place_id=excluded.place_id,
                    photo_name=excluded.photo_name,
                    source_hash=excluded.source_hash,
                    resolved_at=CURRENT_TIMESTAMP,
                    provider=excluded.provider,
                    photo_url=excluded.photo_url,
                    attribution=excluded.attribution,
                    license_name=excluded.license_name,
                    file_page_url=excluded.file_page_url,
                    match_kind=excluded.match_kind
                """,
                (
                    pin_id,
                    media.place_id,
                    media.photo_name,
                    source_hash,
                    media.provider,
                    media.photo_url,
                    media.attribution,
                    media.license_name,
                    media.file_page_url,
                    media.match_kind,
                ),
            )
            conn.commit()

    def invalidate_pin(self, pin_id: str) -> None:
        if not self.path.exists():
            return
        with self._connect() as conn:
            conn.execute("DELETE FROM place_media_cache WHERE pin_id = ?", (pin_id,))
            conn.commit()


def resolve_place_media(
    pin: SavedLocation,
    *,
    source_hash: str,
    atlas_db_path: Path,
    allow_google: bool = True,
) -> PlaceMedia:
    """Find a photo for *pin*.

    Strategy (``MEDIA_STRATEGY_VERSION``):
    1. Wikimedia Commons — ``name + city + country`` (then looser), name-token match.
    2. Optional Google Places only when ``GOOGLE_MAPS_API_KEY`` is set.
    3. Never accept pure Commons geosearch "nearby" for named venues.
    """
    _ = MEDIA_STRATEGY_VERSION
    cache = PlaceMediaCache(atlas_db_path)
    cached = cache.get(pin.id, source_hash, pin=pin)
    if cached:
        return cached

    # Free path first: location-scoped Commons search.
    photo = commons_media.find_photo(
        pin.name,
        pin.latitude,
        pin.longitude,
        city=pin.city,
        region=pin.region,
        country=pin.country,
        allow_nearby=False,
        require_name_match=True,
    )
    if photo:
        media = PlaceMedia(
            place_id=None,
            photo_name=None,
            maps_url=google_maps_link(pin),
            provider="commons",
            photo_url=photo.thumb_url,
            attribution=photo.attribution_line(),
            license_name=photo.license_name,
            file_page_url=photo.file_page_url,
            match_kind=photo.match,
        )
        cache.save(pin.id, source_hash, media)
        return media

    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    maps_url = url_from_raw_json(pin.raw_json)

    if allow_google and api_key:
        identity = resolve_place_identity(
            name=pin.name,
            raw_json=pin.raw_json,
            url=maps_url,
            latitude=pin.latitude,
            longitude=pin.longitude,
            allow_google_api=True,
        )
        if identity and identity.photo_name:
            media = PlaceMedia(
                place_id=identity.place_id,
                photo_name=identity.photo_name,
                maps_url=google_maps_link(pin, place_id=identity.place_id),
                provider="google",
                attribution="Google",
                match_kind="place",
            )
            cache.save(pin.id, source_hash, media)
            return media
        place_id, photo_name = _search_place_new(pin, api_key)
        if photo_name:
            media = PlaceMedia(
                place_id=place_id,
                photo_name=photo_name,
                maps_url=google_maps_link(pin, place_id=place_id),
                provider="google",
                attribution="Google",
                match_kind="place",
            )
            cache.save(pin.id, source_hash, media)
            return media

    media = PlaceMedia(
        place_id=None, photo_name=None, maps_url=google_maps_link(pin)
    )
    cache.save(pin.id, source_hash, media)
    return media


def _search_place_new(pin: SavedLocation, api_key: str) -> tuple[str | None, str | None]:
    payload = {
        "textQuery": pin.name,
        "maxResultCount": 1,
    }
    if pin.latitude != 0 or pin.longitude != 0:
        payload["locationBias"] = {
            "circle": {
                "center": {"latitude": pin.latitude, "longitude": pin.longitude},
                "radius": 5000.0,
            }
        }
    request = urllib.request.Request(
        "https://places.googleapis.com/v1/places:searchText",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "places.id,places.photos.name",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None, None

    places = body.get("places") or []
    if not places:
        return None, None
    place = places[0]
    place_id = place.get("id")
    photos = place.get("photos") or []
    photo_name = photos[0].get("name") if photos else None
    return place_id, photo_name


def search_nearby_lodging(
    *,
    latitude: float,
    longitude: float,
    radius_m: float = 2000.0,
    api_key: str | None = None,
    max_results: int = 20,
) -> list[dict]:
    """Google Places Nearby lodging / inns / B&Bs. Empty if no key or the call fails."""
    key = (api_key or os.environ.get("GOOGLE_MAPS_API_KEY", "")).strip()
    if not key:
        return []
    payload = {
        "includedTypes": ["lodging", "guest_house", "bed_and_breakfast", "inn"],
        "maxResultCount": max(1, min(int(max_results), 20)),
        "locationRestriction": {
            "circle": {
                "center": {"latitude": latitude, "longitude": longitude},
                "radius": float(radius_m),
            }
        },
    }
    request = urllib.request.Request(
        "https://places.googleapis.com/v1/places:searchNearby",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": key,
            "X-Goog-FieldMask": (
                "places.id,places.displayName,places.location,places.rating,"
                "places.googleMapsUri,places.types"
            ),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return []
    out: list[dict] = []
    for place in body.get("places") or []:
        if not isinstance(place, dict):
            continue
        loc = place.get("location") or {}
        try:
            lat = float(loc.get("latitude"))
            lon = float(loc.get("longitude"))
        except (TypeError, ValueError):
            continue
        display = place.get("displayName") or {}
        name = (
            display.get("text")
            if isinstance(display, dict)
            else None
        ) or place.get("id") or "Lodging"
        rating = place.get("rating")
        try:
            rating_f = float(rating) if rating is not None else None
        except (TypeError, ValueError):
            rating_f = None
        maps_url = place.get("googleMapsUri") or (
            f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
        )
        out.append(
            {
                "hotel_name": str(name),
                "provider": "google_places",
                "total_price": None,
                "nightly_rate": None,
                "currency": None,
                "rating": rating_f,
                "rating_scale": 5.0 if rating_f is not None else None,
                "rating_unknown": rating_f is None,
                "lat": lat,
                "lon": lon,
                "google_maps_url": str(maps_url),
                "place_id": place.get("id"),
                "types": list(place.get("types") or []),
            }
        )
    return out
