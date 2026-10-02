"""Stay-put Alaska opener: LAX, Fairbanks hotel, aurora nights — no Denali."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

_TRAVEL = Path(__file__).parent.parent
if str(_TRAVEL) not in sys.path:
    sys.path.insert(0, str(_TRAVEL))

from travel_atlas.database import AtlasDatabase
from travel_atlas.knowledge_loader import load_bundled_knowledge
from travel_atlas.repository import AtlasRepository
from travel_atlas.services.alaska_aurora import (
    FLIGHT_TITLE,
    HOTEL_TITLE,
    OPENER_VERSION,
    apply_alaska_aurora,
    book_first_items,
    build_stayput_itinerary,
    should_apply,
)
from travel_atlas.services.alaska_bases import get_base
from travel_atlas.services.destination_itinerary import DestinationItineraryService
from travel_atlas.services.itinerary_service import ItineraryService
from travel_atlas.services.pin_service import PinService
from travel_atlas.services.prep_service import PrepService
from travel_atlas.services.reservation_service import ReservationService
from travel_atlas.services.trip_service import TripPlanService


def _stack(tmp_path: Path) -> dict:
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
    }


def _alaska_trip(trips: TripPlanService) -> dict:
    start = date(2026, 9, 9)
    end = date(2026, 9, 13)
    return trips.create_trip(
        name="Alaska Northern Lights",
        destinations=[
            {
                "kind": "us_state",
                "label": "Alaska",
                "day_count": 4,
                "start_date": start.isoformat(),
            }
        ],
        definition={
            "departure_date": start.isoformat(),
            "return_date": end.isoformat(),
            "alaska_aurora": OPENER_VERSION,
            "aurora_base": "fairbanks",
            "home_city": "Los Angeles",
            "home_airport": "LAX",
        },
    )


def test_should_apply_then_seeds_lax_not_seattle(tmp_path: Path) -> None:
    s = _stack(tmp_path)
    trip = _alaska_trip(s["trips"])
    assert should_apply(trip) is True
    first = apply_alaska_aurora(
        s["trips"], s["reservations"], trip_id=trip["id"], prep_service=s["prep"]
    )
    assert first["applied"] is True
    titles = [r["title"] for r in s["reservations"].list_for_trip(trip["id"])]
    assert FLIGHT_TITLE in titles
    assert HOTEL_TITLE in titles
    flight = next(r for r in s["reservations"].list_for_trip(trip["id"]) if r["kind"] == "flight")
    notes = flight.get("notes") or ""
    url = flight.get("booking_url") or ""
    assert "Los Angeles" in notes or "LAX" in notes
    assert "from Seattle" not in notes
    assert "LAX" in url or "Los" in url
    assert first["trip"]["definition"]["alaska_aurora_seeded"] is True
    assert first["trip"]["definition"]["aurora_base"] == "fairbanks"
    assert first["trip"]["committed_at"] is None

    second = apply_alaska_aurora(s["trips"], s["reservations"], trip_id=trip["id"])
    assert second["applied"] is False
    assert len(s["reservations"].list_for_trip(trip["id"])) == len(titles)


def test_legacy_healy_base_resolves_to_fairbanks() -> None:
    base = get_base("healy")
    assert base.key == "fairbanks"
    assert base.label == "Fairbanks"


def test_stayput_itinerary_is_fairbanks_aurora_not_denali() -> None:
    itinerary = build_stayput_itinerary(
        start_date=date(2026, 9, 9), day_count=4, base_key="fairbanks"
    )
    assert itinerary["destination_label"] == "Alaska"
    assert len(itinerary["days"]) == 4
    names = [
        stop["name"]
        for day in itinerary["days"]
        for stop in day["morning"] + day["afternoon"] + day["evening"] + day.get("optional", [])
    ]
    assert any("Aurora" in name for name in names)
    assert any("Fairbanks" in name for name in names)
    assert not any("Denali" in name for name in names)
    assert all(stop.get("pin_id") is None for day in itinerary["days"] for stop in day["morning"])
    assert "Fairbanks aurora" in itinerary["message"]


def test_get_trip_uses_stayput_days(tmp_path: Path) -> None:
    s = _stack(tmp_path)
    trip = _alaska_trip(s["trips"])
    apply_alaska_aurora(s["trips"], s["reservations"], trip_id=trip["id"])
    loaded = s["trips"].get_trip(trip["id"])
    assert len(loaded["destinations"]) == 1
    assert loaded["destinations"][0]["destination_label"] == "Alaska"
    assert len(loaded["days"]) == 4
    assert loaded["days"][0]["date"] == "2026-09-09"
    morning = [stop["name"] for stop in loaded["days"][0]["morning"]]
    assert morning[0].startswith("Land FAI")
    assert "LAX" in morning[0]


def test_book_first_is_flight_hotel_car(tmp_path: Path) -> None:
    s = _stack(tmp_path)
    trip = _alaska_trip(s["trips"])
    apply_alaska_aurora(s["trips"], s["reservations"], trip_id=trip["id"])
    items = book_first_items(s["reservations"].list_for_trip(trip["id"]))
    assert [i["key"] for i in items] == ["flight_lax", "hotel_stay", "car_airport"]
    assert items[0]["status"] == "book_now"
    assert "Fairbanks" in (items[1].get("booking_url") or "")


def test_three_day_window_still_stayput() -> None:
    itinerary = build_stayput_itinerary(
        start_date=date(2026, 9, 10), day_count=3, base_key="fairbanks"
    )
    assert len(itinerary["days"]) == 3
    last = itinerary["days"][-1]
    assert last["day"] == 3
    assert any("LAX" in stop["name"] for stop in last["morning"])
