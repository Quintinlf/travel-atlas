"""Phase 2 tests: pin resolution, contextual lessons, and local migrations."""

from __future__ import annotations

import importlib
import json
import sys
import uuid
from pathlib import Path

import pytest

_TRAVEL = Path(__file__).parent.parent
if str(_TRAVEL) not in sys.path:
    sys.path.insert(0, str(_TRAVEL))

from src_phase1.models import SavedLocation
from src_phase1.pin_repository import PinRepository
from travel_atlas.database import AtlasDatabase
from travel_atlas.knowledge_loader import load_bundled_knowledge
from travel_atlas.repository import AtlasRepository
from travel_atlas.services.itinerary_service import ItineraryService
from travel_atlas.services.knowledge_service import KnowledgeService
from travel_atlas.services.language_service import LanguageService
from travel_atlas.services.pin_service import PinDataUnavailableError, PinService
from travel_atlas.services.planning_service import PlanningService
from travel_atlas.services.preferences_service import PreferencesService
from travel_atlas.services.types import AreaResolution


def make_services(tmp_path: Path) -> tuple[PinService, KnowledgeService, LanguageService]:
    atlas_database = AtlasDatabase(tmp_path / "atlas.db")
    atlas_database.migrate()
    atlas_repository = AtlasRepository(atlas_database)
    load_bundled_knowledge(atlas_repository)
    return (
        PinService(tmp_path / "pins.db"),
        KnowledgeService(atlas_repository),
        LanguageService(atlas_repository, PinService(tmp_path / "pins.db"), KnowledgeService(atlas_repository)),
    )


def insert_pin(tmp_path: Path, **kwargs: object) -> SavedLocation:
    pin = SavedLocation(
        id=str(uuid.uuid4()),
        name=str(kwargs.get("name", "Tokyo National Museum")),
        latitude=float(kwargs.get("latitude", 35.7219)),
        longitude=float(kwargs.get("longitude", 139.7758)),
        city=kwargs.get("city", "Tokyo"),
        country=kwargs.get("country", "Japan"),
        list_name="Want To Go",
        notes=kwargs.get("notes"),
        category=kwargs.get("category"),
        source_type="test",
        source_file="test.json",
        raw_json=str(kwargs.get("raw_json", "{}")),
    )
    PinRepository(tmp_path / "pins.db").insert_pin(pin)
    return pin


def test_pin_resolves_to_exact_city_and_atlas_context(tmp_path: Path) -> None:
    pin = insert_pin(tmp_path)
    _, knowledge_service, _ = make_services(tmp_path)

    context = knowledge_service.get_context_for_pin(pin)

    assert context["resolution"].area_id == "city-tokyo"
    assert context["resolution"].method == "exact_city"
    assert context["claims_by_category"]


def test_coordinateless_pin_resolves_by_name_match(tmp_path: Path) -> None:
    pin = insert_pin(
        tmp_path, name="Tokyo Tower observation deck",
        city=None, country=None, latitude=0.0, longitude=0.0,
    )
    _, knowledge_service, _ = make_services(tmp_path)

    resolution = knowledge_service.resolve_pin(pin)

    assert resolution.area_id == "city-tokyo"
    assert resolution.method == "name_match"


def test_uncovered_pin_is_explicit_not_location_specific(tmp_path: Path) -> None:
    pin = insert_pin(tmp_path, name="Louvre", city="Paris", country="France", latitude=48.8606, longitude=2.3376)
    _, knowledge_service, _ = make_services(tmp_path)

    context = knowledge_service.get_context_for_pin(pin)

    assert context["resolution"].context_status == "uncovered"
    assert context["claims_by_category"] == {}


def test_market_pin_generates_explainable_japanese_lesson(tmp_path: Path) -> None:
    pin = insert_pin(tmp_path, name="Tsukiji Fish Market", category="Market")
    pin_service, knowledge_service, language_service = make_services(tmp_path)
    assert pin_service.get_pin_details(pin.id)

    lesson = language_service.generate_language_lesson([pin.id])[0]

    assert lesson.lesson_source == "offline_phrase_catalog_japanese"
    assert lesson.explanation["classification_tags"][0] == "market_food"
    assert lesson.explanation["matching_evidence"][0]["term"] in {"market", "fish"}


def test_preferences_rank_the_lesson_queue_without_mutating_pins(tmp_path: Path) -> None:
    market = insert_pin(tmp_path, name="Tsukiji Fish Market", category="Market")
    museum = insert_pin(tmp_path, name="Tokyo National Museum", category="Museum")
    _, _, language_service = make_services(tmp_path)
    language_service.repository.save_profile(
        "local-default", ["museum_history"], "balanced", {}, ["history"]
    )

    queue = language_service.personalized_lesson_queue()

    assert queue[0].pin_id == museum.id
    assert market.id != museum.id


def test_phase2_migration_creates_personalization_tables(tmp_path: Path) -> None:
    database = AtlasDatabase(tmp_path / "atlas.db")
    database.migrate()

    with database.connect() as conn:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert {"user_profile", "pin_classification", "language_lesson"} <= tables


def test_lfs_pin_database_pointer_has_actionable_error(tmp_path: Path) -> None:
    pointer_path = tmp_path / "travel_pins.db"
    pointer_path.write_text(
        "version https://git-lfs.github.com/spec/v1\n"
        "oid sha256:placeholder\n"
        "size 65536\n",
        encoding="utf-8",
    )

    with pytest.raises(PinDataUnavailableError, match="Git LFS pointer"):
        PinService(pointer_path)


def test_empty_pin_database_bootstraps_from_local_saved_takeout(tmp_path: Path) -> None:
    saved_dir = tmp_path / "Takeout" / "Saved"
    saved_dir.mkdir(parents=True)
    (saved_dir / "Want to go.csv").write_text(
        'Title,Note,URL,Tags,Comment\n'
        '"Tsukiji Fish Market",,"https://www.google.com/maps/@35.6654,139.7707,17z",,\n',
        encoding="utf-8",
    )
    pin_service = PinService(tmp_path / "pins.db")

    result = pin_service.bootstrap_from_takeout(saved_dir)

    assert result["inserted"] == 1
    assert result["clusters"] == 0
    assert pin_service.list_pins()[0].name == "Tsukiji Fish Market"


def test_enrich_from_geocoded_csv_fills_missing_coordinates(tmp_path: Path) -> None:
    url = "https://www.google.com/maps/place/Tsukiji/data=!4m2!3m1!1s0x0:0x1"
    pin = insert_pin(
        tmp_path,
        name="Tsukiji Fish Market",
        latitude=0.0,
        longitude=0.0,
        raw_json=json.dumps({"Title": "Tsukiji Fish Market", "URL": url}),
    )
    geocoded = tmp_path / "Want to go_geocoded.csv"
    geocoded.write_text(
        "Title,Note,URL,Tags,Comment,Latitude,Longitude,GeocodeNote\n"
        f'"Tsukiji Fish Market",,"{url}",,,35.6654,139.7707,\n',
        encoding="utf-8",
    )
    pin_service = PinService(tmp_path / "pins.db")

    result = pin_service.enrich_from_geocoded_csv(geocoded)

    assert result["updated"] == 1
    assert result["clusters"] == 0
    updated = pin_service.get_pin_details(pin.id)
    assert updated is not None
    assert updated.latitude == 35.6654
    assert updated.longitude == 139.7707


def test_upsert_preserves_coords_when_takeout_sends_zero(tmp_path: Path) -> None:
    url = "https://www.google.com/maps/place/Louvre/data=!4m2!3m1!1s0x0:0xabc"
    pin = insert_pin(
        tmp_path,
        name="Louvre",
        latitude=48.8606,
        longitude=2.3376,
        city="Paris",
        country="France",
        raw_json=json.dumps({"Title": "Louvre", "URL": url}),
    )
    incoming = SavedLocation(
        id=str(uuid.uuid4()),
        name="Louvre Museum",
        latitude=0.0,
        longitude=0.0,
        list_name="Want to go",
        source_type="saved_list_csv",
        source_file="Want to go.csv",
        raw_json=json.dumps({"Title": "Louvre Museum", "URL": url}),
    )
    repo = PinRepository(tmp_path / "pins.db")
    stats = repo.upsert_pins_batch([incoming])
    assert stats["updated"] == 1
    updated = PinService(tmp_path / "pins.db").get_pin_details(pin.id)
    assert updated is not None
    assert updated.latitude == pytest.approx(48.8606)
    assert updated.longitude == pytest.approx(2.3376)
    assert updated.name == "Louvre Museum"
    assert updated.country == "France"


def test_fill_missing_coordinates_from_cid_mocks_http(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = (
        "https://www.google.com/maps/place/Cape+Roca/"
        "data=!4m2!3m1!1s0xd1edac0235d438d:0x953ad8a898fcb3af"
    )
    missing = insert_pin(
        tmp_path,
        name="Cape Roca",
        latitude=0.0,
        longitude=0.0,
        city=None,
        country=None,
        raw_json=json.dumps({"Title": "Cape Roca", "URL": url}),
    )
    already = insert_pin(
        tmp_path,
        name="Eiffel Tower",
        latitude=48.8584,
        longitude=2.2945,
        city="Paris",
        country="France",
        raw_json=json.dumps(
            {
                "Title": "Eiffel Tower",
                "URL": "https://www.google.com/maps/place/Eiffel/data=!4m2!3m1!1s0x0:0x2",
            }
        ),
    )

    def fake_cid(_url: str | None, **_kwargs: object) -> tuple[float, float] | None:
        return (38.7804, -9.4991)

    monkeypatch.setattr(
        "src_phase1.google_place_identity.resolve_coords_via_cid_embed",
        fake_cid,
    )
    pin_service = PinService(tmp_path / "pins.db")
    result = pin_service.fill_missing_coordinates_from_cid()
    assert result["updated"] == 1
    assert result["checked"] == 1
    filled = pin_service.get_pin_details(missing.id)
    assert filled is not None
    assert filled.latitude == pytest.approx(38.7804)
    assert filled.longitude == pytest.approx(-9.4991)
    untouched = pin_service.get_pin_details(already.id)
    assert untouched is not None
    assert untouched.latitude == pytest.approx(48.8584)


def test_backfill_places_fills_city_and_country(tmp_path: Path) -> None:
    pin = insert_pin(
        tmp_path,
        name="Tokyo Tower",
        city=None,
        country=None,
        latitude=35.6586,
        longitude=139.7454,
    )
    pin_service = PinService(tmp_path / "pins.db")

    result = pin_service.backfill_places()

    assert result["updated"] == 1
    updated = pin_service.get_pin_details(pin.id)
    assert updated is not None
    assert updated.city
    assert updated.country == "Japan"


def test_suggest_day_plan_uses_nearby_saved_places(tmp_path: Path) -> None:
    anchor = insert_pin(
        tmp_path,
        name="Tokyo National Museum",
        latitude=35.7188,
        longitude=139.7765,
    )
    insert_pin(
        tmp_path,
        name="Ueno Park",
        latitude=35.7148,
        longitude=139.7733,
    )
    pin_service = PinService(tmp_path / "pins.db")
    day_plan = ItineraryService(pin_service).suggest_day_plan(anchor)

    assert day_plan["anchor"]["name"] == "Tokyo National Museum"
    assert day_plan["morning"][0]["name"] == "Tokyo National Museum"
    assert any(stop["name"] == "Ueno Park" for stop in day_plan["afternoon"] + day_plan["evening"] + day_plan["optional"])
    assert day_plan["source"] == "nearby_saved_places"


def test_planning_links_include_destination_city(tmp_path: Path) -> None:
    pin = insert_pin(tmp_path, name="Senso-ji", city="Tokyo", country="Japan")
    database = AtlasDatabase(tmp_path / "atlas.db")
    database.migrate()
    service = PlanningService(PreferencesService(AtlasRepository(database)))
    resolution = AreaResolution("city-tokyo", "Tokyo", "city", "exact_city", 1.0, "atlas_knowledge")

    links = service.planning_links(pin, resolution)

    assert "Tokyo" in links["destination"]
    assert "Tokyo" in links["google_flights"] or "Tokyo" in links["booking"]
    assert links["booking"].startswith("https://www.booking.com/")
    assert links["airbnb"].startswith("https://www.airbnb.com/")


def test_streamlit_explorer_module_imports() -> None:
    module = importlib.import_module("travel_atlas.app_streamlit")
    assert callable(module.main)
