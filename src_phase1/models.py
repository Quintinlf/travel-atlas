"""
Phase 1 — Core data models and SQLite schema.

Defines SavedLocation (the canonical representation of a saved map pin)
and the three database tables used throughout Phase 1.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict, fields
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class SavedLocation:
    """Canonical representation of a saved Google Maps pin.

    All fields are sourced directly from Takeout JSON where possible.
    ``raw_json`` preserves the original record verbatim so no information
    is ever lost during normalization.
    """

    id: str
    name: str
    latitude: float
    longitude: float
    list_name: str
    source_type: str
    source_file: str
    raw_json: str  # JSON-encoded original record

    city: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = None
    notes: Optional[str] = None
    category: Optional[str] = None
    imported_at: datetime = field(default_factory=datetime.now)
    user_priority: int = 5  # 1-10, default neutral
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Return a flat dict suitable for sqlite3 parameterised inserts."""
        d = asdict(self)
        d["imported_at"] = d["imported_at"].isoformat()
        d["tags"] = json.dumps(d["tags"])
        return d

    @staticmethod
    def from_row(row: Dict[str, Any]) -> "SavedLocation":
        """Re-hydrate a SavedLocation from a sqlite3.Row / plain dict."""
        allowed = {item.name for item in fields(SavedLocation)}
        data = {key: row[key] for key in allowed if key in row}
        if isinstance(data.get("imported_at"), str):
            data["imported_at"] = datetime.fromisoformat(data["imported_at"])
        if isinstance(data.get("tags"), str):
            data["tags"] = json.loads(data["tags"] or "[]")
        return SavedLocation(**data)

    def __repr__(self) -> str:
        loc = (
            f"{self.city}, {self.country}"
            if self.city
            else f"({self.latitude:.3f}, {self.longitude:.3f})"
        )
        return f"<SavedLocation name={self.name!r} loc={loc!r} list={self.list_name!r}>"


@dataclass
class Cluster:
    """A geographic cluster of SavedLocation pins."""

    id: str
    name: str
    centroid_lat: float
    centroid_lng: float
    pin_ids: List[str]
    threshold_km: float

    city: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = None
    primary_category: Optional[str] = None

    @property
    def pin_count(self) -> int:
        return len(self.pin_ids)

    def __repr__(self) -> str:
        label = self.city or self.name
        return f"<Cluster {label!r} pins={self.pin_count}>"


# ------------------------------------------------------------------ #
# SQLite DDL                                                           #
# ------------------------------------------------------------------ #

_DDL_SAVED_LOCATIONS = """
CREATE TABLE IF NOT EXISTS saved_locations (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    latitude      REAL NOT NULL,
    longitude     REAL NOT NULL,
    city          TEXT,
    region        TEXT,
    country       TEXT,
    list_name     TEXT NOT NULL,
    notes         TEXT,
    category      TEXT,
    source_type   TEXT NOT NULL,
    source_file   TEXT NOT NULL,
    raw_json      TEXT NOT NULL,
    imported_at   TEXT NOT NULL,
    user_priority INTEGER NOT NULL DEFAULT 5,
    tags          TEXT    NOT NULL DEFAULT '[]'
);
"""

_DDL_CLUSTERS = """
CREATE TABLE IF NOT EXISTS clusters (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    city         TEXT,
    country      TEXT,
    centroid_lat REAL NOT NULL,
    centroid_lng REAL NOT NULL,
    pin_count    INTEGER NOT NULL DEFAULT 0,
    threshold_km REAL NOT NULL,
    created_at   TEXT NOT NULL
);
"""

_DDL_CLUSTER_MEMBERS = """
CREATE TABLE IF NOT EXISTS cluster_members (
    id          TEXT PRIMARY KEY,
    cluster_id  TEXT NOT NULL,
    pin_id      TEXT NOT NULL,
    distance_km REAL,
    FOREIGN KEY (cluster_id) REFERENCES clusters(id),
    FOREIGN KEY (pin_id)     REFERENCES saved_locations(id)
);
"""

_DDL_INDICES = """
CREATE INDEX IF NOT EXISTS idx_pins_lat_lng    ON saved_locations(latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_pins_city       ON saved_locations(city);
CREATE INDEX IF NOT EXISTS idx_pins_region     ON saved_locations(region);
CREATE INDEX IF NOT EXISTS idx_pins_country    ON saved_locations(country);
CREATE INDEX IF NOT EXISTS idx_pins_list       ON saved_locations(list_name);
CREATE INDEX IF NOT EXISTS idx_members_cluster ON cluster_members(cluster_id);
CREATE INDEX IF NOT EXISTS idx_members_pin     ON cluster_members(pin_id);
"""

ALL_DDL: List[str] = [
    _DDL_SAVED_LOCATIONS,
    _DDL_CLUSTERS,
    _DDL_CLUSTER_MEMBERS,
    _DDL_INDICES,
]
