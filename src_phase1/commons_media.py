"""Wikimedia Commons imagery for saved pins — free, keyless, and attributable.

Search by **name + city + country** (then progressively looser queries). Pure
coordinate geosearch is opt-in only — proximity hits were matching birds and
meals to the wrong venues.

Everything returned is CC-licensed; ``CommonsPhoto`` carries attribution metadata.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional

COMMONS_API = "https://commons.wikimedia.org/w/api.php"

# Wikimedia asks that API clients identify themselves with a contact-bearing UA.
USER_AGENT = "TravelAtlas/0.1 (personal travel planner; +https://github.com/)"

#: How close a Commons file's own coordinates must be to count as "of this place".
DEFAULT_RADIUS_M = 300

_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class CommonsPhoto:
    """A single Commons image plus the metadata its licence requires."""

    title: str
    thumb_url: str
    file_page_url: str
    artist: Optional[str]
    license_name: Optional[str]
    #: ``"nearby"`` when matched by coordinates, ``"named"`` when matched by title.
    match: str = "nearby"
    #: Query string that produced the hit (for debugging / UI).
    query: str | None = None

    def attribution_line(self) -> str:
        """Short credit suitable for a caption under the image."""
        artist = self.artist or "Unknown author"
        licence = self.license_name or "see file page"
        return f"{artist} / Wikimedia Commons ({licence})"

    def is_approximate(self) -> bool:
        """True when the photo is only known to be *near* the pin, not of it."""
        return self.match == "nearby"


def _name_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.casefold())
        if len(token) >= 3
    }


def titles_similar(pin_name: str, file_title: str) -> bool:
    """True when Commons file title shares meaningful tokens with the pin name."""
    pin_tokens = _name_tokens(pin_name)
    if not pin_tokens:
        return False
    file_tokens = _name_tokens(file_title)
    if not file_tokens:
        return False
    overlap = pin_tokens & file_tokens
    if not overlap:
        return False
    need = max(1, min(len(pin_tokens), len(file_tokens)) // 2)
    if len(overlap) >= need:
        return True
    return any(len(token) >= 5 for token in overlap)


def location_search_queries(
    name: str,
    *,
    city: str | None = None,
    region: str | None = None,
    country: str | None = None,
) -> list[str]:
    """Most-specific → least-specific Commons search strings."""
    name = (name or "").strip()
    if not name:
        return []
    city = (city or "").strip()
    region = (region or "").strip()
    country = (country or "").strip()

    # Drop region when it duplicates city/country labels.
    if region and region.casefold() in {
        city.casefold(),
        country.casefold(),
        name.casefold(),
    }:
        region = ""

    candidates = [
        " ".join(part for part in (name, city, country) if part),
        " ".join(part for part in (name, city, region) if part),
        " ".join(part for part in (name, city) if part),
        " ".join(part for part in (name, country) if part),
        " ".join(part for part in (name, region) if part),
        name,
    ]
    seen: set[str] = set()
    queries: list[str] = []
    for query in candidates:
        key = query.casefold()
        if not query or key in seen:
            continue
        seen.add(key)
        queries.append(query)
    return queries


def find_photo(
    name: str,
    latitude: float = 0.0,
    longitude: float = 0.0,
    *,
    city: str | None = None,
    region: str | None = None,
    country: str | None = None,
    radius_m: int = DEFAULT_RADIUS_M,
    thumb_width: int = 480,
    timeout: int = 20,
    allow_nearby: bool = True,
    require_name_match: bool = False,
) -> Optional[CommonsPhoto]:
    """Best Commons photo for a place, or ``None`` if Commons has nothing.

    Tries ``name city country`` first, then looser variants. Never raises on
    network trouble — caller falls through to the next source (or no image).
    """
    for query in location_search_queries(
        name, city=city, region=region, country=country
    ):
        photo = _title_search(
            query,
            thumb_width,
            timeout,
            require_name_match=require_name_match,
            pin_name=name.strip() if require_name_match else None,
        )
        if photo:
            return photo

    if allow_nearby and (latitude or longitude):
        return _geosearch(latitude, longitude, radius_m, thumb_width, timeout)
    return None


def _geosearch(
    latitude: float,
    longitude: float,
    radius_m: int,
    thumb_width: int,
    timeout: int,
) -> Optional[CommonsPhoto]:
    return _first_photo(
        {
            "generator": "geosearch",
            "ggscoord": f"{latitude}|{longitude}",
            "ggsradius": max(10, min(radius_m, 10000)),
            "ggslimit": 10,
            "ggsnamespace": 6,  # File:
        },
        thumb_width,
        timeout,
        match="nearby",
    )


def _title_search(
    query: str,
    thumb_width: int,
    timeout: int,
    *,
    require_name_match: bool = False,
    pin_name: str | None = None,
) -> Optional[CommonsPhoto]:
    return _first_photo(
        {
            "generator": "search",
            "gsrsearch": f"filetype:bitmap {query}",
            "gsrnamespace": 6,
            "gsrlimit": 10,
        },
        thumb_width,
        timeout,
        match="named",
        pin_name=pin_name if require_name_match else None,
        query=query,
    )


def _first_photo(
    generator_params: dict,
    thumb_width: int,
    timeout: int,
    *,
    match: str,
    pin_name: str | None = None,
    query: str | None = None,
) -> Optional[CommonsPhoto]:
    params = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
        "iiurlwidth": thumb_width,
        **generator_params,
    }
    payload = _get(params, timeout)
    if not payload:
        return None

    for page in (payload.get("query") or {}).get("pages") or []:
        photo = _page_to_photo(page, match, query=query)
        if not photo:
            continue
        if pin_name and not titles_similar(pin_name, photo.title):
            continue
        return photo
    return None


def _page_to_photo(
    page: dict, match: str, *, query: str | None = None
) -> Optional[CommonsPhoto]:
    info = (page.get("imageinfo") or [{}])[0]
    thumb = info.get("thumburl")
    if not thumb:
        return None

    meta = info.get("extmetadata") or {}
    return CommonsPhoto(
        title=str(page.get("title") or "").removeprefix("File:"),
        thumb_url=thumb,
        file_page_url=info.get("descriptionurl") or "",
        artist=_clean(_meta_value(meta, "Artist")),
        license_name=_meta_value(meta, "LicenseShortName"),
        match=match,
        query=query,
    )


def _meta_value(meta: dict, key: str) -> Optional[str]:
    entry = meta.get(key)
    if isinstance(entry, dict):
        value = entry.get("value")
        return str(value) if value else None
    return None


def _clean(value: Optional[str]) -> Optional[str]:
    """Commons returns Artist as an HTML fragment; reduce it to plain text."""
    if not value:
        return None
    text = _TAG_RE.sub("", value)
    text = urllib.parse.unquote(text).replace("&amp;", "&").strip()
    return " ".join(text.split()) or None


def _get(params: dict, timeout: int) -> Optional[dict[str, Any]]:
    url = f"{COMMONS_API}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
