"""Multi-traveler profiles (passport, Global Entry, birth data for astro)."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from travel_atlas.repository import AtlasRepository
from travel_atlas.services.traveler_docs import DEFAULT_TRAVELER_DOCUMENTS

PRIMARY_DISPLAY_NAME = "Traveler One (me)"
COMPANION_DISPLAY_NAME = "Companion (Traveler Two)"

PRIMARY_BIRTH = {
    "birth_date": "2000-01-01",
    "birth_time": "12:00",
    "birth_place": "Los Angeles, California",
    "birth_timezone": "America/Los_Angeles",
    "birth_latitude": 34.0522,
    "birth_longitude": -118.2437,
}

COMPANION_BIRTH = {
    "birth_date": "1990-06-15",
    "birth_time": "09:30",
    "birth_place": "Los Angeles, California",
    "birth_timezone": "America/Los_Angeles",
    "birth_latitude": 34.0522,
    "birth_longitude": -118.2437,
}

COMPANION_DOCS = {
    "passport_country": "United States of America",
    "passport_expires": "2034-01-01",
}


class TravelerService:
    def __init__(self, repository: AtlasRepository) -> None:
        self.repository = repository

    def ensure_primary(self, user_key: str = "local-default") -> dict[str, Any]:
        travelers = self.list_travelers(user_key)
        if travelers:
            primary = next((t for t in travelers if t.get("is_primary")), travelers[0])
            return self._ensure_primary_profile(primary)
        docs = dict(DEFAULT_TRAVELER_DOCUMENTS)
        return self.create(
            display_name=PRIMARY_DISPLAY_NAME,
            user_key=user_key,
            is_primary=True,
            passport_country=docs["passport_country"],
            passport_expires=docs["passport_expires"],
            visa_pages_blank=docs["visa_pages_blank"],
            visa_pages_total=docs["visa_pages_total"],
            global_entry_expires=docs["global_entry_expires"],
            tsa_precheck=True,
            tsa_precheck_via_global_entry=True,
            **PRIMARY_BIRTH,
        )

    def _ensure_primary_profile(self, traveler: dict[str, Any]) -> dict[str, Any]:
        """Always seed the primary traveler's natal on the primary local traveler when fields are blank."""
        updates: dict[str, Any] = {}
        name = (traveler.get("display_name") or "").strip()
        if name in {"", "Me", "me"}:
            updates["display_name"] = PRIMARY_DISPLAY_NAME
        for key, value in PRIMARY_BIRTH.items():
            current = traveler.get(key)
            if current in (None, "", 0, 0.0):
                updates[key] = value
        if not updates:
            return traveler
        self.update(traveler["id"], **updates)
        return self.get(traveler["id"])

    def ensure_companion(self, user_key: str = "local-default") -> dict[str, Any]:
        """Idempotently seed Traveler Two (companion) as a companion traveler."""
        travelers = self.list_travelers(user_key)
        existing = next(
            (
                t
                for t in travelers
                if (t.get("display_name") or "").strip().casefold().startswith("companion")
            ),
            None,
        )
        if existing:
            return self._ensure_companion_profile(existing)
        return self.create(
            display_name=COMPANION_DISPLAY_NAME,
            user_key=user_key,
            is_primary=False,
            passport_country=COMPANION_DOCS["passport_country"],
            passport_expires=COMPANION_DOCS["passport_expires"],
            **COMPANION_BIRTH,
        )

    def _ensure_companion_profile(self, traveler: dict[str, Any]) -> dict[str, Any]:
        updates: dict[str, Any] = {}
        name = (traveler.get("display_name") or "").strip()
        if name in {"", "Aunt", "aunt", "Companion", "companion"}:
            updates["display_name"] = COMPANION_DISPLAY_NAME
        for key, value in COMPANION_BIRTH.items():
            current = traveler.get(key)
            if current in (None, "", 0, 0.0):
                updates[key] = value
        if not traveler.get("passport_country"):
            updates["passport_country"] = COMPANION_DOCS["passport_country"]
        if not traveler.get("passport_expires"):
            updates["passport_expires"] = COMPANION_DOCS["passport_expires"]
        if not updates:
            return traveler
        self.update(traveler["id"], **updates)
        return self.get(traveler["id"])

    def list_travelers(self, user_key: str = "local-default") -> list[dict[str, Any]]:
        with self.repository.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM traveler
                WHERE user_key = ?
                ORDER BY is_primary DESC, display_name COLLATE NOCASE
                """,
                (user_key,),
            ).fetchall()
        return [dict(row) for row in rows]

    def create(
        self,
        *,
        display_name: str,
        user_key: str = "local-default",
        is_primary: bool = False,
        passport_country: str | None = None,
        passport_expires: str | None = None,
        visa_pages_blank: int | None = None,
        visa_pages_total: int | None = None,
        global_entry_expires: str | None = None,
        tsa_precheck: bool = False,
        tsa_precheck_via_global_entry: bool = False,
        birth_date: str | None = None,
        birth_place: str | None = None,
        birth_time: str | None = None,
        birth_timezone: str | None = None,
        birth_latitude: float | None = None,
        birth_longitude: float | None = None,
    ) -> dict[str, Any]:
        traveler_id = str(uuid.uuid4())
        with self.repository.database.connect() as conn:
            if is_primary:
                conn.execute(
                    "UPDATE traveler SET is_primary = 0 WHERE user_key = ?",
                    (user_key,),
                )
            conn.execute(
                """
                INSERT INTO traveler(
                    id, user_key, display_name, is_primary,
                    passport_country, passport_expires, visa_pages_blank, visa_pages_total,
                    global_entry_expires, tsa_precheck, tsa_precheck_via_global_entry,
                    birth_date, birth_place, birth_time,
                    birth_timezone, birth_latitude, birth_longitude
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    traveler_id,
                    user_key,
                    display_name,
                    1 if is_primary else 0,
                    passport_country,
                    passport_expires,
                    visa_pages_blank,
                    visa_pages_total,
                    global_entry_expires,
                    1 if tsa_precheck else 0,
                    1 if tsa_precheck_via_global_entry else 0,
                    birth_date,
                    birth_place,
                    birth_time,
                    birth_timezone,
                    birth_latitude,
                    birth_longitude,
                ),
            )
        return self.get(traveler_id)

    def update(self, traveler_id: str, **fields: Any) -> dict[str, Any]:
        allowed = {
            "display_name",
            "birth_date",
            "birth_place",
            "birth_time",
            "birth_timezone",
            "birth_latitude",
            "birth_longitude",
            "passport_country",
            "passport_expires",
            "visa_pages_blank",
            "visa_pages_total",
            "global_entry_expires",
            "tsa_precheck",
            "tsa_precheck_via_global_entry",
        }
        sets = []
        values = []
        for key, value in fields.items():
            if key not in allowed:
                continue
            sets.append(f"{key} = ?")
            values.append(value)
        if not sets:
            return self.get(traveler_id)
        values.append(traveler_id)
        with self.repository.database.connect() as conn:
            conn.execute(
                f"UPDATE traveler SET {', '.join(sets)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                values,
            )
        return self.get(traveler_id)

    def get(self, traveler_id: str) -> dict[str, Any]:
        with self.repository.database.connect() as conn:
            row = conn.execute(
                "SELECT * FROM traveler WHERE id = ?", (traveler_id,)
            ).fetchone()
        if not row:
            raise ValueError(f"Unknown traveler: {traveler_id}")
        return dict(row)

    def as_documents(self, traveler: dict[str, Any]) -> dict[str, Any]:
        ge = traveler.get("global_entry_expires")
        via_ge = bool(traveler.get("tsa_precheck_via_global_entry"))
        tsa = bool(traveler.get("tsa_precheck"))
        if via_ge and ge and str(ge) >= date.today().isoformat():
            tsa = True
        return {
            "passport_country": traveler.get("passport_country"),
            "passport_expires": traveler.get("passport_expires"),
            "visa_pages_blank": traveler.get("visa_pages_blank"),
            "visa_pages_total": traveler.get("visa_pages_total"),
            "global_entry_expires": ge,
            "tsa_precheck": tsa,
            "tsa_precheck_via_global_entry": via_ge,
            "tsa_precheck_recommended": True,
            "birth_date": traveler.get("birth_date"),
            "birth_place": traveler.get("birth_place"),
            "birth_time": traveler.get("birth_time"),
            "birth_timezone": traveler.get("birth_timezone"),
            "birth_latitude": traveler.get("birth_latitude"),
            "birth_longitude": traveler.get("birth_longitude"),
            "display_name": traveler.get("display_name"),
        }
