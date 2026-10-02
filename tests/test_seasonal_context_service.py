"""Tests for SeasonalContextService: sky events + seasonal claim/note matching."""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

_TRAVEL = Path(__file__).parent.parent
if str(_TRAVEL) not in sys.path:
    sys.path.insert(0, str(_TRAVEL))

from travel_atlas.adapters import SkySnapshot
from travel_atlas.database import AtlasDatabase
from travel_atlas.knowledge_loader import load_bundled_knowledge
from travel_atlas.repository import AtlasRepository
from travel_atlas.services.notes_service import NotesService
from travel_atlas.services.seasonal_context_service import SeasonalContextService


class _StubAstronomyAdapter:
    key = "stub-v1"

    def __init__(self) -> None:
        self.calls: list[tuple[float, float, date]] = []

    def fetch(self, *, latitude: float, longitude: float, on_date: date) -> SkySnapshot:
        self.calls.append((latitude, longitude, on_date))
        return SkySnapshot(
            adapter_key=self.key,
            latitude=latitude,
            longitude=longitude,
            date=on_date,
            events=(),
            generated_at=datetime.now(timezone.utc),
        )


def make_repository(tmp_path: Path) -> AtlasRepository:
    database = AtlasDatabase(tmp_path / "atlas.db")
    database.migrate()
    repository = AtlasRepository(database)
    load_bundled_knowledge(repository)
    return repository


def test_almaty_wild_apple_claim_matches_late_may(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)
    service = SeasonalContextService(repository, astronomy_adapter=_StubAstronomyAdapter())

    context = service.get_seasonal_context(area_id="city-almaty", start_date=date(2026, 5, 26))

    claim_ids = {claim["id"] for claim in context["seasonal_claims"]}
    assert "kz-wild-apple" in claim_ids


def test_kazakhstan_pastoral_claim_matches_and_nauryz_excluded(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)
    service = SeasonalContextService(repository, astronomy_adapter=_StubAstronomyAdapter())

    context = service.get_seasonal_context(area_id="country-kz", start_date=date(2026, 5, 26))

    claim_ids = {claim["id"] for claim in context["seasonal_claims"]}
    assert "kz-pastoral-calendar" in claim_ids
    assert "kz-nauryz" not in claim_ids
    assert "kz-wild-apple" not in claim_ids  # different area_id (city, not country)


def test_personal_note_with_season_window_is_matched_separately(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)
    notes_service = NotesService(repository)
    notes_service.save_personal_note(
        area_id="country-kz",
        category_key="history",
        topic_key="seasonal_traditions",
        title="My own seasonal note",
        body="Personal observation about late May in Kazakhstan.",
        season_start_month_day="05-01",
        season_end_month_day="05-31",
        season_label="My seasonal window",
    )
    service = SeasonalContextService(repository, astronomy_adapter=_StubAstronomyAdapter())

    context = service.get_seasonal_context(area_id="country-kz", start_date=date(2026, 5, 26))

    personal_titles = {claim["value"]["title"] for claim in context["personal_notes"]}
    seasonal_titles = {claim["value"]["title"] for claim in context["seasonal_claims"]}
    assert "My own seasonal note" in personal_titles
    assert "My own seasonal note" not in seasonal_titles


def test_service_depends_only_on_injected_astronomy_adapter(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)
    stub = _StubAstronomyAdapter()
    service = SeasonalContextService(repository, astronomy_adapter=stub)

    service.get_seasonal_context(
        area_id="city-almaty", start_date=date(2026, 5, 26), latitude=43.222, longitude=76.8512
    )

    assert stub.calls  # the stub, not AstralAstronomyAdapter, was used
