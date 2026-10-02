"""Offline tests for Nuitee hotel normalize + Aviasales fare parsing."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

_TRAVEL = Path(__file__).parent.parent
if str(_TRAVEL) not in sys.path:
    sys.path.insert(0, str(_TRAVEL))

from travel_atlas.env_loader import load_travel_env
from travel_atlas.providers.aviasales_flight import (
    aviasales_search_url,
    parse_prices_for_dates,
)
from travel_atlas.providers.base import StubResult
from travel_atlas.providers.nuitee_hotel import (
    NuiteeHotelProvider,
    _cheapest_rate,
    _is_two_queen_room,
)
from travel_atlas.services.flight_search import search_roundtrip_fares
from travel_atlas.services.hotel_compare import (
    normalize_nuitee_offer_row,
    sorted_by_price,
)
from travel_atlas.services.hotel_search import search_hotels_by_geocode


FAIRBANKS = (64.8378, -147.7164)


class _FakeNuitee:
    key = "nuitee-hotel-v1"

    def credentials_configured(self) -> bool:
        return True

    def search_by_geocode(self, **kwargs):
        near = {
            "hotelId": "lpFAI001",
            "name": "Aurora Inn",
            "geoCode": {"latitude": 64.8400, "longitude": -147.7200},
            "rating": 4.1,
        }
        far = {
            "hotelId": "lpFAI099",
            "name": "Too Far Lodge",
            "geoCode": {"latitude": 65.5000, "longitude": -148.5000},
            "rating": 4.5,
        }
        cheap = {
            "hotelId": "lpFAI002",
            "name": "Chena Road Motel",
            "geoCode": {"latitude": 64.8450, "longitude": -147.7000},
            "rating": 3.9,
        }
        return StubResult(
            provider="nuitee-hotel-v1",
            status="ok",
            payload={
                "message": "ok",
                "hotels": [near, far, cheap],
                "offers": [
                    {
                        "hotel": near,
                        "offers": [
                            {"id": "R1", "price": {"total": 420.0, "currency": "USD"}}
                        ],
                    },
                    {
                        "hotel": far,
                        "offers": [
                            {"id": "R9", "price": {"total": 200.0, "currency": "USD"}}
                        ],
                    },
                    {
                        "hotel": cheap,
                        "offers": [
                            {"id": "R2", "price": {"total": 310.0, "currency": "USD"}}
                        ],
                    },
                ],
            },
        )


class _FakeAviasales:
    partner_id = "test-marker"

    def credentials_configured(self) -> bool:
        return True

    def prices_for_dates(self, **kwargs):
        return StubResult(
            provider="aviasales-flight-v1",
            status="ok",
            payload={
                "message": "ok",
                "fares": parse_prices_for_dates(
                    {
                        "data": [
                            {
                                "price": 512,
                                "airline": "AS",
                                "departure_at": "2026-09-18T08:00:00",
                                "return_at": "2026-09-22T14:00:00",
                                "transfers": 1,
                                "duration": 420,
                                "origin": "LAX",
                                "destination": "FAI",
                                "currency": "usd",
                            },
                            {
                                "price": 389,
                                "airline": "AA",
                                "departure_at": "2026-09-18T06:30:00",
                                "return_at": "2026-09-22T20:00:00",
                                "transfers": 2,
                                "duration": 510,
                                "origin": "LAX",
                                "destination": "FAI",
                                "currency": "usd",
                            },
                        ]
                    }
                ),
                "origin": "LAX",
                "destination": "FAI",
                "search_url": "https://www.aviasales.com/search/LAX180926FAI2209262?marker=test-marker",
            },
            links={
                "aviasales": "https://www.aviasales.com/search/LAX180926FAI2209262?marker=test-marker"
            },
        )

    def get_latest_prices(self, **kwargs):
        return StubResult(
            provider="aviasales-flight-v1",
            status="ok",
            payload={"message": "ok", "fares": []},
        )

    def grouped_prices(self, **kwargs):
        return StubResult(
            provider="aviasales-flight-v1",
            status="ok",
            payload={"message": "ok", "fares": []},
        )


def test_load_travel_env_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "nope.env"
    assert load_travel_env(env_path=missing) is None


def test_load_travel_env_sets_missing_keys_only(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("NUITEE_API_KEY=sand_test\nALREADY=from_file\n", encoding="utf-8")
    monkeypatch.setenv("ALREADY", "from_os")
    monkeypatch.delenv("NUITEE_API_KEY", raising=False)
    assert load_travel_env(env_path=env_file) == env_file
    import os

    assert os.environ["NUITEE_API_KEY"] == "sand_test"
    assert os.environ["ALREADY"] == "from_os"


def test_nuitee_cheapest_rate_picks_lowest_retail() -> None:
    room_types = [
        {
            "offerId": "A",
            "rates": [
                {
                    "rateId": "r1",
                    "name": "King",
                    "retailRate": {"total": [{"amount": 500, "currency": "USD"}]},
                }
            ],
        },
        {
            "offerId": "B",
            "rates": [
                {
                    "rateId": "r2",
                    "name": "Queen",
                    "retailRate": {"total": [{"amount": 350.5, "currency": "USD"}]},
                }
            ],
        },
    ]
    best = _cheapest_rate(room_types)
    assert best is not None
    offer, amount, currency = best
    assert amount == 350.5
    assert currency == "USD"
    assert offer["id"] == "r2"


def test_normalize_nuitee_offer_row_fairbanks() -> None:
    hotel = {
        "hotelId": "lp1",
        "name": "Aurora Inn",
        "latitude": 64.84,
        "longitude": -147.72,
        "rating": 4.0,
        "main_photo": "https://cdn.example.com/aurora.jpg",
    }
    block = {
        "hotel": hotel,
        "offers": [
            {
                "id": "r1",
                "room_name": "2 Queen Beds Non-Smoking",
                "price": {"total": 400, "currency": "USD"},
            }
        ],
    }
    row = normalize_nuitee_offer_row(
        hotel,
        block,
        check_in="2026-09-18",
        check_out="2026-09-22",
        center=FAIRBANKS,
        radius_km=20.0,
        adults=2,
        city="Fairbanks, Alaska",
    )
    assert row is not None
    assert row["provider"] == "nuitee"
    assert row["room_name"] == "2 Queen Beds Non-Smoking"
    assert row["total_price"] == 400.0
    assert row["nightly_rate"] == 100.0
    assert row["nuitee_hotel_id"] == "lp1"
    assert row["photo_url"] == "https://cdn.example.com/aurora.jpg"
    assert row["booking_url"]


def test_search_hotels_nuitee_filters_by_radius() -> None:
    payload = search_hotels_by_geocode(
        latitude=FAIRBANKS[0],
        longitude=FAIRBANKS[1],
        check_in="2026-09-18",
        check_out="2026-09-22",
        radius_km=20.0,
        currency="USD",
        city="Fairbanks, Alaska",
        provider=_FakeNuitee(),
        include_google_lodging=False,
    )
    assert payload["ok"] is True
    names = {row["hotel_name"] for row in payload["hotels"]}
    assert "Aurora Inn" in names
    assert "Chena Road Motel" in names
    assert "Too Far Lodge" not in names
    assert sorted_by_price(payload["hotels"])[0]["hotel_name"] == "Chena Road Motel"
    assert "NUITEE" not in (payload.get("message") or "").upper() or payload["ok"]


def test_search_hotels_missing_nuitee_key_message() -> None:
    class _Empty:
        key = "nuitee-hotel-v1"

        def credentials_configured(self) -> bool:
            return False

        def search_by_geocode(self, **kwargs):
            raise AssertionError("should not call search")

    payload = search_hotels_by_geocode(
        latitude=FAIRBANKS[0],
        longitude=FAIRBANKS[1],
        check_in="2026-09-18",
        check_out="2026-09-22",
        provider=_Empty(),
        include_google_lodging=False,
        city="Fairbanks, Alaska",
    )
    assert payload["ok"] is False
    assert "NUITEE_API_KEY" in payload["message"]
    assert payload["area_links"]


def test_parse_prices_for_dates_sorts_by_price() -> None:
    fares = parse_prices_for_dates(
        {
            "data": [
                {"price": 500, "airline": "AS", "departure_at": "2026-09-18"},
                {"price": 300, "airline": "AA", "departure_at": "2026-09-18"},
            ]
        }
    )
    assert [f["price"] for f in fares] == [300.0, 500.0]
    assert fares[0]["airline"] == "AA"


def test_aviasales_search_url_includes_marker_and_adults() -> None:
    url = aviasales_search_url(
        origin="LAX",
        destination="FAI",
        depart=date(2026, 9, 18),
        return_on=date(2026, 9, 22),
        marker="abc123",
        adults=2,
    )
    assert "LAX180926FAI2209262" in url
    assert "marker=abc123" in url


def test_cheapest_rate_prefers_two_queen_room() -> None:
    room_types = [
        {
            "offerId": "cheap",
            "name": "Standard Queen",
            "rates": [
                {
                    "rateId": "r1",
                    "name": "Queen Room",
                    "retailRate": {"total": [{"amount": 300, "currency": "USD"}]},
                }
            ],
        },
        {
            "offerId": "two",
            "name": "Double Queen",
            "rates": [
                {
                    "rateId": "r2",
                    "name": "2 Queen Beds",
                    "retailRate": {"total": [{"amount": 340, "currency": "USD"}]},
                }
            ],
        },
    ]
    best = _cheapest_rate(room_types)
    assert best is not None
    offer, amount, _currency = best
    assert amount == 340.0
    assert "2 Queen" in offer["room_name"]
    assert _is_two_queen_room("Two Queen Beds Deluxe")


def test_search_roundtrip_fares_with_fake_provider() -> None:
    result = search_roundtrip_fares(
        origin="LAX",
        destination="FAI",
        depart=date(2026, 9, 18),
        return_on=date(2026, 9, 22),
        adults=2,
        provider=_FakeAviasales(),
    )
    assert result["ok"] is True
    assert result["fares"][0]["price"] == 389.0
    assert result["fares"][0]["total_for_party"] == 778.0
    assert result["adults"] == 2
    assert "2adults" in result["links"]["kayak"]
    assert "aviasales" in result["links"]
    assert "google_flights" in result["links"]
    assert "kayak" in result["links"]


def test_nuitee_provider_missing_credentials() -> None:
    client = NuiteeHotelProvider(api_key="")
    assert client.credentials_configured() is False
    result = client.search_by_geocode(
        latitude=64.8,
        longitude=-147.7,
        check_in="2026-09-18",
        check_out="2026-09-22",
    )
    assert result.status == "unavailable"
    assert "NUITEE_API_KEY" in (result.payload or {}).get("message", "")
