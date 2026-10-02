"""Derive the Atlas geography from saved pins.

The Atlas cannot hold knowledge about a place it has no ``geo_area`` row for, and the
authoritative list of places worth knowing about is the pin set — those are the places
actually saved. This module reads Phase 1 pins (never writing to them) and provisions
the country and city rows they imply.

Area IDs are deterministic (``country-jp``, ``city-tokyo``) so re-running is an upsert
rather than a duplication, and so the bundled seed corpus for Japan and Tokyo lands on
exactly the rows a pin-derived run would create.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..repository import AtlasRepository

#: A country needs at least this many pins before its cities are provisioned too.
#: One saved airport in a country you passed through does not justify drafting a city
#: encyclopedia for it; the country-level entry is enough.
DEFAULT_CITY_MIN_PINS = 3


@dataclass(frozen=True)
class ProvisionedAreas:
    countries: list[str]
    cities: list[str]

    @property
    def total(self) -> int:
        return len(self.countries) + len(self.cities)


def slugify(value: str) -> str:
    """``"Côte d'Ivoire"`` → ``"cote-d-ivoire"``. Stable across runs and platforms."""
    normalised = unicodedata.normalize("NFKD", value)
    ascii_only = normalised.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_only.lower()).strip("-")
    return slug or "unknown"


def country_area_id(country: str, country_code: Optional[str] = None) -> str:
    """Prefer the ISO code — ``country-jp`` matches the bundled seed corpus."""
    if country_code and len(country_code) == 2:
        return f"country-{country_code.lower()}"
    return f"country-{slugify(country)}"


def city_area_id(city: str) -> str:
    return f"city-{slugify(city)}"


def _country_codes(conn: sqlite3.Connection) -> dict[str, str]:
    """Map country name → ISO 3166-1 alpha-2, resolved offline from pin coordinates.

    Pins store country *names*, which make poor identifiers. ``reverse_geocode`` ships
    an offline gazetteer, so one lookup per pin recovers the code without a network
    call. A country whose pins all lack coordinates simply falls back to a name slug.
    """
    try:
        import reverse_geocode
    except ImportError:
        return {}

    rows = conn.execute(
        """
        SELECT country, latitude, longitude FROM saved_locations
        WHERE country IS NOT NULL AND country <> ''
          AND latitude IS NOT NULL AND longitude IS NOT NULL
        """
    ).fetchall()
    if not rows:
        return {}

    try:
        resolved = reverse_geocode.search(
            [(row["latitude"], row["longitude"]) for row in rows]
        )
    except Exception:
        return {}

    # A pin near a border can reverse-geocode to the neighbour, so take the code the
    # country's pins agree on most often rather than trusting any single lookup.
    votes: dict[str, Counter] = {}
    for row, place in zip(rows, resolved):
        code = (place.get("country_code") or "").strip().upper()
        if len(code) == 2:
            votes.setdefault(row["country"], Counter())[code] += 1
    return {name: counter.most_common(1)[0][0] for name, counter in votes.items()}


def provision_areas(
    repository: AtlasRepository,
    pin_db_path: Path,
    *,
    countries: list[str] | None = None,
    city_min_pins: int = DEFAULT_CITY_MIN_PINS,
) -> ProvisionedAreas:
    """Create the ``geo_area`` rows implied by saved pins. Read-only on the pin DB."""
    pin_db_path = Path(pin_db_path)
    if not pin_db_path.exists():
        raise FileNotFoundError(f"Pin database not found: {pin_db_path}")

    conn = sqlite3.connect(f"file:{pin_db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        codes = _country_codes(conn)
        country_rows = conn.execute(
            """
            SELECT country, COUNT(*) AS pin_count,
                   AVG(latitude) AS latitude, AVG(longitude) AS longitude
            FROM saved_locations
            WHERE country IS NOT NULL AND country <> ''
            GROUP BY country
            ORDER BY pin_count DESC
            """
        ).fetchall()
        city_rows = conn.execute(
            """
            SELECT city, country, COUNT(*) AS pin_count,
                   AVG(latitude) AS latitude, AVG(longitude) AS longitude
            FROM saved_locations
            WHERE city IS NOT NULL AND city <> ''
              AND country IS NOT NULL AND country <> ''
            GROUP BY city, country
            ORDER BY pin_count DESC
            """
        ).fetchall()
    finally:
        conn.close()

    wanted = {c.strip().lower() for c in countries} if countries else None

    created_countries: dict[str, str] = {}
    for row in country_rows:
        name = row["country"].strip()
        if wanted is not None and name.lower() not in wanted:
            continue
        code = codes.get(row["country"])
        area_id = country_area_id(name, code)
        repository.upsert_area(
            {
                "id": area_id,
                "name": name,
                "area_type": "country",
                "country_code": code,
                "parent_id": None,
                "latitude": row["latitude"],
                "longitude": row["longitude"],
            }
        )
        created_countries[name] = area_id

    created_cities = []
    for row in city_rows:
        parent_id = created_countries.get(row["country"].strip())
        if parent_id is None or row["pin_count"] < city_min_pins:
            continue
        name = row["city"].strip()
        area_id = city_area_id(name)
        repository.upsert_area(
            {
                "id": area_id,
                "name": name,
                "area_type": "city",
                "country_code": codes.get(row["country"]),
                "parent_id": parent_id,
                "latitude": row["latitude"],
                "longitude": row["longitude"],
            }
        )
        created_cities.append(area_id)

    return ProvisionedAreas(
        countries=list(created_countries.values()), cities=created_cities
    )
