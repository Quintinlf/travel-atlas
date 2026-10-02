"""Tests for the standalone Travel Atlas knowledge foundation."""

from __future__ import annotations

import sys
from pathlib import Path

_TRAVEL = Path(__file__).parent.parent
if str(_TRAVEL) not in sys.path:
    sys.path.insert(0, str(_TRAVEL))

from travel_atlas.adapters import DynamicKnowledgeAdapter, DynamicSnapshot
from travel_atlas.database import AtlasDatabase, SCHEMA_VERSION
from travel_atlas.knowledge_loader import load_bundled_knowledge
from travel_atlas.repository import AtlasRepository


def make_repository(tmp_path: Path) -> AtlasRepository:
    database = AtlasDatabase(tmp_path / "atlas.db")
    database.migrate()
    return AtlasRepository(database)


def test_migration_creates_independent_atlas_schema(tmp_path: Path) -> None:
    database = AtlasDatabase(tmp_path / "atlas.db")
    database.migrate()

    with database.connect() as conn:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        version = conn.execute("PRAGMA user_version").fetchone()[0]

    assert version == SCHEMA_VERSION
    assert {"geo_area", "knowledge_claim", "source", "coverage_assessment"} <= tables
    assert "saved_locations" not in tables


def test_migration_adds_seasonal_columns(tmp_path: Path) -> None:
    database = AtlasDatabase(tmp_path / "atlas.db")
    database.migrate()

    with database.connect() as conn:
        claim_columns = {row["name"] for row in conn.execute("PRAGMA table_info(knowledge_claim)")}
        trip_destination_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(trip_plan_destination)")
        }

    assert {"season_start_month_day", "season_end_month_day", "season_label"} <= claim_columns
    assert "start_date" in trip_destination_columns


def test_bundled_knowledge_is_idempotent_and_preserves_evidence(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)
    load_bundled_knowledge(repository)
    load_bundled_knowledge(repository)

    japan_claims = repository.list_claims("country-jp")
    assert japan_claims
    assert all(claim["source_url"] for claim in japan_claims)
    assert all(claim["confidence"] in {"high", "medium", "low"} for claim in japan_claims)

    with repository.database.connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM knowledge_claim").fetchone()[0]
    assert count == 18


def test_coverage_is_derived_from_reviewed_confident_claims(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)
    load_bundled_knowledge(repository)

    coverage = {item["category_key"]: item for item in repository.get_coverage("city-tokyo")}
    assert coverage

    # The bundled Tokyo corpus fully satisfies the categories it was written for. The
    # ruleset also asks for city-level food and history, which the seed does not cover —
    # those score zero rather than being silently omitted, which is what makes the gap
    # visible to the ingestion worklist.
    for category in ("language", "culture", "logistics", "architecture", "health"):
        assert coverage[category]["score"] == 1.0, category
    assert coverage["food"]["score"] == 0.0
    assert coverage["food"]["missing_topics"] == ["cuisine"]

    with repository.database.connect() as conn:
        conn.execute(
            "UPDATE knowledge_claim SET review_status = 'needs_review' WHERE id = 'tokyo-transit'"
        )
    refreshed = repository.recompute_coverage("city-tokyo")
    logistics = next(item for item in refreshed if item["category_key"] == "logistics")

    assert logistics["score"] == 0.5
    assert logistics["missing_topics"] == ["public_transport"]


def test_list_seasonal_claims_returns_only_windowed_claims_for_the_area(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)
    load_bundled_knowledge(repository)

    seasonal = repository.list_seasonal_claims("country-kz")

    assert {claim["id"] for claim in seasonal} == {"kz-pastoral-calendar", "kz-nauryz"}


def test_dynamic_adapter_contract_is_separate_from_curated_storage() -> None:
    class ExampleAdapter:
        key = "weather"

        def fetch(self, area_id: str) -> DynamicSnapshot:
            raise NotImplementedError

    assert isinstance(ExampleAdapter(), DynamicKnowledgeAdapter)
