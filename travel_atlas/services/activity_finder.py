"""Travel-mode activity finder: hikes, light gym, martial arts, dance."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ActivityHit:
    name: str
    kind: str  # hike | gym | martial_arts | dance
    lat: float | None
    lon: float | None
    maps_url: str
    source: str


_KIND_QUERIES = {
    "hike": "hiking trail park walk",
    "gym": "gym fitness centre day pass",
    "martial_arts": "martial arts gym boxing muay thai",
    "dance": "dance class studio salsa bachata",
}


class ActivityFinder:
    """Prefer Google Places Text Search when keyed; else OSM Nominatim search."""

    def search(
        self,
        *,
        city: str,
        country: str,
        kinds: list[str] | None = None,
        limit_per_kind: int = 4,
    ) -> list[ActivityHit]:
        kinds = kinds or ["hike", "gym", "martial_arts", "dance"]
        hits: list[ActivityHit] = []
        api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
        for kind in kinds:
            q = _KIND_QUERIES.get(kind, kind)
            query = f"{q} in {city}, {country}"
            if api_key:
                hits.extend(
                    self._google(query, kind=kind, limit=limit_per_kind, api_key=api_key)
                )
            else:
                hits.extend(self._nominatim(query, kind=kind, limit=limit_per_kind))
        return hits

    def _google(
        self, query: str, *, kind: str, limit: int, api_key: str
    ) -> list[ActivityHit]:
        payload = {"textQuery": query, "maxResultCount": limit}
        request = urllib.request.Request(
            "https://places.googleapis.com/v1/places:searchText",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": (
                    "places.displayName,places.location,places.googleMapsUri,places.id"
                ),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
            return []
        out: list[ActivityHit] = []
        for place in body.get("places") or []:
            name = (place.get("displayName") or {}).get("text") or "Place"
            loc = place.get("location") or {}
            lat = loc.get("latitude")
            lon = loc.get("longitude")
            maps = place.get("googleMapsUri") or (
                "https://www.google.com/maps/search/?api=1&query="
                + urllib.parse.quote_plus(f"{name}, {query_tail(query)}")
            )
            out.append(
                ActivityHit(
                    name=name,
                    kind=kind,
                    lat=float(lat) if lat is not None else None,
                    lon=float(lon) if lon is not None else None,
                    maps_url=maps,
                    source="google",
                )
            )
        return out

    def _nominatim(self, query: str, *, kind: str, limit: int) -> list[ActivityHit]:
        url = (
            "https://nominatim.openstreetmap.org/search?"
            + urllib.parse.urlencode(
                {"q": query, "format": "json", "limit": str(limit)}
            )
        )
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "TravelAtlas/1.0 (personal travel prep)"},
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
            return []
        out: list[ActivityHit] = []
        for row in body or []:
            name = row.get("display_name") or "Place"
            short = name.split(",")[0].strip()
            try:
                lat = float(row["lat"])
                lon = float(row["lon"])
            except (KeyError, TypeError, ValueError):
                lat = lon = None
            maps = (
                "https://www.google.com/maps/search/?api=1&query="
                + urllib.parse.quote_plus(short + ", " + query_tail(query))
            )
            out.append(
                ActivityHit(
                    name=short,
                    kind=kind,
                    lat=lat,
                    lon=lon,
                    maps_url=maps,
                    source="nominatim",
                )
            )
        return out


def query_tail(query: str) -> str:
    if " in " in query:
        return query.split(" in ", 1)[1]
    return query
