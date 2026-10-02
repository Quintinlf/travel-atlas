"""Trip photos — first-class memory domain (manual / local stub first)."""

from __future__ import annotations

import uuid
from typing import Any

from travel_atlas.repository import AtlasRepository


class PhotoService:
    def __init__(self, repository: AtlasRepository) -> None:
        self.repository = repository

    def add(
        self,
        trip_id: str,
        *,
        caption: str = "",
        notes: str = "",
        place_ref: str | None = None,
        day_number: int | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        local_path: str | None = None,
        source_uri: str | None = None,
        journal_entry_id: str | None = None,
        captured_at: str | None = None,
    ) -> dict[str, Any]:
        photo_id = str(uuid.uuid4())
        with self.repository.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO trip_photo(
                    id, trip_id, place_ref, day_number, latitude, longitude,
                    local_path, source_uri, caption, notes, journal_entry_id,
                    captured_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    photo_id,
                    trip_id,
                    place_ref,
                    day_number,
                    latitude,
                    longitude,
                    local_path,
                    source_uri,
                    caption,
                    notes,
                    journal_entry_id,
                    captured_at,
                ),
            )
        return self.get(photo_id)

    def get(self, photo_id: str) -> dict[str, Any]:
        with self.repository.database.connect() as conn:
            row = conn.execute(
                "SELECT * FROM trip_photo WHERE id = ?", (photo_id,)
            ).fetchone()
        if not row:
            raise ValueError(f"Unknown photo: {photo_id}")
        return dict(row)

    def list_for_trip(self, trip_id: str) -> list[dict[str, Any]]:
        with self.repository.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM trip_photo
                WHERE trip_id = ?
                ORDER BY
                    CASE WHEN captured_at IS NULL THEN 1 ELSE 0 END,
                    captured_at ASC,
                    created_at ASC
                """,
                (trip_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def count_for_trip(self, trip_id: str) -> int:
        with self.repository.database.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM trip_photo WHERE trip_id = ?",
                (trip_id,),
            ).fetchone()
        return int(row["n"] if row else 0)

    def link_journal(self, photo_id: str, journal_entry_id: str | None) -> dict[str, Any]:
        with self.repository.database.connect() as conn:
            conn.execute(
                "UPDATE trip_photo SET journal_entry_id = ? WHERE id = ?",
                (journal_entry_id, photo_id),
            )
        return self.get(photo_id)

    def update_caption(
        self, photo_id: str, *, caption: str | None = None, notes: str | None = None
    ) -> dict[str, Any]:
        photo = self.get(photo_id)
        with self.repository.database.connect() as conn:
            conn.execute(
                """
                UPDATE trip_photo
                SET caption = ?, notes = ?
                WHERE id = ?
                """,
                (
                    photo["caption"] if caption is None else caption,
                    photo["notes"] if notes is None else notes,
                    photo_id,
                ),
            )
        return self.get(photo_id)
