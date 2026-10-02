"""Offline tests for hotel search helpers (fake Amadeus, no network)."""

from __future__ import annotations

import sys
from pathlib import Path

_TRAVEL = Path(__file__).parent.parent
if str(_TRAVEL) not in sys.path:
    sys.path.insert(0, str(_TRAVEL))

from travel_atlas.providers.base import StubResult
from travel_atlas.services.hotel_search import (
    add_hotel_markers,
    build_hotel_search_map,
    hotel_marker_specs,
    search_hotels_by_geocode,
)


class _FakeAmadeus:
    key = "amadeus-hotel-v1"
    env = "test"

    def credentials_configured(self) -> bool:
        return True

    def search_by_geocode(self, **kwargs):
        near = {
            "hotelId": "HLEDI002",
            "name": "Near Good",
            "geoCode": {"latitude": 55.9505, "longitude": -3.1885},
            "rating": 4.2,
        }
        hill = {
            "hotelId": "HLEDI099",
            "name": "Crags Lodge",
            "geoCode": {"latitude": 55.9442, "longitude": -3.1618},
            "rating": 4.5,
        }
        new_town = {
            "hotelId": "HLEDI003",
            "name": "New Town Bargain",
            "geoCode": {"latitude": 55.9580, "longitude": -3.2010},
            "rating": 3.8,
        }
        return StubResult(
            provider="fake",
            status="ok",
            payload={
                "message": "ok",
                "hotels": [near, hill, new_town],
                "offers": [
                    {
                        "hotel": near,
                        "offers": [
                            {"id": "OFF2", "price": {"total": "120.00", "currency": "GBP"}}
                        ],
                    },
                    {
                        "hotel": hill,
                        "offers": [
                            {"id": "OFF9", "price": {"total": "80.00", "currency": "GBP"}}
                        ],
                    },
                    {
                        "hotel": new_town,
                        "offers": [
                            {"id": "OFF3", "price": {"total": "90.00", "currency": "GBP"}}
                        ],
                    },
                ],
            },
        )


def test_search_filters_arthurs_seat_keeps_new_town() -> None:
    payload = search_hotels_by_geocode(
        check_in="2027-03-28",
        check_out="2027-03-29",
        provider=_FakeAmadeus(),
        include_google_lodging=False,
    )
    assert payload["ok"] is True
    names = {row["hotel_name"] for row in payload["hotels"]}
    assert "Near Good" in names
    assert "New Town Bargain" in names
    assert "Crags Lodge" not in names
    cheapest = payload["sorted_by_price"][0]
    assert cheapest["hotel_name"] == "New Town Bargain"
    assert payload["area_links"]["airbnb"]
    assert "airbnb.com" in payload["area_links"]["airbnb"]


def test_hotel_marker_specs_and_map_attach_without_network() -> None:
    rows = [
        {
            "hotel_name": "Cheap Inn",
            "lat": 55.9505,
            "lon": -3.1885,
            "total_price": 80.0,
            "nightly_rate": 80.0,
            "currency": "GBP",
            "booking_url": "https://www.booking.com/searchresults.html?ss=Cheap",
        },
        {
            "hotel_name": "Pricey Hall",
            "lat": 55.9510,
            "lon": -3.1900,
            "total_price": 200.0,
            "nightly_rate": 200.0,
            "currency": "GBP",
        },
    ]
    specs = hotel_marker_specs(rows)
    assert len(specs) == 2
    by_name = {s["name"]: s for s in specs}
    assert by_name["Cheap Inn"]["color"] == "#15803d"
    assert by_name["Pricey Hall"]["color"] == "#b91c1c"
    fmap = build_hotel_search_map(rows)
    before = len(fmap._children)
    add_hotel_markers(fmap, rows)
    assert len(fmap._children) > before
