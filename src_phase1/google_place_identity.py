"""Resolve Google Maps Takeout URLs to exact place coordinates / place IDs.

Takeout CSVs embed a feature id ``!1s0x…:0x…``. The hex after the colon is the
CID. Nominatim title geocoding often matches the wrong country for short/branded
names (e.g. Links N' Ice → Blyth, UK). Prefer CID / Places API identity.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Optional

# !1s0x<feature>:0x<cid>
_FEATURE_CID_RE = re.compile(r"!1s0x[0-9a-fA-F]+:0x([0-9a-fA-F]+)", re.I)
_CID_QUERY_RE = re.compile(r"[?&]cid=(\d+)", re.I)
# Embed HTML contains the place coordinates as a [lat,lng] array.
_COORD_RE = re.compile(r"\[(-?\d+\.\d+),(-?\d+\.\d+)\]")

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

#: Bump when media / geo strategy changes so place_media_cache invalidates.
MEDIA_STRATEGY_VERSION = "exact-maps-link-v2"


@dataclass(frozen=True)
class ResolvedPlace:
    latitude: float
    longitude: float
    place_id: str | None = None
    photo_name: str | None = None
    source: str = "cid_embed"


def extract_cid_decimal(url: str | None) -> Optional[int]:
    """Return Google CID as decimal int, or None."""
    if not url:
        return None
    match = _FEATURE_CID_RE.search(url)
    if match:
        return int(match.group(1), 16)
    match = _CID_QUERY_RE.search(url)
    if match:
        return int(match.group(1))
    return None


def extract_cid_decimal_from_pin_raw(raw_json: str | None) -> Optional[int]:
    try:
        payload = json.loads(raw_json or "{}")
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    for key in ("URL", "url", "google_maps_url", "Google Maps URL"):
        cid = extract_cid_decimal(str(payload.get(key) or ""))
        if cid is not None:
            return cid
    props = payload.get("properties")
    if isinstance(props, dict):
        return extract_cid_decimal(str(props.get("google_maps_url") or ""))
    return None


def url_from_raw_json(raw_json: str | None) -> Optional[str]:
    try:
        payload = json.loads(raw_json or "{}")
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    for key in ("URL", "url", "google_maps_url", "Google Maps URL"):
        value = payload.get(key)
        if value:
            return str(value).strip()
    props = payload.get("properties")
    if isinstance(props, dict) and props.get("google_maps_url"):
        return str(props["google_maps_url"]).strip()
    return None


def _valid_coords(lat: float, lng: float) -> bool:
    return -90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0 and not (
        lat == 0.0 and lng == 0.0
    )


def resolve_coords_via_cid_embed(
    url: str | None,
    *,
    timeout: int = 15,
) -> Optional[tuple[float, float]]:
    """Keyless exact-place coords via Maps embed HTML (no Places billing)."""
    cid = extract_cid_decimal(url)
    if cid is None:
        return None
    lookup = f"https://maps.google.com/maps?cid={cid}&output=embed&hl=en"
    request = urllib.request.Request(lookup, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="ignore")
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    match = _COORD_RE.search(body)
    if not match:
        return None
    lat, lng = float(match.group(1)), float(match.group(2))
    if not _valid_coords(lat, lng):
        return None
    return lat, lng


def resolve_place_via_places_api(
    *,
    name: str,
    url: str | None = None,
    latitude: float = 0.0,
    longitude: float = 0.0,
    api_key: str | None = None,
) -> Optional[ResolvedPlace]:
    """Resolve place_id + photo + coords via Places API (New) text search."""
    key = (api_key or os.environ.get("GOOGLE_MAPS_API_KEY", "")).strip()
    if not key:
        return None

    # Prefer CID-derived coords as a tight bias when available.
    cid_coords = resolve_coords_via_cid_embed(url) if url else None
    center_lat = cid_coords[0] if cid_coords else latitude
    center_lng = cid_coords[1] if cid_coords else longitude

    payload: dict = {
        "textQuery": name,
        "maxResultCount": 1,
    }
    if center_lat or center_lng:
        payload["locationBias"] = {
            "circle": {
                "center": {"latitude": center_lat, "longitude": center_lng},
                "radius": 2000.0 if cid_coords else 5000.0,
            }
        }

    request = urllib.request.Request(
        "https://places.googleapis.com/v1/places:searchText",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": key,
            "X-Goog-FieldMask": (
                "places.id,places.photos.name,places.location"
            ),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        if cid_coords:
            return ResolvedPlace(
                latitude=cid_coords[0],
                longitude=cid_coords[1],
                source="cid_embed",
            )
        return None

    places = body.get("places") or []
    if not places:
        if cid_coords:
            return ResolvedPlace(
                latitude=cid_coords[0],
                longitude=cid_coords[1],
                source="cid_embed",
            )
        return None

    place = places[0]
    location = place.get("location") or {}
    lat = float(location.get("latitude") or 0.0)
    lng = float(location.get("longitude") or 0.0)
    if not _valid_coords(lat, lng) and cid_coords:
        lat, lng = cid_coords
    if not _valid_coords(lat, lng):
        return None

    photos = place.get("photos") or []
    photo_name = photos[0].get("name") if photos else None
    return ResolvedPlace(
        latitude=lat,
        longitude=lng,
        place_id=place.get("id"),
        photo_name=photo_name,
        source="places_api",
    )


def resolve_place_identity(
    *,
    name: str,
    raw_json: str | None = None,
    url: str | None = None,
    latitude: float = 0.0,
    longitude: float = 0.0,
    allow_google_api: bool = True,
) -> Optional[ResolvedPlace]:
    """Best available identity: Places API when keyed, else CID embed."""
    maps_url = url or url_from_raw_json(raw_json)
    if allow_google_api and os.environ.get("GOOGLE_MAPS_API_KEY", "").strip():
        resolved = resolve_place_via_places_api(
            name=name,
            url=maps_url,
            latitude=latitude,
            longitude=longitude,
        )
        if resolved:
            return resolved
    if maps_url:
        coords = resolve_coords_via_cid_embed(maps_url)
        if coords:
            return ResolvedPlace(
                latitude=coords[0],
                longitude=coords[1],
                source="cid_embed",
            )
    return None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from math import asin, cos, radians, sin, sqrt

    r = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    )
    return 2 * r * asin(sqrt(a))


def coords_conflict(
    existing_lat: float,
    existing_lng: float,
    resolved_lat: float,
    resolved_lng: float,
    *,
    threshold_km: float = 50.0,
) -> bool:
    """True when existing Nominatim-ish coords disagree with CID/Places."""
    if existing_lat == 0 and existing_lng == 0:
        return True
    return (
        haversine_km(existing_lat, existing_lng, resolved_lat, resolved_lng)
        > threshold_km
    )
