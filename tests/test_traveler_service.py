"""Tests for multi-traveler seed (Companion)."""

from __future__ import annotations

import sys
from pathlib import Path

_TRAVEL = Path(__file__).parent.parent
if str(_TRAVEL) not in sys.path:
    sys.path.insert(0, str(_TRAVEL))

from travel_atlas.database import AtlasDatabase
from travel_atlas.repository import AtlasRepository
from travel_atlas.services.traveler_docs import TravelerDocsService
from travel_atlas.services.traveler_service import (
    COMPANION_DISPLAY_NAME,
    TravelerService,
)
from travel_atlas.services.preferences_service import PreferencesService


def _repo(tmp_path: Path) -> AtlasRepository:
    database = AtlasDatabase(tmp_path / "atlas.db")
    database.migrate()
    return AtlasRepository(database)


def test_ensure_companion_seeds_birth_and_passport(tmp_path: Path) -> None:
    svc = TravelerService(_repo(tmp_path))
    svc.ensure_primary()
    companion = svc.ensure_companion()
    assert companion["display_name"] == COMPANION_DISPLAY_NAME
    assert companion["is_primary"] in (0, False)
    assert companion["birth_date"] == "1990-06-15"
    assert companion["birth_time"] == "09:30"
    assert companion["birth_timezone"] == "America/Los_Angeles"
    assert companion["birth_place"] == "Los Angeles, California"
    assert float(companion["birth_latitude"]) == 34.0522
    assert float(companion["birth_longitude"]) == -118.2437
    assert companion["passport_country"] == "United States of America"
    assert companion["passport_expires"] == "2034-01-01"


def test_ensure_companion_is_idempotent(tmp_path: Path) -> None:
    svc = TravelerService(_repo(tmp_path))
    svc.ensure_primary()
    first = svc.ensure_companion()
    second = svc.ensure_companion()
    assert first["id"] == second["id"]
    travelers = svc.list_travelers()
    companions = [
        t
        for t in travelers
        if (t.get("display_name") or "").casefold().startswith("companion")
    ]
    assert len(companions) == 1


def test_passport_status_accepts_documents_override(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    traveler_svc = TravelerService(repo)
    prefs = PreferencesService(repo)
    docs_svc = TravelerDocsService(prefs)
    traveler_svc.ensure_primary()
    companion = traveler_svc.ensure_companion()
    status = docs_svc.passport_status(
        destination="France",
        departure=None,
        documents=traveler_svc.as_documents(companion),
    )
    assert status["expires"] == "2034-01-01"
    assert status["passport_country"] == "United States of America"
    # Page counts were never recorded — do not fail on blank pages.
    assert not any("blank visa pages" in i.lower() for i in status["issues"])
