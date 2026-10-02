"""
Phase 1 — SQLite repository for SavedLocation.

Handles:
  - DB initialisation (creates tables + indices on first use)
  - Bulk insert with conflict-safe upsert
  - Geographic deduplication (same place saved twice)
  - Query helpers used by clustering and insights layers
"""

from __future__ import annotations

import logging
import math
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Generator, List, Optional, Tuple

from .geo_grouping import top_level_destination
from .insights import BOOST_DEFAULT, clamp_boost
from .models import ALL_DDL, SavedLocation

logger = logging.getLogger(__name__)

_EARTH_RADIUS_KM = 6371.0

# Manual per-destination multipliers applied on top of the computed interest score.
# Created in _init_db() rather than in models.ALL_DDL so existing databases pick it up
# without a migration step, the same way idx_pins_region is handled.
_DESTINATION_BOOST_DDL = """
CREATE TABLE IF NOT EXISTS destination_boost (
    destination TEXT PRIMARY KEY,
    boost       REAL NOT NULL DEFAULT 1.0
)
"""

_COUNTRY_RATING_DDL = """
CREATE TABLE IF NOT EXISTS country_rating (
    destination TEXT PRIMARY KEY,
    rating      INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
    updated_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""


class PinRepository:
    """Thread-safe SQLite repository for Phase 1 pin data."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._init_db()

    # ---------------------------------------------------------------- #
    # DB lifecycle                                                       #
    # ---------------------------------------------------------------- #

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            for ddl in ALL_DDL:
                for statement in _split_statements(ddl):
                    if "idx_pins_region" in statement:
                        continue
                    conn.execute(statement)
            self._ensure_schema_migrations(conn)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_pins_region ON saved_locations(region)"
            )
            conn.execute(_DESTINATION_BOOST_DDL)
            conn.execute(_COUNTRY_RATING_DDL)

    @staticmethod
    def _ensure_schema_migrations(conn: sqlite3.Connection) -> None:
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(saved_locations)").fetchall()
        }
        if "region" not in columns:
            conn.execute("ALTER TABLE saved_locations ADD COLUMN region TEXT")

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ---------------------------------------------------------------- #
    # Write operations                                                   #
    # ---------------------------------------------------------------- #

    def insert_pin(self, location: SavedLocation) -> None:
        """Insert a single pin; silently ignore exact-id duplicates."""
        row = location.to_dict()
        with self._conn() as conn:
            conn.execute(_INSERT_PIN_SQL, row)

    def insert_pins_batch(self, locations: List[SavedLocation]) -> int:
        """Bulk-insert a list of pins. Returns number successfully inserted."""
        if not locations:
            return 0
        inserted = 0
        with self._conn() as conn:
            for loc in locations:
                try:
                    conn.execute(_INSERT_PIN_SQL, loc.to_dict())
                    inserted += 1
                except sqlite3.IntegrityError:
                    # Duplicate primary key — skip silently
                    pass
        return inserted

    def upsert_pins_batch(self, locations: List[SavedLocation]) -> dict[str, int]:
        """Insert new pins and refresh name/coords/raw for existing ids.

        Also matches by Google Maps URL in ``raw_json`` when the Takeout id changed
        but the place URL is the same.
        """
        empty = {"inserted": 0, "updated": 0, "unchanged": 0}
        if not locations:
            return empty

        existing = {pin.id: pin for pin in self.get_all_pins()}
        by_url: dict[str, SavedLocation] = {}
        for pin in existing.values():
            url = _url_from_raw(pin.raw_json)
            if url:
                by_url[url] = pin

        inserted = 0
        updated = 0
        unchanged = 0
        with self._conn() as conn:
            for loc in locations:
                row = loc.to_dict()
                target_id = loc.id
                prior = existing.get(loc.id)
                if prior is None:
                    url = _url_from_raw(loc.raw_json)
                    if url and url in by_url:
                        prior = by_url[url]
                        target_id = prior.id
                        row["id"] = target_id

                if prior is None:
                    try:
                        conn.execute(_INSERT_PIN_SQL, row)
                        inserted += 1
                        existing[loc.id] = loc
                    except sqlite3.IntegrityError:
                        unchanged += 1
                    continue

                # Takeout CSV rows are often CID-only (0,0). Never wipe real coords.
                incoming_lat = loc.latitude
                incoming_lng = loc.longitude
                prior_has_coords = prior.latitude != 0.0 or prior.longitude != 0.0
                incoming_missing = incoming_lat == 0.0 and incoming_lng == 0.0
                if prior_has_coords and incoming_missing:
                    incoming_lat = prior.latitude
                    incoming_lng = prior.longitude

                same_coords = (
                    abs(prior.latitude - incoming_lat) < 1e-6
                    and abs(prior.longitude - incoming_lng) < 1e-6
                )
                same_name = (prior.name or "") == (loc.name or "")
                same_list = (prior.list_name or "") == (loc.list_name or "")
                if same_coords and same_name and same_list:
                    unchanged += 1
                    continue

                conn.execute(
                    """
                    UPDATE saved_locations
                    SET name = ?, latitude = ?, longitude = ?, list_name = ?,
                        source_type = ?, source_file = ?, raw_json = ?,
                        notes = COALESCE(?, notes)
                    WHERE id = ?
                    """,
                    (
                        loc.name,
                        incoming_lat,
                        incoming_lng,
                        loc.list_name,
                        loc.source_type,
                        loc.source_file,
                        loc.raw_json,
                        loc.notes,
                        target_id,
                    ),
                )
                updated += 1

        return {"inserted": inserted, "updated": updated, "unchanged": unchanged}

    def update_pin_coordinates(self, pin_id: str, latitude: float, longitude: float) -> bool:
        """Update a pin's latitude/longitude. Returns True if a row was changed."""
        with self._conn() as conn:
            cursor = conn.execute(
                "UPDATE saved_locations SET latitude = ?, longitude = ? WHERE id = ?",
                (latitude, longitude, pin_id),
            )
            return cursor.rowcount > 0

    def update_pin_place(
        self,
        pin_id: str,
        city: str | None,
        country: str | None,
        region: str | None = None,
    ) -> bool:
        """Update a pin's city/region/country labels. Returns True if a row was changed."""
        with self._conn() as conn:
            cursor = conn.execute(
                "UPDATE saved_locations SET city = ?, region = ?, country = ? WHERE id = ?",
                (city, region, country, pin_id),
            )
            return cursor.rowcount > 0

    # ---------------------------------------------------------------- #
    # Destination boosts                                                 #
    # ---------------------------------------------------------------- #

    def get_destination_boosts(self) -> Dict[str, float]:
        """Return ``{destination_label: multiplier}`` for every stored override."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT destination, boost FROM destination_boost"
            ).fetchall()
        return {row["destination"]: float(row["boost"]) for row in rows}

    def set_destination_boost(self, destination: str, boost: float) -> None:
        """Store *destination*'s multiplier, clamped to the supported range.

        Setting it back to the default removes the row so an untouched database and a
        reset-to-default one behave identically.
        """
        value = clamp_boost(boost)
        with self._conn() as conn:
            if math.isclose(value, BOOST_DEFAULT):
                conn.execute(
                    "DELETE FROM destination_boost WHERE destination = ?",
                    (destination,),
                )
                return
            conn.execute(
                """
                INSERT INTO destination_boost (destination, boost) VALUES (?, ?)
                ON CONFLICT(destination) DO UPDATE SET boost = excluded.boost
                """,
                (destination, value),
            )

    def get_country_ratings(self) -> Dict[str, int]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT destination, rating FROM country_rating"
            ).fetchall()
        return {row["destination"]: int(row["rating"]) for row in rows}

    def set_country_rating(self, destination: str, rating: int | None) -> None:
        """Store a 1–5 personal country rating, or clear when *rating* is None."""
        with self._conn() as conn:
            if rating is None:
                conn.execute(
                    "DELETE FROM country_rating WHERE destination = ?",
                    (destination,),
                )
                return
            value = max(1, min(5, int(rating)))
            conn.execute(
                """
                INSERT INTO country_rating(destination, rating, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(destination) DO UPDATE SET
                    rating = excluded.rating,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (destination, value),
            )

    def insert_manual_pin(self, location: SavedLocation) -> None:
        """Insert a user-created planned pin."""
        with self._conn() as conn:
            conn.execute(_INSERT_PIN_SQL, location.to_dict())

    def delete_all_pins(self) -> None:
        """Flush all pins (and cascade to cluster_members)."""
        with self._conn() as conn:
            conn.execute("DELETE FROM cluster_members;")
            conn.execute("DELETE FROM clusters;")
            conn.execute("DELETE FROM saved_locations;")

    # ---------------------------------------------------------------- #
    # Deduplication                                                      #
    # ---------------------------------------------------------------- #

    def deduplicate(self, proximity_m: float = 100.0) -> int:
        """Remove duplicate pins that are within *proximity_m* metres of each
        other and share the same name (case-insensitive).

        The pin with the richer data (longer name + notes) is kept.
        Returns the number of pins removed.
        """
        pins = self.get_all_pins()
        if not pins:
            return 0

        threshold_km = proximity_m / 1000.0
        keep: Dict[str, SavedLocation] = {}  # id -> winner
        remove_ids: List[str] = []

        for pin in pins:
            matched = False
            for kept_id, kept_pin in keep.items():
                dist = haversine_km(pin.latitude, pin.longitude,
                                    kept_pin.latitude, kept_pin.longitude)
                if dist <= threshold_km and _similar_name(pin.name, kept_pin.name):
                    # Replace kept if current pin has richer data
                    if _richness(pin) > _richness(kept_pin):
                        remove_ids.append(kept_id)
                        keep[pin.id] = pin
                        del keep[kept_id]
                    else:
                        remove_ids.append(pin.id)
                    matched = True
                    break
            if not matched:
                keep[pin.id] = pin

        if remove_ids:
            with self._conn() as conn:
                for rid in remove_ids:
                    # cluster_members.pin_id → saved_locations(id); clear dependents first.
                    conn.execute(
                        "DELETE FROM cluster_members WHERE pin_id = ?", (rid,)
                    )
                    conn.execute(
                        "DELETE FROM saved_locations WHERE id = ?", (rid,)
                    )
                # Drop clusters that no longer have any members.
                conn.execute(
                    """
                    DELETE FROM clusters
                    WHERE id NOT IN (SELECT DISTINCT cluster_id FROM cluster_members)
                    """
                )
            logger.info("Deduplication removed %d pins", len(remove_ids))

        return len(remove_ids)

    # ---------------------------------------------------------------- #
    # Read operations                                                    #
    # ---------------------------------------------------------------- #

    def get_all_pins(self) -> List[SavedLocation]:
        from . import models as phase1_models

        pin_cls = phase1_models.SavedLocation
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM saved_locations").fetchall()
        return [pin_cls.from_row(dict(row)) for row in rows]

    def get_pins_with_coords(self) -> List[SavedLocation]:
        """Return only pins that have valid non-zero coordinates."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM saved_locations WHERE latitude != 0 OR longitude != 0"
            ).fetchall()
        return [SavedLocation.from_row(dict(r)) for r in rows]

    def get_pins_by_city(self, city: str) -> List[SavedLocation]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM saved_locations WHERE LOWER(city) = LOWER(?)", (city,)
            ).fetchall()
        return [SavedLocation.from_row(dict(r)) for r in rows]

    def get_pins_by_country(self, country: str) -> List[SavedLocation]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM saved_locations WHERE LOWER(country) = LOWER(?)", (country,)
            ).fetchall()
        return [SavedLocation.from_row(dict(r)) for r in rows]

    def get_pins_by_list(self, list_name: str) -> List[SavedLocation]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM saved_locations WHERE list_name = ?", (list_name,)
            ).fetchall()
        return [SavedLocation.from_row(dict(r)) for r in rows]

    def count(self) -> int:
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM saved_locations").fetchone()[0]

    def get_stats(self) -> Dict:
        """Return aggregate counts used by the dashboard."""
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM saved_locations").fetchone()[0]

            cities = conn.execute(
                "SELECT city, COUNT(*) as cnt FROM saved_locations "
                "WHERE city IS NOT NULL GROUP BY city ORDER BY cnt DESC"
            ).fetchall()

            countries = conn.execute(
                "SELECT country, COUNT(*) as cnt FROM saved_locations "
                "WHERE country IS NOT NULL GROUP BY country ORDER BY cnt DESC"
            ).fetchall()

            lists = conn.execute(
                "SELECT list_name, COUNT(*) as cnt FROM saved_locations "
                "GROUP BY list_name ORDER BY cnt DESC"
            ).fetchall()

        return {
            "total": total,
            "by_city": {r["city"]: r["cnt"] for r in cities},
            "by_country": {r["country"]: r["cnt"] for r in countries},
            "by_list": {r["list_name"]: r["cnt"] for r in lists},
            "by_destination": self._destination_counts(),
        }

    def _destination_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for pin in self.get_all_pins():
            kind, label = top_level_destination(pin)
            key = f"{kind}:{label}"
            counts[key] = counts.get(key, 0) + 1
        return counts

    # ---------------------------------------------------------------- #
    # Cluster persistence                                                #
    # ---------------------------------------------------------------- #

    def save_clusters(self, clusters: "List[Cluster]") -> None:  # noqa: F821
        """Persist a fresh set of clusters (replaces previous clustering)."""
        from datetime import datetime

        with self._conn() as conn:
            conn.execute("DELETE FROM cluster_members;")
            conn.execute("DELETE FROM clusters;")

            for cl in clusters:
                conn.execute(
                    """
                    INSERT INTO clusters
                        (id, name, city, country, centroid_lat, centroid_lng,
                         pin_count, threshold_km, created_at)
                    VALUES
                        (:id, :name, :city, :country, :centroid_lat,
                         :centroid_lng, :pin_count, :threshold_km, :created_at)
                    """,
                    {
                        "id": cl.id,
                        "name": cl.name,
                        "city": cl.city,
                        "country": cl.country,
                        "centroid_lat": cl.centroid_lat,
                        "centroid_lng": cl.centroid_lng,
                        "pin_count": cl.pin_count,
                        "threshold_km": cl.threshold_km,
                        "created_at": datetime.now().isoformat(),
                    },
                )
                for pin_id in cl.pin_ids:
                    conn.execute(
                        "INSERT INTO cluster_members (id, cluster_id, pin_id) VALUES (?, ?, ?)",
                        (str(uuid.uuid4()), cl.id, pin_id),
                    )

    def load_clusters(self) -> List[Dict]:
        """Return persisted clusters as plain dicts (for display)."""
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM clusters ORDER BY pin_count DESC").fetchall()
        return [dict(r) for r in rows]


# ------------------------------------------------------------------ #
# Module-level helpers                                                 #
# ------------------------------------------------------------------ #

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine great-circle distance in kilometres."""
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return _EARTH_RADIUS_KM * 2 * math.asin(math.sqrt(a))


def _similar_name(a: str, b: str) -> bool:
    """True when names are the same after lowercasing + stripping whitespace."""
    return a.strip().lower() == b.strip().lower()


def _richness(pin: SavedLocation) -> int:
    """Higher = more information available."""
    score = 0
    score += len(pin.name)
    score += len(pin.notes or "") * 2
    score += len(pin.city or "") + len(pin.country or "")
    score += len(pin.category or "")
    return score


def _url_from_raw(raw_json: str | None) -> str | None:
    if not raw_json:
        return None
    try:
        import json

        payload = json.loads(raw_json)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    for key in ("url", "URL", "googleMapsUrl", "mapsUrl"):
        value = payload.get(key)
        if isinstance(value, str) and value.startswith("http"):
            return value.strip()
    return None


def _split_statements(ddl: str) -> List[str]:
    """Split a multi-statement DDL string on semicolons."""
    return [s.strip() for s in ddl.split(";") if s.strip()]


_INSERT_PIN_SQL = """
INSERT OR IGNORE INTO saved_locations
    (id, name, latitude, longitude, city, region, country, list_name, notes,
     category, source_type, source_file, raw_json, imported_at,
     user_priority, tags)
VALUES
    (:id, :name, :latitude, :longitude, :city, :region, :country, :list_name,
     :notes, :category, :source_type, :source_file, :raw_json,
     :imported_at, :user_priority, :tags)
"""
