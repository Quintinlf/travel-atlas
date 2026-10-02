"""Top-level destination grouping for pins (country, US state, or UK nation)."""

from __future__ import annotations

import re
from typing import Literal

from .models import SavedLocation

DestinationKind = Literal["country", "us_state", "wishlist_country", "uk_nation"]

_US_COUNTRY_NAMES = frozenset(
    {
        "united states",
        "united states of america",
        "usa",
        "u.s.a.",
        "us",
        "u.s.",
    }
)

_UK_COUNTRY_NAMES = frozenset(
    {
        "united kingdom",
        "uk",
        "u.k.",
        "great britain",
        "britain",
    }
)

#: Canonical UK nation labels (Republic of Ireland is NOT included).
_UK_NATIONS = frozenset(
    {
        "england",
        "scotland",
        "wales",
        "northern ireland",
    }
)

_UK_NATION_ALIASES: dict[str, str] = {
    "england": "England",
    "scotland": "Scotland",
    "wales": "Wales",
    "northern ireland": "Northern Ireland",
    "ni": "Northern Ireland",
}

# Country-level aliases. England/Scotland/Wales/NI stay as nation names when
# used as wishlist pin titles; only generic UK labels collapse to United Kingdom.
_COUNTRY_ALIASES: dict[str, str] = {
    "uk": "United Kingdom",
    "u.k.": "United Kingdom",
    "great britain": "United Kingdom",
    "britain": "United Kingdom",
    "usa": "United States",
    "u.s.a.": "United States",
    "us": "United States",
    "u.s.": "United States",
    "republic of ireland": "Ireland",
    "irish republic": "Ireland",
    "eire": "Ireland",
    "éire": "Ireland",
    "ie": "Ireland",
    "irl": "Ireland",
}

_IRELAND_CITIES = frozenset(
    {
        "dublin",
        "galway",
        "cork",
        "howth",
        "killarney",
        "limerick",
        "waterford",
        "kilkenny",
        "kildare",
        "sligo",
        "westport",
        "dingle",
        "tralee",
        "athlone",
        "wexford",
        "donegal",
        "letterkenny",
        "shannon",
        "knock",
        "cliffs of moher",
        "clifden",
        "caherconlish",
        "tullyallen",
        "millstreet",
        "rathmines",
        "templemore",
        "drogheda",
        "mullingar",
        "connaught",
        "leinster",
        "munster",
    }
)

# Rough Republic of Ireland box; NI is excluded separately.
_ROI_LAT = (51.2, 55.45)
_ROI_LNG = (-10.8, -5.3)
_NI_LAT = (53.9, 55.4)
_NI_LNG = (-8.3, -5.3)

_WISHLIST_COUNTRY_NAMES = frozenset(
    {
        "japan",
        "china",
        "thailand",
        "vietnam",
        "kazakhstan",
        "france",
        "italy",
        "spain",
        "portugal",
        "ireland",
        "united kingdom",
        "england",
        "scotland",
        "wales",
        "northern ireland",
        "germany",
        "australia",
        "indonesia",
        "mexico",
        "canada",
        "brazil",
        "india",
        "south korea",
        "korea",
    }
)


def normalize_country(country: str | None) -> str | None:
    if not country:
        return None
    normalized = country.strip()
    if not normalized:
        return None
    lower = normalized.lower()
    if lower in _UK_NATION_ALIASES:
        # Keep nation string for callers that want it; country field often stores UK.
        return "United Kingdom"
    alias = _COUNTRY_ALIASES.get(lower)
    return alias or normalized


def is_known_country_label(value: str | None) -> bool:
    """True when the last CSV address segment looks like a real country, not a note."""
    if not value:
        return False
    lower = value.strip().lower()
    if lower in _COUNTRY_ALIASES or lower in _US_COUNTRY_NAMES or lower in _UK_COUNTRY_NAMES:
        return True
    if lower in _UK_NATION_ALIASES or lower in _WISHLIST_COUNTRY_NAMES:
        return True
    canonical = {v.lower() for v in _COUNTRY_ALIASES.values()}
    canonical.update(normalize_country(item).lower() for item in _WISHLIST_COUNTRY_NAMES if normalize_country(item))
    return lower in canonical


def looks_like_northern_ireland(text: str | None) -> bool:
    if not text:
        return False
    lower = text.strip().lower()
    return "northern ireland" in lower or lower in {"ni", "belfast", "derry", "londonderry"}


def infer_ireland(pin: SavedLocation) -> bool:
    """Republic of Ireland when country is missing or aliased."""
    country = normalize_country(pin.country)
    if country == "Ireland":
        return True
    if looks_like_northern_ireland(pin.country) or looks_like_northern_ireland(pin.region):
        return False
    if looks_like_northern_ireland(pin.name):
        return False
    city = (pin.city or "").strip().lower()
    if city in _IRELAND_CITIES:
        return True
    name = (pin.name or "").strip()
    if re.search(r"\bireland\b", name, re.I) and not looks_like_northern_ireland(name):
        return True
    if pin.latitude and pin.longitude and _in_republic_bbox(pin.latitude, pin.longitude):
        return True
    return False


def _in_republic_bbox(lat: float, lng: float) -> bool:
    if not (_ROI_LAT[0] <= lat <= _ROI_LAT[1] and _ROI_LNG[0] <= lng <= _ROI_LNG[1]):
        return False
    if _NI_LAT[0] <= lat <= _NI_LAT[1] and _NI_LNG[0] <= lng <= _NI_LNG[1]:
        return False
    return True


def normalize_uk_nation(value: str | None) -> str | None:
    if not value:
        return None
    return _UK_NATION_ALIASES.get(value.strip().lower())


def is_united_states(country: str | None) -> bool:
    if not country:
        return False
    return country.strip().lower() in _US_COUNTRY_NAMES


def is_united_kingdom(country: str | None) -> bool:
    if not country:
        return False
    lower = country.strip().lower()
    if lower in _UK_COUNTRY_NAMES:
        return True
    return lower in _UK_NATIONS


def is_wishlist_country_name(name: str) -> bool:
    cleaned = name.strip().lower()
    if cleaned in _WISHLIST_COUNTRY_NAMES:
        return True
    if cleaned in _COUNTRY_ALIASES:
        return True
    if cleaned in _UK_NATION_ALIASES:
        return True
    canonical = {normalize_country(item).lower() for item in _WISHLIST_COUNTRY_NAMES if normalize_country(item)}
    canonical.update(value.lower() for value in _COUNTRY_ALIASES.values())
    return cleaned in canonical


def uk_nation_for_pin(pin: SavedLocation) -> str | None:
    """Return England/Scotland/Wales/Northern Ireland when the pin belongs there."""
    for candidate in (pin.region, pin.name if not pin.city else None, pin.country):
        nation = normalize_uk_nation(candidate)
        if nation:
            return nation
    # Wishlist pins titled with a UK nation.
    if is_wishlist_country_name(pin.name) and not pin.city:
        return normalize_uk_nation(pin.name)
    return None


def top_level_destination(pin: SavedLocation) -> tuple[DestinationKind, str]:
    """Return the navigation bucket for a pin."""
    # Wishlist nation pins (England / Scotland / …) before country collapse.
    if is_wishlist_country_name(pin.name) and not pin.city:
        nation = normalize_uk_nation(pin.name)
        if nation:
            return "uk_nation", nation
        if pin.name.strip().lower() in {"united kingdom", "uk", "u.k."}:
            return "wishlist_country", "United Kingdom"
        canonical = normalize_country(pin.name) or pin.name.strip()
        # Ireland stays its own country — never a uk_nation.
        return "wishlist_country", canonical

    country = normalize_country(pin.country)
    if country == "Ireland" or (not country and infer_ireland(pin)):
        return "country", "Ireland"

    if country and is_united_states(country):
        region = (pin.region or "").strip()
        if region:
            return "us_state", region
        return "us_state", "United States (unknown state)"

    # Never steal Republic of Ireland pins into UK even if region looks like NI.
    nation = uk_nation_for_pin(pin)
    if nation and country != "Ireland" and (
        is_united_kingdom(pin.country) or normalize_uk_nation(pin.region)
    ):
        return "uk_nation", nation

    if country and is_united_kingdom(country):
        # UK pin without a resolvable nation — keep under United Kingdom.
        return "country", "United Kingdom"

    if country:
        return "country", country

    if infer_ireland(pin):
        return "country", "Ireland"

    return "country", "Unknown"


def destination_label(kind: DestinationKind | str, label: str) -> str:
    if kind == "us_state":
        return f"{label}, USA"
    if kind == "uk_nation":
        return f"{label} (UK)"
    return label


def _normalize_match_label(kind: DestinationKind | str, label: str) -> str:
    cleaned = label.replace(" (UK)", "").strip()
    if kind in {"country", "wishlist_country"}:
        return normalize_country(cleaned) or cleaned
    return cleaned


def destination_matches(
    pin: SavedLocation, kind: DestinationKind | str, label: str
) -> bool:
    pin_kind, pin_label = top_level_destination(pin)
    match_label = _normalize_match_label(kind, label)
    if kind == "country" and match_label.lower() in {"united kingdom", "uk", "u.k."}:
        # Matching "United Kingdom" includes all UK nation pins.
        return pin_kind in {"country", "uk_nation", "wishlist_country"} and (
            pin_label.lower() in {"united kingdom", "england", "scotland", "wales", "northern ireland"}
            or (pin_kind == "uk_nation")
        )
    # Wishlist / UK-nation / country buckets with the same label are equivalent for
    # trip filtering (e.g. trip leg country+France matches a wishlist "France" pin).
    if pin_label.lower() == match_label.lower():
        if kind == pin_kind:
            return True
        equivalent = {"country", "wishlist_country", "uk_nation"}
        if kind in equivalent and pin_kind in equivalent:
            return True
        return False
    if pin_kind != kind:
        return False
    return False

def trip_pin_stats(pins: list[SavedLocation]) -> dict:
    """Pin counts per destination bucket and per city for a trip filter."""
    by_destination: dict[str, int] = {}
    by_city: dict[str, int] = {}
    for pin in pins:
        kind, label = top_level_destination(pin)
        display = destination_label(kind, label)
        by_destination[display] = by_destination.get(display, 0) + 1
        city = (pin.city or "").strip() or "Unknown city"
        country = destination_label(kind, label)
        city_key = f"{city} — {country}"
        by_city[city_key] = by_city.get(city_key, 0) + 1
    return {
        "by_destination": dict(
            sorted(by_destination.items(), key=lambda item: (-item[1], item[0]))
        ),
        "by_city": dict(sorted(by_city.items(), key=lambda item: (-item[1], item[0]))),
        "total": len(pins),
    }


def ireland_leg_caption(pin_count: int) -> str:
    return (
        f"{pin_count} pins in the Republic of Ireland. "
        "Northern Ireland is under the UK. "
        "Notes on the country-level Ireland pin (Howth, spice bag, …) are not extra venues."
    )


# Mainland West Europe + UK/Ireland box used for default map cameras.
WEST_EUROPE_LAT_MIN = 35.0
WEST_EUROPE_LAT_MAX = 62.0
WEST_EUROPE_LON_MIN = -12.5
WEST_EUROPE_LON_MAX = 12.0
WEST_EUROPE_MAP_CENTER = (51.5, -1.0)
WEST_EUROPE_MAP_ZOOM = 5
WEST_EUROPE_FIT_BOUNDS = (
    (WEST_EUROPE_LAT_MIN, WEST_EUROPE_LON_MIN),
    (WEST_EUROPE_LAT_MAX, WEST_EUROPE_LON_MAX),
)


def in_west_europe_box(lat: float, lon: float) -> bool:
    return (
        WEST_EUROPE_LAT_MIN <= lat <= WEST_EUROPE_LAT_MAX
        and WEST_EUROPE_LON_MIN <= lon <= WEST_EUROPE_LON_MAX
    )


def world_map_view(
    coords: list[tuple[float, float]],
    *,
    show_all: bool = False,
) -> tuple[float, float, int, list[tuple[float, float]]]:
    """Return (center_lat, center_lon, zoom, coords_to_plot).

    Default camera is the West Europe box so Kazakhstan/Japan pins do not
    yank the centroid. ``show_all=True`` restores a global average.
    """
    if show_all:
        if not coords:
            return (
                WEST_EUROPE_MAP_CENTER[0],
                WEST_EUROPE_MAP_CENTER[1],
                WEST_EUROPE_MAP_ZOOM,
                [],
            )
        lat = sum(c[0] for c in coords) / len(coords)
        lon = sum(c[1] for c in coords) / len(coords)
        return lat, lon, 3, list(coords)
    west = [c for c in coords if in_west_europe_box(c[0], c[1])]
    return (
        WEST_EUROPE_MAP_CENTER[0],
        WEST_EUROPE_MAP_CENTER[1],
        WEST_EUROPE_MAP_ZOOM,
        west,
    )
