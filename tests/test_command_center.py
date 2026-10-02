"""Phase 3A Command Center — lifecycle, checklist, Today, logistics, budget."""

from __future__ import annotations

import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest

_TRAVEL = Path(__file__).parent.parent
if str(_TRAVEL) not in sys.path:
    sys.path.insert(0, str(_TRAVEL))

from src_phase1.models import SavedLocation
from src_phase1.pin_repository import PinRepository
from travel_atlas.database import SCHEMA_VERSION, AtlasDatabase
from travel_atlas.knowledge_loader import load_bundled_knowledge
from travel_atlas.planning import PlanningEngine, default_planning_config
from travel_atlas.providers import StubResult, StubTransitProvider, StubWeatherProvider
from travel_atlas.repository import AtlasRepository
from travel_atlas.services.budget_board_service import BudgetBoardService
from travel_atlas.services.destination_itinerary import DestinationItineraryService
from travel_atlas.services.itinerary_service import ItineraryService
from travel_atlas.services.knowledge_service import KnowledgeService
from travel_atlas.services.learning_queue_service import LearningQueueService
from travel_atlas.services.lifecycle_service import LifecycleService
from travel_atlas.services.logistics_service import LogisticsService
from travel_atlas.services.pin_service import PinService
from travel_atlas.services.preferences_service import PreferencesService
from travel_atlas.services.prep_service import PrepService
from travel_atlas.services.today_service import TodayService
from travel_atlas.services.trip_service import TripPlanService
from travel_atlas.services.types import Recommendation, TripDefinition


def _insert_pin(path: Path, **kwargs: object) -> SavedLocation:
    pin = SavedLocation(
        id=str(kwargs.get("id", uuid.uuid4())),
        name=str(kwargs.get("name", "Place")),
        latitude=float(kwargs.get("latitude", 35.68)),
        longitude=float(kwargs.get("longitude", 139.76)),
        city=kwargs.get("city", "Tokyo"),  # type: ignore[arg-type]
        country=kwargs.get("country", "Japan"),  # type: ignore[arg-type]
        list_name="Want To Go",
        notes=kwargs.get("notes"),  # type: ignore[arg-type]
        category=kwargs.get("category"),  # type: ignore[arg-type]
        source_type="test",
        source_file="test.json",
        raw_json="{}",
        user_priority=5,
    )
    PinRepository(path).insert_pin(pin)
    return pin


def _stack(tmp_path: Path):
    atlas = AtlasDatabase(tmp_path / "atlas.db")
    atlas.migrate()
    assert atlas.connect().execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    repo = AtlasRepository(atlas)
    load_bundled_knowledge(repo)
    pins_path = tmp_path / "pins.db"
    pin_service = PinService(pins_path)
    knowledge = KnowledgeService(repo)
    prefs = PreferencesService(repo)
    itinerary = DestinationItineraryService(pin_service, ItineraryService(pin_service))
    trips = TripPlanService(repo, itinerary, knowledge)
    lifecycle = LifecycleService(repo)
    prep = PrepService(repo)
    learning = LearningQueueService(repo)
    logistics = LogisticsService()
    budget = BudgetBoardService(repo)
    today = TodayService(repo, trips, lifecycle, prep, learning)
    engine = PlanningEngine(
        pin_service=pin_service,
        knowledge_service=knowledge,
        preferences_service=prefs,
        itinerary_service=itinerary,
        config=default_planning_config(),
    )
    return {
        "repo": repo,
        "pins_path": pins_path,
        "pin_service": pin_service,
        "trips": trips,
        "lifecycle": lifecycle,
        "prep": prep,
        "learning": learning,
        "logistics": logistics,
        "budget": budget,
        "today": today,
        "engine": engine,
        "prefs": prefs,
    }


def _japan_trip(trips: TripPlanService, *, days_until: int = 87, day_count: int = 10):
    departure = date.today() + timedelta(days=days_until)
    return trips.create_trip(
        name="Japan Prep",
        destinations=[
            {
                "kind": "country",
                "label": "Japan",
                "day_count": day_count,
                "start_date": departure.isoformat(),
            }
        ],
        definition={
            "departure_date": departure.isoformat(),
            "budget": 2500,
            "pace": "medium",
            "energy": "medium",
        },
    )


def test_schema_v10_tables(tmp_path: Path) -> None:
    s = _stack(tmp_path)
    with s["repo"].database.connect() as conn:
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "trip_checklist_item" in names
    assert "trip_budget_line" in names
    assert "trip_mission_log" in names


def test_stage_planning_at_87_days_without_commitment(tmp_path: Path) -> None:
    s = _stack(tmp_path)
    trip = _japan_trip(s["trips"], days_until=87)
    life = s["lifecycle"].resolve(trip, today=date.today())
    assert life["stage"] == "planning"
    assert life["days_until"] == 87
    assert life["prep_band"] == "90"


def test_stage_preparation_when_committed(tmp_path: Path) -> None:
    from travel_atlas.services.reservation_service import ReservationService

    s = _stack(tmp_path)
    trip = _japan_trip(s["trips"], days_until=87)
    ReservationService(s["repo"]).create(
        trip["id"], kind="hotel", title="Hotel", status="reserved"
    )
    trip = s["trips"].get_trip(trip["id"])
    life = s["lifecycle"].resolve(trip, today=date.today())
    assert life["stage"] == "preparation"
    assert life["is_committed"] is True


def test_stage_travel_mid_trip(tmp_path: Path) -> None:
    s = _stack(tmp_path)
    trip = _japan_trip(s["trips"], days_until=-2, day_count=10)
    life = s["lifecycle"].resolve(trip, today=date.today())
    assert life["stage"] == "traveling"
    assert life["prep_band"] == "travel"


def test_stage_completed_after_return(tmp_path: Path) -> None:
    s = _stack(tmp_path)
    # Departed 20 days ago, 5-day trip → returned 15 days ago
    trip = _japan_trip(s["trips"], days_until=-20, day_count=5)
    life = s["lifecycle"].resolve(trip, today=date.today())
    assert life["stage"] == "completed"


def test_checklist_seeded_and_completion_updates_score(tmp_path: Path) -> None:
    s = _stack(tmp_path)
    trip = _japan_trip(s["trips"], days_until=87)
    progress = s["prep"].progress(trip["id"], "90")
    assert progress["total"] >= 5
    assert progress["prep_score"] == 0.0
    first = progress["items"][0]
    s["prep"].toggle(trip["id"], first["key"], True)
    after = s["prep"].progress(trip["id"], "90")
    assert after["done"] == 1
    assert after["prep_score"] > 0


def test_today_missions_nonempty(tmp_path: Path) -> None:
    from travel_atlas.services.reservation_service import ReservationService

    s = _stack(tmp_path)
    _insert_pin(s["pins_path"], name="Tokyo Station", category="train station")
    trip = _japan_trip(s["trips"], days_until=87)
    ReservationService(s["repo"]).create(
        trip["id"], kind="hotel", title="Hotel", status="reserved"
    )
    trip = s["trips"].get_trip(trip["id"])
    s["trips"].set_active_focus(trip["id"])
    dash = s["today"].build(interests=["museum_history"])
    assert dash["has_trip"] is True
    assert dash["missions"]
    assert dash["lesson"]["estimated_minutes"] >= 1
    assert "prep_score" in dash


def test_logistics_card_has_stub_status(tmp_path: Path) -> None:
    s = _stack(tmp_path)
    pin = _insert_pin(s["pins_path"], name="Tokyo National Museum", category="museum")
    hotel = _insert_pin(
        s["pins_path"],
        name="Hotel Base",
        category="hotel",
        latitude=35.67,
        longitude=139.75,
    )
    rec = Recommendation(
        title=pin.name,
        category="museum_history",
        location="Tokyo, Japan",
        estimated_duration_hours=2.0,
        estimated_cost=15.0,
        confidence=0.8,
        explanation="test",
        score=80.0,
        signals={},
        source_refs={"pin_id": pin.id},
    )
    card = s["logistics"].enrich(
        rec,
        pins=[pin, hotel],
        hotel_lat=hotel.latitude,
        hotel_lng=hotel.longitude,
    )
    assert card["provider_status"] == "stub"
    assert "opening_hours" in card
    assert card["walking_minutes"] is not None
    assert card["how_to_get_there"]


def test_budget_confidence_rises_with_actual(tmp_path: Path) -> None:
    s = _stack(tmp_path)
    trip = _japan_trip(s["trips"], days_until=60)
    s["budget"].seed_from_plan(trip["id"], trip_budget=2500, day_count=10)
    board = s["budget"].board(trip["id"])
    food = next(c for c in board["categories"] if c["category"] == "food")
    assert food["confidence"] == 40.0
    s["budget"].set_actual(trip["id"], "food", food["label"], 400.0)
    board2 = s["budget"].board(trip["id"])
    food2 = next(c for c in board2["categories"] if c["category"] == "food")
    assert food2["confidence"] == 95.0
    assert food2["actual"] == 400.0


def test_providers_return_stub_without_network() -> None:
    transit = StubTransitProvider().route(
        from_lat=35.68, from_lng=139.76, to_lat=35.71, to_lng=139.78
    )
    assert isinstance(transit, StubResult)
    assert transit.status == "stub"
    weather = StubWeatherProvider().forecast(latitude=35.68, longitude=139.76)
    assert weather.status == "stub"


def test_engine_claims_unchanged_during_command_center(tmp_path: Path) -> None:
    s = _stack(tmp_path)
    _insert_pin(s["pins_path"], name="Meiji Shrine", category="shrine")
    trip = _japan_trip(s["trips"], days_until=40)
    before = s["repo"].list_claims("country-jp")
    before_ids = {c["id"] for c in before}
    s["today"].build(trip=trip)
    report = s["engine"].plan(
        destination_kind="country",
        destination_label="Japan",
        trip=TripDefinition(
            destination_kind="country",
            destination_label="Japan",
            day_count=5,
            start_date=trip["definition"]["departure_date"],
        ),
    )
    s["logistics"].enrich(report.experiences[0], pins=s["pin_service"].list_pins()) if report.experiences else None
    after = s["repo"].list_claims("country-jp")
    assert {c["id"] for c in after} == before_ids


def test_value_blurb() -> None:
    text = BudgetBoardService.value_blurb(
        added_cost=50, trip_budget=2500, coverage_gain_pct=14
    )
    assert "2%" in text or "2%" in text.replace(" ", "")
    assert "14%" in text
