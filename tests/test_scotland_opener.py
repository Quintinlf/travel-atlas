"""Scotland Dundee opener: Days 1–3, booking seeds, pin buckets."""

from __future__ import annotations

import sys
import uuid
from datetime import date, timedelta
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
from travel_atlas.services.prep_service import PrepService
from travel_atlas.services.reservation_service import ReservationService
from travel_atlas.services.scotland_opener import (
    DAY1_CAPTION,
    OPENER_VERSION,
    apply_scotland_opener,
    book_first_items,
)
from travel_atlas.services.trip_map import travel_leg_for_pin
from travel_atlas.services.trip_service import TripPlanService


def _pin(**kwargs: object) -> SavedLocation:
    return SavedLocation(
        id=str(uuid.uuid4()),
        name=str(kwargs.get("name", "pin")),
        latitude=float(kwargs.get("latitude", 55.95)),
        longitude=float(kwargs.get("longitude", -3.19)),
        city=kwargs.get("city"),
        country=kwargs.get("country", "United Kingdom"),
        region=kwargs.get("region", "Scotland"),
        list_name="Want To Go",
        source_type="test",
        source_file="test.json",
        raw_json="{}",
    )


def _stack(tmp_path: Path):
    for pin in (
        _pin(name="National Museum of Scotland", city="Edinburgh"),
        _pin(name="David Hume Statue", city="Edinburgh"),
        _pin(name="Calton Hill", city="Edinburgh"),
        _pin(name="Arthur's Seat", city="Edinburgh"),
        _pin(name="Eagle Rock", city="Dalgety Bay", latitude=55.983, longitude=-3.309),
        _pin(name="University of St Andrews", city="Saint Andrews", latitude=56.34, longitude=-2.79),
        _pin(name="Glasgow", city="Glasgow", latitude=55.86, longitude=-4.25),
        _pin(name="Scone Palace", city="Perth", latitude=56.42, longitude=-3.44),
    ):
        PinRepository(tmp_path / "pins.db").insert_pin(pin)
    atlas = AtlasDatabase(tmp_path / "atlas.db")
    atlas.migrate()
    repo = AtlasRepository(atlas)
    load_bundled_knowledge(repo)
    pin_service = PinService(tmp_path / "pins.db")
    trips = TripPlanService(
        repo, DestinationItineraryService(pin_service, ItineraryService(pin_service))
    )
    return {
        "trips": trips,
        "reservations": ReservationService(repo),
        "prep": PrepService(repo),
        "pin_service": pin_service,
    }


def _west_europe_trip(trips: TripPlanService) -> dict:
    departure = date.today() + timedelta(days=90)
    return trips.create_trip(
        name="West Europe trip",
        destinations=[
            {"kind": "uk_nation", "label": "England", "day_count": 2, "start_date": departure.isoformat()},
            {"kind": "uk_nation", "label": "Scotland", "day_count": 1},
            {"kind": "country", "label": "France", "day_count": 2},
        ],
        definition={"departure_date": departure.isoformat()},
    )


def test_apply_puts_scotland_first_and_is_idempotent(tmp_path: Path) -> None:
    s = _stack(tmp_path)
    trip = _west_europe_trip(s["trips"])
    first = apply_scotland_opener(
        s["trips"], s["reservations"], trip_id=trip["id"], prep_service=s["prep"]
    )
    assert first["applied"] is True
    labels = [d["destination_label"] for d in first["trip"]["destinations"]]
    assert labels[0] == "Scotland"
    assert first["trip"]["destinations"][0]["day_count"] == 3
    assert first["trip"]["definition"]["scotland_opener"] == OPENER_VERSION

    titles = [r["title"] for r in s["reservations"].list_for_trip(trip["id"])]
    assert "Inbound flight to EDI (open-jaw)" in titles
    assert "Dundee hotel (1 night)" in titles
    assert "Glasgow hotel (2 nights)" in titles
    n = len(titles)

    second = apply_scotland_opener(
        s["trips"], s["reservations"], trip_id=trip["id"], prep_service=s["prep"]
    )
    assert second["applied"] is False
    assert len(s["reservations"].list_for_trip(trip["id"])) == n


def test_day_one_is_edi_landing_on_departure_date(tmp_path: Path) -> None:
    s = _stack(tmp_path)
    trip = _west_europe_trip(s["trips"])
    departure = trip["definition"]["departure_date"]
    apply_scotland_opener(s["trips"], s["reservations"], trip_id=trip["id"])
    loaded = s["trips"].get_trip(trip["id"])
    day1 = loaded["days"][0]
    assert day1["day"] == 1
    assert day1["date"] == departure
    assert day1["destination_label"] == "Scotland"
    morning_names = [stop["name"] for stop in day1["morning"]]
    assert morning_names[0].startswith("Land EDI")
    assert "National Museum of Scotland" in morning_names
    assert DAY1_CAPTION in (day1.get("message") or "")
    assert loaded["days"][1]["destination_label"] == "Scotland"
    assert loaded["days"][2]["destination_label"] == "Scotland"


def test_book_first_order_is_flight_car_dundee_glasgow(tmp_path: Path) -> None:
    s = _stack(tmp_path)
    trip = _west_europe_trip(s["trips"])
    apply_scotland_opener(s["trips"], s["reservations"], trip_id=trip["id"])
    items = book_first_items(s["reservations"].list_for_trip(trip["id"]))
    assert [i["key"] for i in items] == [
        "flight_edi",
        "car_edi",
        "hotel_dundee",
        "hotel_glasgow",
    ]
    flight = items[0]
    assert "EDI" in (flight.get("booking_url") or "")
    assert flight["status"] == "book_now"
    assert loaded_not_committed(s, trip["id"])


def loaded_not_committed(s: dict, trip_id: str) -> bool:
    loaded = s["trips"].get_trip(trip_id)
    return loaded.get("committed_at") is None


def test_travel_leg_splits_glasgow_from_car_loop() -> None:
    edinburgh = _pin(name="Calton Hill", city="Edinburgh")
    st_andrews = _pin(
        name="St Andrews Cathedral",
        city="Saint Andrews",
        latitude=56.34,
        longitude=-2.79,
    )
    glasgow = _pin(name="Glasgow", city="Glasgow", latitude=55.86, longitude=-4.25)
    assert travel_leg_for_pin(edinburgh) == "Scotland car loop (Dundee)"
    assert travel_leg_for_pin(st_andrews) == "Scotland car loop (Dundee)"
    assert travel_leg_for_pin(glasgow) == "Glasgow"


def test_checklist_includes_edi_booking_items(tmp_path: Path) -> None:
    s = _stack(tmp_path)
    trip = _west_europe_trip(s["trips"])
    apply_scotland_opener(
        s["trips"], s["reservations"], trip_id=trip["id"], prep_service=s["prep"]
    )
    keys = {item["key"] for item in s["prep"].checklist_for_band(trip["id"], "90")}
    assert "book_flight_edi" in keys
    assert "book_hotel_dundee" in keys
    assert "book_hotel_glasgow" in keys
