"""Tests for calendar-date threading through itinerary building and trip plans."""

from __future__ import annotations

import sys
import uuid
from datetime import date
from pathlib import Path

_TRAVEL = Path(__file__).parent.parent
if str(_TRAVEL) not in sys.path:
    sys.path.insert(0, str(_TRAVEL))

from src_phase1.models import SavedLocation
from src_phase1.pin_repository import PinRepository
from travel_atlas.database import AtlasDatabase
from travel_atlas.knowledge_loader import load_bundled_knowledge
from travel_atlas.repository import AtlasRepository
from travel_atlas.services.destination_itinerary import DestinationItineraryService
from travel_atlas.services.itinerary_service import ItineraryService
from travel_atlas.services.pin_service import PinService
from travel_atlas.services.trip_service import TripPlanService


def insert_pin(tmp_path: Path, **kwargs: object) -> SavedLocation:
    pin = SavedLocation(
        id=str(uuid.uuid4()),
        name=str(kwargs.get("name", "Tokyo National Museum")),
        latitude=float(kwargs.get("latitude", 35.7219)),
        longitude=float(kwargs.get("longitude", 139.7758)),
        city=kwargs.get("city", "Tokyo"),
        country=kwargs.get("country", "Japan"),
        list_name="Want To Go",
        source_type="test",
        source_file="test.json",
        raw_json="{}",
    )
    PinRepository(tmp_path / "pins.db").insert_pin(pin)
    return pin


def make_destination_itinerary_service(tmp_path: Path) -> DestinationItineraryService:
    insert_pin(tmp_path)
    pin_service = PinService(tmp_path / "pins.db")
    return DestinationItineraryService(pin_service, ItineraryService(pin_service))


def make_trip_service(tmp_path: Path) -> TripPlanService:
    insert_pin(tmp_path, name="Tokyo Tower", city="Tokyo", country="Japan")
    insert_pin(tmp_path, name="Almaty Central Mosque", city="Almaty", country="Kazakhstan")
    atlas_database = AtlasDatabase(tmp_path / "atlas.db")
    atlas_database.migrate()
    repository = AtlasRepository(atlas_database)
    load_bundled_knowledge(repository)
    pin_service = PinService(tmp_path / "pins.db")
    itinerary_service = DestinationItineraryService(pin_service, ItineraryService(pin_service))
    return TripPlanService(repository, itinerary_service)


def test_build_destination_itinerary_dates_are_sequential(tmp_path: Path) -> None:
    service = make_destination_itinerary_service(tmp_path)

    itinerary = service.build_destination_itinerary(
        destination_kind="country", destination_label="Japan", days=3, start_date=date(2026, 5, 24)
    )

    assert [day["date"] for day in itinerary["days"]] == ["2026-05-24", "2026-05-25", "2026-05-26"]


def test_build_destination_itinerary_without_start_date_is_back_compatible(tmp_path: Path) -> None:
    service = make_destination_itinerary_service(tmp_path)

    itinerary = service.build_destination_itinerary(
        destination_kind="country", destination_label="Japan", days=2
    )

    assert all(day["date"] is None for day in itinerary["days"])


def test_trip_plan_round_trips_start_date_and_auto_chains(tmp_path: Path) -> None:
    trip_service = make_trip_service(tmp_path)

    trip = trip_service.create_trip(
        name="Silk Road",
        destinations=[
            {"kind": "country", "label": "Japan", "day_count": 2, "start_date": "2026-05-20"},
            {"kind": "country", "label": "Kazakhstan", "day_count": 3},
        ],
    )

    reloaded = trip_service.get_trip(trip["id"])
    japan_leg, kazakhstan_leg = reloaded["destinations"]
    assert japan_leg["resolved_start_date"] == "2026-05-20"
    assert kazakhstan_leg["resolved_start_date"] == "2026-05-22"  # chained after 2-day Japan leg

    dates = [day["date"] for day in reloaded["days"]]
    assert dates == ["2026-05-20", "2026-05-21", "2026-05-22", "2026-05-23", "2026-05-24"]


def test_trip_with_no_dates_returns_none_everywhere(tmp_path: Path) -> None:
    trip_service = make_trip_service(tmp_path)

    trip = trip_service.create_trip(
        name="Someday",
        destinations=[{"kind": "country", "label": "Japan", "day_count": 2}],
    )
    reloaded = trip_service.get_trip(trip["id"])

    assert reloaded["destinations"][0]["resolved_start_date"] is None
    assert all(day["date"] is None for day in reloaded["days"])
