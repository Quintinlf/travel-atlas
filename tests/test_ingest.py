"""Tests for the knowledge ingestion pipeline.

Nothing here touches the network or a model. Source fetching is exercised against
canned article text, and extraction against a fake client, so the tests assert the
pipeline's contract: sourced drafts, no silent invention, and resumability.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_TRAVEL = Path(__file__).parent.parent
if str(_TRAVEL) not in sys.path:
    sys.path.insert(0, str(_TRAVEL))

from travel_atlas.database import AtlasDatabase
from travel_atlas.ingest import areas, extract, gaps, pipeline, sources
from travel_atlas.knowledge_loader import load_bundled_knowledge
from travel_atlas.repository import AtlasRepository

ARTICLE = """\
Portugal is a country on the Iberian Peninsula with a long Atlantic coastline and a
history of maritime exploration that shaped its cities and cuisine. The mainland is
divided between the greener, hillier north and the drier Alentejo plains of the south,
with the Azores and Madeira lying far out in the Atlantic.

== Eat ==
Bacalhau, salted cod, appears in hundreds of preparations. Pastel de nata is the
best-known pastry. Percebes, goose barnacles, are harvested from Atlantic rocks and
served simply boiled.

== Get around ==
Comboios de Portugal runs intercity rail. Lisbon and Porto both have metro systems
using rechargeable Viva Viagem cards.

== Stay safe ==
Portugal has low violent crime. Pickpocketing occurs on Lisbon tram 28. The general
emergency number is 112.

=== Natural hazards ===
Wildfires are a risk inland during summer.
"""


def make_repository(tmp_path: Path) -> AtlasRepository:
    database = AtlasDatabase(tmp_path / "atlas.db")
    database.migrate()
    repository = AtlasRepository(database)
    load_bundled_knowledge(repository)
    return repository


def make_pin_db(tmp_path: Path, rows: list[tuple[str, str, str, float, float]]) -> Path:
    """A minimal stand-in for the Phase 1 pin database."""
    path = tmp_path / "travel_pins.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE saved_locations ("
        "id TEXT PRIMARY KEY, name TEXT, city TEXT, country TEXT, "
        "latitude REAL, longitude REAL)"
    )
    conn.executemany(
        "INSERT INTO saved_locations(id, name, city, country, latitude, longitude) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [(f"pin-{i}", name, city, country, lat, lon)
         for i, (name, city, country, lat, lon) in enumerate(rows)],
    )
    conn.commit()
    conn.close()
    return path


# -- Areas -----------------------------------------------------------------


def test_slugify_is_stable_across_accents_and_punctuation() -> None:
    assert areas.slugify("Côte d'Ivoire") == "cote-d-ivoire"
    assert areas.slugify("  São Paulo  ") == "sao-paulo"
    assert areas.slugify("!!!") == "unknown"


def test_country_area_id_prefers_iso_code_matching_the_seed_corpus() -> None:
    assert areas.country_area_id("Japan", "JP") == "country-jp"
    assert areas.country_area_id("Japan", None) == "country-japan"


def test_provision_areas_creates_countries_and_only_well_pinned_cities(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)
    pin_db = make_pin_db(
        tmp_path,
        [("Belém", "Lisbon", "Portugal", 38.69, -9.21)] * 4
        + [("Airport", "Reykjavik", "Iceland", 64.13, -21.9)],
    )

    provisioned = areas.provision_areas(repository, pin_db, city_min_pins=3)

    names = {area["name"] for area in repository.list_areas()}
    assert {"Portugal", "Iceland", "Lisbon"} <= names
    # Reykjavik has one pin, below the threshold, so no city entry is created for it.
    assert "Reykjavik" not in names
    assert len(provisioned.cities) == 1


def test_provision_areas_never_writes_to_the_pin_database(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)
    pin_db = make_pin_db(tmp_path, [("Belém", "Lisbon", "Portugal", 38.69, -9.21)] * 3)
    before = pin_db.read_bytes()

    areas.provision_areas(repository, pin_db)

    assert pin_db.read_bytes() == before


# -- Sources ---------------------------------------------------------------


def test_split_sections_keeps_subsections_inside_their_parent() -> None:
    sections = sources.split_sections(ARTICLE)

    assert set(sections) >= {"__lead__", "eat", "get around", "stay safe"}
    assert "Wildfires" in sections["stay safe"]
    assert "natural hazards" not in sections


def test_assemble_document_keeps_only_requested_sections() -> None:
    sections = sources.split_sections(ARTICLE)

    document = sources.assemble_document(
        sources.WIKIVOYAGE_SOURCE_ID, "Portugal", sections, ["Eat", "Drink"]
    )

    assert document is not None
    assert "Percebes" in document.text
    assert "Comboios" not in document.text
    assert document.url.endswith("/wiki/Portugal")


def test_assemble_document_falls_back_to_the_lead_when_no_section_matches() -> None:
    sections = sources.split_sections(ARTICLE)

    document = sources.assemble_document(
        sources.WIKIVOYAGE_SOURCE_ID, "Portugal", sections, ["Nightlife"]
    )

    assert document is not None
    assert "Iberian Peninsula" in document.text


def test_assemble_document_returns_nothing_for_a_stub_article() -> None:
    document = sources.assemble_document(
        sources.WIKIPEDIA_SOURCE_ID, "Nowhere", {"__lead__": "A short stub."}, ["History"]
    )

    assert document is None


def test_every_mapped_topic_exists_in_the_taxonomy(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)
    with repository.database.connect() as conn:
        known = {row["key"] for row in conn.execute("SELECT key FROM knowledge_topic")}

    assert set(sources.TOPIC_SOURCES) <= known


# -- Gaps ------------------------------------------------------------------


def test_missing_topics_excludes_satisfied_and_already_attempted_topics(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)

    missing = {item["topic_key"] for item in repository.missing_topics("country-jp")}
    assert "cuisine" not in missing  # a reviewed, high-confidence claim exists
    assert "food_water_safety" in missing

    repository.record_attempt(
        area_id="country-jp", topic_key="food_water_safety", status="no_source"
    )
    retried = {item["topic_key"] for item in repository.missing_topics("country-jp")}

    assert "food_water_safety" not in retried


def test_missing_topics_counts_drafts_so_a_rerun_does_not_redraft(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)
    repository.upsert_source(
        {
            "id": "wikivoyage", "title": "Wikivoyage", "publisher": "Wikimedia",
            "source_url": "https://en.wikivoyage.org/", "enrichment_url": None,
            "retrieved_at": None, "license_note": "CC BY-SA 4.0",
        }
    )
    repository.upsert_claim(
        {
            "id": "draft-1",
            "area_id": "country-jp",
            "category_key": "microbiome",
            "topic_key": "food_water_safety",
            "value": {"title": "Tap water", "body": "Safe to drink."},
            "source_id": "wikivoyage",
            "confidence": "high",
            "review_status": "draft",
        }
    )

    missing = {item["topic_key"] for item in repository.missing_topics("country-jp")}

    assert "food_water_safety" not in missing
    # A draft still does not count toward the score.
    coverage = {c["category_key"]: c for c in repository.recompute_coverage("country-jp")}
    assert coverage["microbiome"]["score"] == 0.0


def test_worklist_prioritises_areas_with_more_pins(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)
    pin_db = make_pin_db(
        tmp_path,
        [("A", "Almaty", "Kazakhstan", 43.2, 76.9)] * 20
        + [("B", "Tokyo", "Japan", 35.6, 139.6)] * 2,
    )
    areas.provision_areas(repository, pin_db)

    worklist = gaps.build_worklist(repository, pin_db_path=pin_db)

    assert worklist
    assert worklist[0].area_name == "Kazakhstan"
    assert all(g.topic_key in sources.TOPIC_SOURCES for g in worklist)


# -- Extraction ------------------------------------------------------------


class _Block:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _Response:
    def __init__(self, text: str, stop_reason: str = "end_turn") -> None:
        self.content = [_Block(text)]
        self.stop_reason = stop_reason


class FakeMessages:
    """Returns canned JSON and records the prompts it was given."""

    def __init__(self, payloads: list[str]) -> None:
        self.payloads = list(payloads)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        payload = self.payloads.pop(0) if self.payloads else '{"claims": []}'
        return _Response(payload)


class FakeClient:
    def __init__(self, payloads: list[str]) -> None:
        self.messages = FakeMessages(payloads)


def _gap(topic_key: str, category_key: str) -> gaps.Gap:
    return gaps.Gap(
        area_id="country-pt",
        area_name="Portugal",
        area_type="country",
        country_code="PT",
        category_key=category_key,
        category_name=category_key.title(),
        topic_key=topic_key,
        topic_name=topic_key.replace("_", " ").title(),
        topic_description="A test topic.",
    )


def test_extract_claims_drops_topics_that_were_not_requested() -> None:
    client = FakeClient(
        [
            '{"claims": ['
            '{"topic_key": "cuisine", "title": "Bacalhau", "body": "Salted cod.",'
            ' "quote": "Bacalhau, salted cod", "confidence": "high",'
            ' "season_label": "", "season_start_month_day": "", "season_end_month_day": ""},'
            '{"topic_key": "etiquette", "title": "Smuggled", "body": "Not requested.",'
            ' "quote": "x", "confidence": "high",'
            ' "season_label": "", "season_start_month_day": "", "season_end_month_day": ""}'
            "]}"
        ]
    )
    document = sources.SourceDocument("wikivoyage", "Portugal", "https://x/", ARTICLE)

    claims = extract.extract_claims(
        client,
        area_name="Portugal",
        area_type="country",
        gaps=[_gap("cuisine", "food")],
        document=document,
    )

    assert [claim.topic_key for claim in claims] == ["cuisine"]
    assert claims[0].value() == {
        "title": "Bacalhau",
        "body": "Salted cod.",
        "quote": "Bacalhau, salted cod",
    }


def test_extract_claims_normalises_empty_season_fields_to_none() -> None:
    client = FakeClient(
        [
            '{"claims": [{"topic_key": "cuisine", "title": "T", "body": "B", "quote": "Q",'
            ' "confidence": "medium", "season_label": "", "season_start_month_day": "",'
            ' "season_end_month_day": ""}]}'
        ]
    )
    document = sources.SourceDocument("wikivoyage", "Portugal", "https://x/", ARTICLE)

    claim = extract.extract_claims(
        client,
        area_name="Portugal",
        area_type="country",
        gaps=[_gap("cuisine", "food")],
        document=document,
    )[0]

    assert claim.season_label is None
    assert claim.season_start_month_day is None


def test_extract_claims_sends_the_document_and_constrains_the_schema() -> None:
    client = FakeClient(['{"claims": []}'])
    document = sources.SourceDocument("wikivoyage", "Portugal", "https://x/", ARTICLE)

    extract.extract_claims(
        client,
        area_name="Portugal",
        area_type="country",
        gaps=[_gap("cuisine", "food")],
        document=document,
    )

    call = client.messages.calls[0]
    schema = call["output_config"]["format"]["schema"]
    enum = schema["properties"]["claims"]["items"]["properties"]["topic_key"]["enum"]
    assert enum == ["cuisine"]
    assert "Percebes" in call["messages"][0]["content"]
    assert call["model"] == extract.DEFAULT_MODEL


# -- Pipeline --------------------------------------------------------------


@pytest.fixture()
def offline_sources(monkeypatch):
    """Serve the canned article for Wikivoyage; pretend Wikipedia has nothing."""

    def fake_fetch_sections(source_id: str, title: str):
        if source_id == sources.WIKIVOYAGE_SOURCE_ID:
            return sources.split_sections(ARTICLE)
        return None

    monkeypatch.setattr(pipeline.sources, "fetch_sections", fake_fetch_sections)
    monkeypatch.setattr(pipeline, "FETCH_DELAY_SECONDS", 0)


def test_run_ingest_writes_drafts_with_source_records(tmp_path: Path, offline_sources) -> None:
    repository = make_repository(tmp_path)
    repository.upsert_area(
        {
            "id": "country-pt", "name": "Portugal", "area_type": "country",
            "country_code": "PT", "parent_id": None, "latitude": 39.5, "longitude": -8.0,
        }
    )
    payload = (
        '{"claims": [{"topic_key": "cuisine", "title": "Bacalhau and pastel de nata",'
        ' "body": "Salted cod appears in hundreds of preparations.", '
        '"quote": "Bacalhau, salted cod", "confidence": "high", "season_label": "",'
        ' "season_start_month_day": "", "season_end_month_day": ""}]}'
    )
    client = FakeClient([payload] * 10)

    result = pipeline.run_ingest(
        repository, area_ids=["country-pt"], client=client, on_progress=lambda m: None
    )

    assert result.claims_drafted == 1
    drafts = repository.list_claims_by_status("draft")
    assert len(drafts) == 1
    claim = drafts[0]
    assert claim["review_status"] == "draft"
    assert claim["source_id"] == "wikivoyage"
    assert claim["source_record_id"], "a claim must point at the text it came from"

    record = repository.find_source_record("wikivoyage", "Portugal")
    assert record and "Percebes" in record["raw_payload"]


def test_run_ingest_records_unsupported_topics_instead_of_inventing(
    tmp_path: Path, offline_sources
) -> None:
    repository = make_repository(tmp_path)
    repository.upsert_area(
        {
            "id": "country-pt", "name": "Portugal", "area_type": "country",
            "country_code": "PT", "parent_id": None, "latitude": 39.5, "longitude": -8.0,
        }
    )
    client = FakeClient(['{"claims": []}'] * 10)

    result = pipeline.run_ingest(
        repository, area_ids=["country-pt"], client=client, on_progress=lambda m: None
    )

    assert result.claims_drafted == 0
    assert result.topics_no_claims > 0
    with repository.database.connect() as conn:
        statuses = {
            row["status"]
            for row in conn.execute("SELECT status FROM ingest_attempt WHERE area_id = 'country-pt'")
        }
    assert statuses <= {"no_claims", "no_source"}


def test_run_ingest_is_resumable_and_does_not_redraft(tmp_path: Path, offline_sources) -> None:
    repository = make_repository(tmp_path)
    repository.upsert_area(
        {
            "id": "country-pt", "name": "Portugal", "area_type": "country",
            "country_code": "PT", "parent_id": None, "latitude": 39.5, "longitude": -8.0,
        }
    )
    payload = (
        '{"claims": [{"topic_key": "cuisine", "title": "T", "body": "B", "quote": "Q",'
        ' "confidence": "high", "season_label": "", "season_start_month_day": "",'
        ' "season_end_month_day": ""}]}'
    )

    first = FakeClient([payload] * 10)
    pipeline.run_ingest(repository, area_ids=["country-pt"], client=first, on_progress=lambda m: None)
    second = FakeClient([payload] * 10)
    result = pipeline.run_ingest(
        repository, area_ids=["country-pt"], client=second, on_progress=lambda m: None
    )

    assert result.calls_made == 0, "a second run should find nothing left to do"
    assert len(repository.list_claims_by_status("draft")) == 1


def test_approving_a_draft_raises_coverage(tmp_path: Path, offline_sources) -> None:
    repository = make_repository(tmp_path)
    repository.upsert_area(
        {
            "id": "country-pt", "name": "Portugal", "area_type": "country",
            "country_code": "PT", "parent_id": None, "latitude": 39.5, "longitude": -8.0,
        }
    )
    payload = (
        '{"claims": [{"topic_key": "cuisine", "title": "T", "body": "B", "quote": "Q",'
        ' "confidence": "high", "season_label": "", "season_start_month_day": "",'
        ' "season_end_month_day": ""}]}'
    )
    pipeline.run_ingest(
        repository, area_ids=["country-pt"], client=FakeClient([payload] * 10),
        on_progress=lambda m: None,
    )

    before = {c["category_key"]: c["score"] for c in repository.recompute_coverage("country-pt")}
    draft = repository.list_claims_by_status("draft")[0]
    pipeline.approve(repository, [draft["id"]])
    after = {c["category_key"]: c["score"] for c in repository.get_coverage("country-pt")}

    assert before["food"] == 0.0
    assert after["food"] > before["food"]
    assert repository.count_claims_by_status().get("draft", 0) == 0


def test_rejecting_a_draft_deletes_it(tmp_path: Path, offline_sources) -> None:
    repository = make_repository(tmp_path)
    repository.upsert_area(
        {
            "id": "country-pt", "name": "Portugal", "area_type": "country",
            "country_code": "PT", "parent_id": None, "latitude": 39.5, "longitude": -8.0,
        }
    )
    payload = (
        '{"claims": [{"topic_key": "cuisine", "title": "T", "body": "B", "quote": "Q",'
        ' "confidence": "high", "season_label": "", "season_start_month_day": "",'
        ' "season_end_month_day": ""}]}'
    )
    pipeline.run_ingest(
        repository, area_ids=["country-pt"], client=FakeClient([payload] * 10),
        on_progress=lambda m: None,
    )
    draft = repository.list_claims_by_status("draft")[0]

    assert pipeline.reject(repository, [draft["id"]]) == 1
    assert repository.list_claims_by_status("draft") == []
