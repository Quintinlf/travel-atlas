"""Static region overview maps for itinerary legs."""

from __future__ import annotations

import os
import urllib.parse
from typing import Iterable, Sequence


def region_map_image_url(
    coords: Sequence[tuple[float | None, float | None]] | Iterable[tuple],
    *,
    width: int = 640,
    height: int = 320,
) -> str | None:
    """Return a static map URL for the bounding box of *coords*, or None."""
    points: list[tuple[float, float]] = []
    for item in coords:
        if not item or len(item) < 2:
            continue
        lat, lng = item[0], item[1]
        if lat is None or lng is None:
            continue
        try:
            lat_f, lng_f = float(lat), float(lng)
        except (TypeError, ValueError):
            continue
        if lat_f == 0.0 and lng_f == 0.0:
            continue
        points.append((lat_f, lng_f))
    if not points:
        return None

    lats = [p[0] for p in points]
    lngs = [p[1] for p in points]
    min_lat, max_lat = min(lats), max(lats)
    min_lng, max_lng = min(lngs), max(lngs)
    # Pad tiny clusters so the map isn't a single pixel.
    pad_lat = max(0.08, (max_lat - min_lat) * 0.25 or 0.08)
    pad_lng = max(0.08, (max_lng - min_lng) * 0.25 or 0.08)
    min_lat -= pad_lat
    max_lat += pad_lat
    min_lng -= pad_lng
    max_lng += pad_lng
    center_lat = (min_lat + max_lat) / 2
    center_lng = (min_lng + max_lng) / 2

    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if api_key:
        markers = "|".join(f"{lat},{lng}" for lat, lng in points[:20])
        query = urllib.parse.urlencode(
            {
                "center": f"{center_lat},{center_lng}",
                "size": f"{width}x{height}",
                "maptype": "roadmap",
                "markers": f"size:tiny|{markers}",
                "key": api_key,
            }
        )
        return f"https://maps.googleapis.com/maps/api/staticmap?{query}"

    # OSM static fallback (no key).
    return (
        "https://staticmap.openstreetmap.de/staticmap.php?"
        f"center={center_lat},{center_lng}&zoom=10"
        f"&size={width}x{height}&maptype=mapnik"
        + "".join(f"&markers={lat},{lng},lightblue1" for lat, lng in points[:10])
    )
