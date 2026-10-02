"""SQLite migrations for the standalone Travel Atlas database."""

from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA_VERSION = 14

_MIGRATION_1 = """
CREATE TABLE geo_area (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    area_type TEXT NOT NULL CHECK (area_type IN ('country', 'region', 'city')),
    country_code TEXT,
    parent_id TEXT REFERENCES geo_area(id),
    latitude REAL,
    longitude REAL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE knowledge_category (
    key TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    description TEXT NOT NULL,
    sort_order INTEGER NOT NULL
);

CREATE TABLE knowledge_topic (
    key TEXT PRIMARY KEY,
    category_key TEXT NOT NULL REFERENCES knowledge_category(key),
    display_name TEXT NOT NULL,
    description TEXT NOT NULL
);

CREATE TABLE source (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    publisher TEXT NOT NULL,
    source_url TEXT NOT NULL,
    enrichment_url TEXT,
    retrieved_at TEXT,
    license_note TEXT
);

CREATE TABLE source_record (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES source(id),
    external_key TEXT,
    raw_payload TEXT NOT NULL,
    checksum TEXT,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_id, external_key)
);

CREATE TABLE knowledge_claim (
    id TEXT PRIMARY KEY,
    area_id TEXT NOT NULL REFERENCES geo_area(id),
    category_key TEXT NOT NULL REFERENCES knowledge_category(key),
    topic_key TEXT NOT NULL REFERENCES knowledge_topic(key),
    value_json TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES source(id),
    source_record_id TEXT REFERENCES source_record(id),
    confidence TEXT NOT NULL CHECK (confidence IN ('high', 'medium', 'low')),
    review_status TEXT NOT NULL CHECK (review_status IN ('draft', 'reviewed', 'needs_review')),
    valid_from TEXT,
    valid_until TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE coverage_rule (
    area_type TEXT NOT NULL CHECK (area_type IN ('country', 'region', 'city')),
    category_key TEXT NOT NULL REFERENCES knowledge_category(key),
    topic_key TEXT NOT NULL REFERENCES knowledge_topic(key),
    weight REAL NOT NULL DEFAULT 1.0 CHECK (weight > 0),
    minimum_confidence TEXT NOT NULL DEFAULT 'medium'
        CHECK (minimum_confidence IN ('high', 'medium', 'low')),
    PRIMARY KEY (area_type, category_key, topic_key)
);

CREATE TABLE coverage_assessment (
    area_id TEXT NOT NULL REFERENCES geo_area(id),
    category_key TEXT NOT NULL REFERENCES knowledge_category(key),
    covered_weight REAL NOT NULL,
    required_weight REAL NOT NULL,
    score REAL NOT NULL,
    missing_topics_json TEXT NOT NULL,
    assessed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ruleset_version INTEGER NOT NULL,
    PRIMARY KEY (area_id, category_key, ruleset_version)
);

CREATE TABLE dynamic_snapshot (
    id TEXT PRIMARY KEY,
    area_id TEXT NOT NULL REFERENCES geo_area(id),
    adapter_key TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    source_url TEXT,
    retrieved_at TEXT NOT NULL,
    expires_at TEXT,
    status TEXT NOT NULL
);

CREATE INDEX idx_geo_area_parent ON geo_area(parent_id);
CREATE INDEX idx_claim_area_category ON knowledge_claim(area_id, category_key);
CREATE INDEX idx_claim_topic ON knowledge_claim(topic_key);
CREATE INDEX idx_snapshot_area_adapter ON dynamic_snapshot(area_id, adapter_key);
"""

_MIGRATION_2 = """
CREATE TABLE user_profile (
    user_key TEXT PRIMARY KEY,
    interests_json TEXT NOT NULL DEFAULT '[]',
    travel_style TEXT NOT NULL DEFAULT 'balanced',
    accommodation_preferences_json TEXT NOT NULL DEFAULT '{}',
    learning_goals_json TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE pin_classification (
    id TEXT PRIMARY KEY,
    pin_id TEXT NOT NULL,
    taxonomy_version TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    tags_json TEXT NOT NULL,
    confidence REAL NOT NULL,
    evidence_json TEXT NOT NULL,
    classified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(pin_id, taxonomy_version, source_hash)
);

CREATE TABLE language_lesson (
    id TEXT PRIMARY KEY,
    user_key TEXT NOT NULL REFERENCES user_profile(user_key),
    pin_id TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    language_code TEXT NOT NULL,
    topic_tag TEXT NOT NULL,
    title TEXT NOT NULL,
    context_text TEXT NOT NULL,
    phrases_json TEXT NOT NULL,
    explanation_json TEXT NOT NULL,
    lesson_source TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_key, pin_id, source_hash, language_code, topic_tag)
);

CREATE INDEX idx_pin_classification_pin ON pin_classification(pin_id);
CREATE INDEX idx_language_lesson_user ON language_lesson(user_key);
"""

_MIGRATION_3 = """
CREATE TABLE IF NOT EXISTS pin_annotation (
    pin_id TEXT PRIMARY KEY,
    note_text TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS custom_phrase (
    id TEXT PRIMARY KEY,
    area_id TEXT REFERENCES geo_area(id),
    pin_id TEXT,
    phrase TEXT NOT NULL,
    translation TEXT NOT NULL DEFAULT '',
    note TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS trip_plan (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS trip_plan_destination (
    trip_id TEXT NOT NULL REFERENCES trip_plan(id),
    destination_kind TEXT NOT NULL CHECK (destination_kind IN ('country', 'us_state', 'wishlist_country')),
    destination_label TEXT NOT NULL,
    order_index INTEGER NOT NULL,
    day_count INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (trip_id, order_index)
);

CREATE TABLE IF NOT EXISTS trip_plan_stop (
    id TEXT PRIMARY KEY,
    trip_id TEXT NOT NULL REFERENCES trip_plan(id),
    day_number INTEGER NOT NULL,
    pin_id TEXT NOT NULL,
    sort_index INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS place_media_cache (
    pin_id TEXT PRIMARY KEY,
    place_id TEXT,
    photo_name TEXT,
    source_hash TEXT NOT NULL,
    resolved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS geocode_cache (
    pin_id TEXT PRIMARY KEY,
    resolved_city TEXT,
    resolved_region TEXT,
    resolved_country TEXT,
    provider TEXT NOT NULL,
    resolved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO source(
    id, title, publisher, source_url, enrichment_url, retrieved_at, license_note
) VALUES (
    'user-notes', 'Personal notes', 'You', 'about:blank', NULL, CURRENT_TIMESTAMP,
    'User-authored notes stored locally.'
);
"""

_MIGRATION_4 = """
ALTER TABLE knowledge_claim ADD COLUMN season_start_month_day TEXT;
ALTER TABLE knowledge_claim ADD COLUMN season_end_month_day TEXT;
ALTER TABLE knowledge_claim ADD COLUMN season_label TEXT;

ALTER TABLE trip_plan_destination ADD COLUMN start_date TEXT;

CREATE INDEX IF NOT EXISTS idx_claim_area_season ON knowledge_claim(area_id, season_start_month_day);
"""

# Photos may now come from Wikimedia Commons as well as Google Places. Commons images
# are CC-licensed, so the artist, licence and file page are cached alongside the URL —
# without them the image cannot legally be displayed.
_MIGRATION_5 = """
ALTER TABLE place_media_cache ADD COLUMN provider TEXT;
ALTER TABLE place_media_cache ADD COLUMN photo_url TEXT;
ALTER TABLE place_media_cache ADD COLUMN attribution TEXT;
ALTER TABLE place_media_cache ADD COLUMN license_name TEXT;
ALTER TABLE place_media_cache ADD COLUMN file_page_url TEXT;
ALTER TABLE place_media_cache ADD COLUMN match_kind TEXT;
"""

# Monthly climate normals derived from Open-Meteo's historical archive. Cached by
# rounded coordinate because the answer to "which month is bearable" does not change
# between two points a few km apart, and the archive request is slow.
_MIGRATION_6 = """
CREATE TABLE IF NOT EXISTS climate_normals (
    cache_key  TEXT PRIMARY KEY,
    latitude   REAL NOT NULL,
    longitude  REAL NOT NULL,
    start_year INTEGER NOT NULL,
    end_year   INTEGER NOT NULL,
    payload    TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


# Bookkeeping for the knowledge ingestion pipeline. Filling the encyclopedia is a long,
# resumable job across hundreds of (area, topic) pairs, so each attempt is recorded —
# including the ones that produced nothing. Without that record a rerun would re-fetch
# and re-extract every barren pair forever; with it, a rerun only does new work.
#
# `review_status` gets an index because the review queue reads exclusively by it, and
# coverage scoring filters on it for every area.
_MIGRATION_7 = """
CREATE TABLE IF NOT EXISTS ingest_attempt (
    area_id      TEXT NOT NULL REFERENCES geo_area(id),
    topic_key    TEXT NOT NULL REFERENCES knowledge_topic(key),
    status       TEXT NOT NULL CHECK (
        status IN ('extracted', 'no_source', 'no_claims', 'error')
    ),
    detail       TEXT,
    model        TEXT,
    claim_count  INTEGER NOT NULL DEFAULT 0,
    attempted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (area_id, topic_key)
);

CREATE INDEX IF NOT EXISTS idx_claim_review_status
    ON knowledge_claim(review_status);
"""

# Planning personalization: expandable preference bag and trip definition JSON so
# new traveler fields (budget tendency, pace, favorite foods, …) do not require
# schema rewrites. Knowledge / ingest tables are untouched.
_MIGRATION_8 = """
ALTER TABLE user_profile ADD COLUMN preferences_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE trip_plan ADD COLUMN definition_json TEXT NOT NULL DEFAULT '{}';
"""

# Feedback loop + learned planning weights. The PlanningEngine stays read-only;
# FeedbackService writes these tables. Ratings close the loop between
# recommendations and outcomes; weight_state stores category multipliers.
_MIGRATION_9 = """
CREATE TABLE IF NOT EXISTS recommendation_rating (
    id TEXT PRIMARY KEY,
    user_key TEXT NOT NULL REFERENCES user_profile(user_key),
    subject_kind TEXT NOT NULL CHECK (subject_kind IN ('pin', 'claim', 'title')),
    subject_id TEXT NOT NULL,
    destination_label TEXT,
    category TEXT,
    rating TEXT NOT NULL CHECK (
        rating IN ('loved', 'liked', 'neutral', 'disliked', 'skip')
    ),
    score REAL NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_key, subject_kind, subject_id)
);

CREATE TABLE IF NOT EXISTS trip_journal_entry (
    id TEXT PRIMARY KEY,
    user_key TEXT NOT NULL REFERENCES user_profile(user_key),
    trip_id TEXT REFERENCES trip_plan(id),
    destination_label TEXT,
    entry_date TEXT,
    day_number INTEGER,
    body TEXT NOT NULL DEFAULT '',
    enjoyed_json TEXT NOT NULL DEFAULT '[]',
    skip_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS planning_weight_state (
    user_key TEXT NOT NULL REFERENCES user_profile(user_key),
    category TEXT NOT NULL,
    multiplier REAL NOT NULL DEFAULT 1.0,
    sample_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_key, category)
);

CREATE INDEX IF NOT EXISTS idx_rating_user_category
    ON recommendation_rating(user_key, category);
CREATE INDEX IF NOT EXISTS idx_journal_user
    ON trip_journal_entry(user_key);
"""

# Command Center: checklist, budget board, and Today mission history.
_MIGRATION_10 = """
CREATE TABLE IF NOT EXISTS trip_checklist_item (
    id TEXT PRIMARY KEY,
    trip_id TEXT NOT NULL REFERENCES trip_plan(id),
    key TEXT NOT NULL,
    band TEXT NOT NULL CHECK (band IN ('90', '60', '30', '7', 'travel', 'any')),
    title TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'prep',
    due_offset_days INTEGER,
    completed_at TEXT,
    sort_index INTEGER NOT NULL DEFAULT 0,
    UNIQUE(trip_id, key)
);

CREATE TABLE IF NOT EXISTS trip_budget_line (
    id TEXT PRIMARY KEY,
    trip_id TEXT NOT NULL REFERENCES trip_plan(id),
    category TEXT NOT NULL CHECK (
        category IN (
            'hotels', 'transportation', 'food', 'museums',
            'shopping', 'experiences', 'emergency_buffer'
        )
    ),
    label TEXT NOT NULL,
    estimated_amount REAL NOT NULL DEFAULT 0,
    actual_amount REAL,
    confidence REAL NOT NULL DEFAULT 40,
    source TEXT NOT NULL DEFAULT 'heuristic',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(trip_id, category, label)
);

CREATE TABLE IF NOT EXISTS trip_mission_log (
    id TEXT PRIMARY KEY,
    trip_id TEXT NOT NULL REFERENCES trip_plan(id),
    mission_date TEXT NOT NULL,
    missions_json TEXT NOT NULL DEFAULT '[]',
    completed_json TEXT NOT NULL DEFAULT '[]',
    prep_score REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(trip_id, mission_date)
);

CREATE INDEX IF NOT EXISTS idx_checklist_trip ON trip_checklist_item(trip_id);
CREATE INDEX IF NOT EXISTS idx_budget_trip ON trip_budget_line(trip_id);
CREATE INDEX IF NOT EXISTS idx_mission_trip ON trip_mission_log(trip_id);
"""

# Architecture foundation: hierarchical trips (regions), purchase-gated lifecycle,
# first-class reservations, and trip photos (distinct from place_media_cache).
_MIGRATION_11 = """
ALTER TABLE trip_plan ADD COLUMN parent_trip_id TEXT REFERENCES trip_plan(id);
ALTER TABLE trip_plan ADD COLUMN kind TEXT NOT NULL DEFAULT 'trip';
ALTER TABLE trip_plan ADD COLUMN lifecycle_stage TEXT NOT NULL DEFAULT 'idea';
ALTER TABLE trip_plan ADD COLUMN committed_at TEXT;
ALTER TABLE trip_plan ADD COLUMN active_focus INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS reservation (
    id TEXT PRIMARY KEY,
    trip_id TEXT NOT NULL REFERENCES trip_plan(id),
    kind TEXT NOT NULL CHECK (
        kind IN (
            'flight', 'hotel', 'museum', 'train', 'restaurant',
            'event', 'tour', 'other'
        )
    ),
    title TEXT NOT NULL,
    place_ref TEXT,
    status TEXT NOT NULL DEFAULT 'not_available' CHECK (
        status IN (
            'not_available', 'available_soon', 'book_now',
            'reserved', 'completed', 'cancelled'
        )
    ),
    opens_on TEXT,
    starts_at TEXT,
    ends_at TEXT,
    notify_at TEXT,
    booking_url TEXT,
    external_ref TEXT,
    notes TEXT,
    cost REAL,
    itinerary_day INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS trip_photo (
    id TEXT PRIMARY KEY,
    trip_id TEXT NOT NULL REFERENCES trip_plan(id),
    place_ref TEXT,
    day_number INTEGER,
    latitude REAL,
    longitude REAL,
    local_path TEXT,
    source_uri TEXT,
    caption TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    journal_entry_id TEXT REFERENCES trip_journal_entry(id),
    captured_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_trip_parent ON trip_plan(parent_trip_id);
CREATE INDEX IF NOT EXISTS idx_trip_active_focus ON trip_plan(active_focus);
CREATE INDEX IF NOT EXISTS idx_reservation_trip ON reservation(trip_id);
CREATE INDEX IF NOT EXISTS idx_reservation_status ON reservation(status);
CREATE INDEX IF NOT EXISTS idx_trip_photo_trip ON trip_photo(trip_id);
"""

_MIGRATION_12 = """
CREATE TABLE IF NOT EXISTS traveler (
    id TEXT PRIMARY KEY,
    user_key TEXT NOT NULL DEFAULT 'local-default',
    display_name TEXT NOT NULL,
    is_primary INTEGER NOT NULL DEFAULT 0,
    passport_country TEXT,
    passport_expires TEXT,
    visa_pages_blank INTEGER,
    visa_pages_total INTEGER,
    global_entry_expires TEXT,
    tsa_precheck INTEGER NOT NULL DEFAULT 0,
    tsa_precheck_via_global_entry INTEGER NOT NULL DEFAULT 0,
    birth_date TEXT,
    birth_place TEXT,
    birth_time TEXT,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_traveler_user ON traveler(user_key);
"""

# Allow UK nation legs (England/Scotland/Wales/NI) on trip plans. SQLite cannot
# ALTER a CHECK constraint in place, so rebuild the destination table.
_MIGRATION_13 = """
CREATE TABLE IF NOT EXISTS trip_plan_destination_new (
    trip_id TEXT NOT NULL REFERENCES trip_plan(id),
    destination_kind TEXT NOT NULL CHECK (
        destination_kind IN ('country', 'us_state', 'wishlist_country', 'uk_nation')
    ),
    destination_label TEXT NOT NULL,
    order_index INTEGER NOT NULL,
    day_count INTEGER NOT NULL DEFAULT 1,
    start_date TEXT,
    PRIMARY KEY (trip_id, order_index)
);

INSERT OR IGNORE INTO trip_plan_destination_new(
    trip_id, destination_kind, destination_label, order_index, day_count, start_date
)
SELECT trip_id, destination_kind, destination_label, order_index, day_count, start_date
FROM trip_plan_destination;

DROP TABLE trip_plan_destination;
ALTER TABLE trip_plan_destination_new RENAME TO trip_plan_destination;
"""

_MIGRATION_14 = """
ALTER TABLE traveler ADD COLUMN birth_timezone TEXT;
ALTER TABLE traveler ADD COLUMN birth_latitude REAL;
ALTER TABLE traveler ADD COLUMN birth_longitude REAL;
"""


class AtlasDatabase:
    """Owns Atlas database lifecycle without touching Phase 1 storage."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def migrate(self) -> None:
        with self.connect() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"Database version {version} is newer than supported "
                    f"version {SCHEMA_VERSION}."
                )
            if version < 1:
                conn.executescript(_MIGRATION_1)
                version = 1
                conn.execute("PRAGMA user_version = 1")
            if version < 2:
                conn.executescript(_MIGRATION_2)
                conn.execute("PRAGMA user_version = 2")
            if version < 3:
                conn.executescript(_MIGRATION_3)
                conn.execute("PRAGMA user_version = 3")
            if version < 4:
                conn.executescript(_MIGRATION_4)
                version = 4
                conn.execute("PRAGMA user_version = 4")
            if version < 5:
                conn.executescript(_MIGRATION_5)
                version = 5
                conn.execute("PRAGMA user_version = 5")
            if version < 6:
                conn.executescript(_MIGRATION_6)
                version = 6
                conn.execute("PRAGMA user_version = 6")
            if version < 7:
                conn.executescript(_MIGRATION_7)
                conn.execute("PRAGMA user_version = 7")
            if version < 8:
                conn.executescript(_MIGRATION_8)
                conn.execute("PRAGMA user_version = 8")
            if version < 9:
                conn.executescript(_MIGRATION_9)
                conn.execute("PRAGMA user_version = 9")
            if version < 10:
                conn.executescript(_MIGRATION_10)
                conn.execute("PRAGMA user_version = 10")
            if version < 11:
                conn.executescript(_MIGRATION_11)
                conn.execute("PRAGMA user_version = 11")
            if version < 12:
                conn.executescript(_MIGRATION_12)
                conn.execute("PRAGMA user_version = 12")
            if version < 13:
                conn.executescript(_MIGRATION_13)
                conn.execute("PRAGMA user_version = 13")
            if version < 14:
                conn.executescript(_MIGRATION_14)
                conn.execute("PRAGMA user_version = 14")
