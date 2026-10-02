"""Architecture foundation — modes, lifecycle, reservations, regions, photos."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

_TRAVEL = Path(__file__).parent.parent
if str(_TRAVEL) not in sys.path:
    sys.path.insert(0, str(_TRAVEL))

from travel_atlas.database import SCHEMA_VERSION, AtlasDatabase
from travel_atlas.knowledge_loader import load_bundled_knowledge
from travel_atlas.providers import (
    StubAstrologyProvider,
    StubBookingProvider,
    StubLanguageProvider,
    StubPhotoProvider,
    StubResult,
    StubShoppingProvider,
)
from travel_atlas.repository import AtlasRepository
from travel_atlas.services.destination_itinerary import DestinationItineraryService
from travel_atlas.services.itinerary_service import ItineraryService
from travel_atlas.services.learning_queue_service import LearningQueueService
from travel_atlas.services.lifecycle_service import LifecycleService
from travel_atlas.services.mode_service import ModeService
from travel_atlas.services.photo_service import PhotoService
from travel_atlas.services.pin_service import PinService
from travel_atlas.services.prep_service import PrepService
from travel_atlas.services.reservation_service import ReservationService
from travel_atlas.services.today_service import TodayService
from travel_atlas.services.travel_pack_service import TravelPackService
from travel_atlas.services.trip_service import TripPlanService


def _stack(tmp_path: Path):
    atlas = AtlasDatabase(tmp_path / "atlas.db")
    atlas.migrate()
    assert atlas.connect().execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    repo = AtlasRepository(atlas)
    load_bundled_knowledge(repo)
    pins_path = tmp_path / "pins.db"
    pin_service = PinService(pins_path)
    itinerary = DestinationItineraryService(pin_service, ItineraryService(pin_service))
    trips = TripPlanService(repo, itinerary)
    lifecycle = LifecycleService(repo)
    prep = PrepService(repo)
    learning = LearningQueueService(repo)
    reservations = ReservationService(repo)
    photos = PhotoService(repo)
    today = TodayService(repo, trips, lifecycle, prep, learning, reservations, photos)
    modes = ModeService(repo, trips, lifecycle)
    pack = TravelPackService(repo, trips, reservations, photos)
    return {
        "repo": repo,
        "trips": trips,
        "lifecycle": lifecycle,
        "prep": prep,
        "reservations": reservations,
        "photos": photos,
        "today": today,
        "modes": modes,
        "pack": pack,
        "learning": learning,
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


def test_schema_v11_tables(tmp_path: Path) -> None:
    s = _stack(tmp_path)
    with s["repo"].database.connect() as conn:
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(trip_plan)").fetchall()
        }
    assert "reservation" in names
    assert "trip_photo" in names
    assert "parent_trip_id" in cols
    assert "committed_at" in cols
    assert "active_focus" in cols
    assert SCHEMA_VERSION == 14


def test_planning_without_commitment(tmp_path: Path) -> None:
    s = _stack(tmp_path)
    trip = _japan_trip(s["trips"], days_until=87)
    life = s["lifecycle"].resolve(trip, today=date.today(), is_committed=False)
    assert life["stage"] == "planning"
    assert life["is_committed"] is False
    assert life["prep_band"] == "90"


def test_commitment_via_hotel_reservation(tmp_path: Path) -> None:
    s = _stack(tmp_path)
    trip = _japan_trip(s["trips"], days_until=87)
    s["reservations"].create(
        trip["id"],
        kind="hotel",
        title="Shibuya Hotel",
        status="reserved",
    )
    trip2 = s["trips"].get_trip(trip["id"])
    assert trip2["committed_at"]
    life = s["lifecycle"].resolve(trip2, today=date.today())
    assert life["stage"] == "preparation"
    assert life["is_committed"] is True


def test_committed_far_out_stays_committed(tmp_path: Path) -> None:
    s = _stack(tmp_path)
    trip = _japan_trip(s["trips"], days_until=120)
    s["reservations"].create(
        trip["id"], kind="flight", title="NRT flight", status="reserved"
    )
    trip2 = s["trips"].get_trip(trip["id"])
    life = s["lifecycle"].resolve(trip2, today=date.today())
    assert life["stage"] == "committed"


def test_traveling_and_completed_remembered(tmp_path: Path) -> None:
    s = _stack(tmp_path)
    trip = _japan_trip(s["trips"], days_until=-2, day_count=10)
    s["trips"].mark_committed(trip["id"])
    trip = s["trips"].get_trip(trip["id"])
    life = s["lifecycle"].resolve(trip, today=date.today())
    assert life["stage"] == "traveling"

    past = _japan_trip(s["trips"], days_until=-20, day_count=5)
    s["trips"].mark_committed(past["id"])
    past = s["trips"].get_trip(past["id"])
    life2 = s["lifecycle"].resolve(past, today=date.today(), journal_count=0)
    assert life2["stage"] == "completed"

    s["photos"].add(past["id"], caption="Louvre afternoon")
    life3 = s["lifecycle"].resolve(
        past, today=date.today(), journal_count=0, photo_count=1
    )
    assert life3["stage"] == "remembered"


def test_reservation_opening_soon_card(tmp_path: Path) -> None:
    s = _stack(tmp_path)
    trip = _japan_trip(s["trips"])
    opens = date.today() + timedelta(days=12)
    s["reservations"].create(
        trip["id"],
        kind="museum",
        title="Louvre",
        status="available_soon",
        opens_on=opens.isoformat(),
    )
    soon = s["reservations"].opening_soon(trip["id"])
    assert len(soon) == 1
    assert soon[0]["days_until_open"] == 12
    cards = s["reservations"].cards_for_trip(trip["id"])
    assert cards[0]["action_label"] == "Opens in 12 days"


def test_region_parent_and_budget_rollup(tmp_path: Path) -> None:
    s = _stack(tmp_path)
    region = s["trips"].create_region(name="West Europe 2026")
    assert region["kind"] == "region"
    fr = s["trips"].create_trip(
        name="France",
        destinations=[{"kind": "country", "label": "France", "day_count": 5}],
        parent_trip_id=region["id"],
        definition={"budget": 1000},
    )
    es = s["trips"].create_trip(
        name="Spain",
        destinations=[{"kind": "country", "label": "Spain", "day_count": 4}],
        parent_trip_id=region["id"],
        definition={"budget": 800},
    )
    children = s["trips"].list_child_trips(region["id"])
    assert {c["name"] for c in children} == {"France", "Spain"}
    rollup = s["trips"].region_budget_rollup(region["id"])
    assert rollup["child_count"] == 2
    assert rollup["estimated_total"] > 0
    parent = s["trips"].get_trip(region["id"])
    assert len(parent["children"]) == 2
    assert fr["parent_trip_id"] == region["id"]
    assert es["parent_trip_id"] == region["id"]


def test_create_trip_allows_uk_nation_destination_kind(tmp_path: Path) -> None:
    s = _stack(tmp_path)
    trip = s["trips"].create_trip(
        name="West Europe trip",
        destinations=[
            {"kind": "uk_nation", "label": "England", "day_count": 2},
            {"kind": "uk_nation", "label": "Scotland", "day_count": 1},
            {"kind": "country", "label": "France", "day_count": 2},
        ],
    )
    kinds = [d["destination_kind"] for d in trip["destinations"]]
    assert kinds == ["uk_nation", "uk_nation", "country"]
    assert trip["destinations"][0]["destination_label"] == "England"


def test_today_requires_committed_active_trip(tmp_path: Path) -> None:
    s = _stack(tmp_path)
    trip = _japan_trip(s["trips"], days_until=87)
    dash = s["today"].build(trip=trip)
    assert dash["has_trip"] is False
    assert dash.get("requires_commitment") is True

    s["reservations"].create(
        trip["id"], kind="hotel", title="Hotel", status="reserved"
    )
    trip2 = s["trips"].get_trip(trip["id"])
    s["trips"].set_active_focus(trip2["id"])
    dash2 = s["today"].build()
    assert dash2["has_trip"] is True
    assert dash2["lifecycle"]["stage"] == "preparation"


def test_mode_isolation_research_vs_active(tmp_path: Path) -> None:
    s = _stack(tmp_path)
    _japan_trip(s["trips"], days_until=200)
    resolved = s["modes"].resolve()
    assert resolved["mode"] in ("research", "planning")
    assert resolved["today_eligible"] is False

    trip = _japan_trip(s["trips"], days_until=40)
    s["reservations"].create(
        trip["id"], kind="flight", title="Flight", status="reserved"
    )
    s["trips"].set_active_focus(trip["id"])
    s["modes"].set_mode("active_trip")
    resolved2 = s["modes"].resolve()
    assert resolved2["today_eligible"] is True
    assert resolved2["default_page"] == "today"
    assert any(t["id"] == trip["id"] for t in resolved2["active_trips"])


def test_photos_first_class(tmp_path: Path) -> None:
    s = _stack(tmp_path)
    trip = _japan_trip(s["trips"])
    photo = s["photos"].add(
        trip["id"],
        caption="Tokyo tower",
        local_path="/tmp/tokyo.jpg",
        day_number=2,
        latitude=35.65,
        longitude=139.74,
    )
    assert photo["caption"] == "Tokyo tower"
    assert s["photos"].count_for_trip(trip["id"]) == 1
    listed = s["photos"].list_for_trip(trip["id"])
    assert listed[0]["day_number"] == 2


def test_travel_pack_manifest(tmp_path: Path) -> None:
    s = _stack(tmp_path)
    trip = _japan_trip(s["trips"])
    s["reservations"].create(
        trip["id"], kind="hotel", title="Hotel", status="reserved"
    )
    s["photos"].add(trip["id"], caption="Pack test")
    manifest = s["pack"].build_manifest(trip["id"])
    assert manifest["trip_id"] == trip["id"]
    assert len(manifest["reservations"]) == 1
    assert len(manifest["photos"]) == 1
    assert manifest["content_hash"]
    assert s["pack"].is_stale(trip["id"], "old-hash") is True
    assert s["pack"].is_stale(trip["id"], manifest["content_hash"]) is False


def test_provider_extension_stubs() -> None:
    booking = StubBookingProvider().search(destination="Kyoto", kind="hotel")
    assert isinstance(booking, StubResult)
    assert "booking" in booking.links
    lang = StubLanguageProvider().next_lesson(
        destination="Japan", locality="Kyoto"
    )
    assert lang.payload["locality_first"] is True
    assert StubShoppingProvider().recommendations(destination="Japan").status == "unavailable"
    assert StubAstrologyProvider().signals(destination="Japan").status == "unavailable"
    assert StubPhotoProvider().list_candidates(trip_id="x").status == "stub"


def test_legacy_stage_override_maps(tmp_path: Path) -> None:
    s = _stack(tmp_path)
    trip = _japan_trip(s["trips"], days_until=87)
    trip["definition"]["stage_override"] = "dream"
    life = s["lifecycle"].resolve(trip, today=date.today())
    assert life["stage"] == "idea"


def test_primary_traveler_is_primary(tmp_path: Path) -> None:
    from travel_atlas.services.traveler_service import (
        PRIMARY_DISPLAY_NAME,
        TravelerService,
    )

    s = _stack(tmp_path)
    primary = TravelerService(s["repo"]).ensure_primary()
    assert primary["display_name"] == PRIMARY_DISPLAY_NAME
    assert primary["birth_date"] == "2000-01-01"
    assert primary["birth_timezone"] == "America/Los_Angeles"
    again = TravelerService(s["repo"]).ensure_primary()
    assert again["id"] == primary["id"]
    assert again["display_name"] == PRIMARY_DISPLAY_NAME
