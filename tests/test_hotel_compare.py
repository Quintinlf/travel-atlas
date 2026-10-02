"""Offline tests for Edinburgh hotel compare helpers (no Amadeus network)."""

from __future__ import annotations

import sys
from pathlib import Path

_TRAVEL = Path(__file__).parent.parent
if str(_TRAVEL) not in sys.path:
    sys.path.insert(0, str(_TRAVEL))

from travel_atlas.services.hotel_compare import (
    EDINBURGH_CENTER,
    MAP_RADIUS_KM,
    build_summary,
    consumer_booking_links,
    distance_km_to_center,
    is_sleep_zone,
    normalize_amadeus_offer_row,
    passes_rating_filter,
    rank_hotel_rows,
    sorted_by_price,
    walking_km_to_waverley,
    within_radius,
)


def test_within_radius_old_town_vs_arthurs_seat() -> None:
    # Near Waverley / Old Town
    assert within_radius(55.9500, -3.1880)
    assert within_radius(55.9520, -3.1890)
    # Arthur's Seat trailhead is outside 0.8 km sleep radius
    assert not within_radius(55.9442, -3.1618)


def test_sleep_zone_two_km_includes_new_town_excludes_hill() -> None:
    assert is_sleep_zone(55.9500, -3.1880)
    # New Town / Canonmills-ish: outside 0.8 km, inside 2 km map window
    assert not within_radius(55.9580, -3.2010)
    assert is_sleep_zone(55.9580, -3.2010, radius_km=MAP_RADIUS_KM)
    assert not is_sleep_zone(55.9442, -3.1618, radius_km=MAP_RADIUS_KM)
    assert not is_sleep_zone(55.9300, -3.2200, radius_km=MAP_RADIUS_KM)


def test_walking_distance_positive() -> None:
    dist = walking_km_to_waverley(55.9500, -3.1880)
    assert dist > 0
    assert dist < 1.0


def test_passes_rating_filter_scales() -> None:
    ok, unknown = passes_rating_filter(None)
    assert ok and unknown
    assert passes_rating_filter(3.5, scale=5.0) == (True, False)
    assert passes_rating_filter(3.4, scale=5.0) == (False, False)
    assert passes_rating_filter(7.0, scale=10.0) == (True, False)
    assert passes_rating_filter(6.9, scale=10.0) == (False, False)
    # Infer 10-point scale when value > 5
    assert passes_rating_filter(8.2) == (True, False)
    assert passes_rating_filter(6.5) == (False, False)


def test_rank_prefers_cheaper_closer_and_rated() -> None:
    rows = [
        {
            "hotel_name": "Far Cheap",
            "total_price": 80.0,
            "distance_km_to_center": 0.75,
            "rating_unknown": False,
        },
        {
            "hotel_name": "Near Mid",
            "total_price": 100.0,
            "distance_km_to_center": 0.1,
            "rating_unknown": False,
        },
        {
            "hotel_name": "Unrated Bargain",
            "total_price": 50.0,
            "distance_km_to_center": 0.2,
            "rating_unknown": True,
        },
    ]
    ranked = rank_hotel_rows(rows)
    # Rated hotels before unrated
    assert ranked[0]["rating_unknown"] is False
    assert ranked[-1]["hotel_name"] == "Unrated Bargain"
    by_price = sorted_by_price(ranked)
    assert by_price[0]["hotel_name"] == "Unrated Bargain"
    summary = build_summary(ranked)
    assert summary["count"] == 3
    assert summary["lowest_rate"]["hotel_name"] == "Unrated Bargain"


def test_consumer_booking_links_include_dates() -> None:
    links = consumer_booking_links(
        "The Balmoral", check_in="2027-03-28", check_out="2027-03-29"
    )
    assert "booking.com" in links["booking"]
    assert "checkin=2027-03-28" in links["booking"]
    assert "checkout=2027-03-29" in links["booking"]
    assert "google.com/travel/hotels" in links["google_hotels"]
    assert "airbnb.com" in links["airbnb"]


def test_normalize_offer_row_filters_far_and_low_rating() -> None:
    hotel = {
        "hotelId": "HLEDI001",
        "name": "Far Low Rated",
        "geoCode": {"latitude": 55.9442, "longitude": -3.1618},
        "rating": 2.0,
    }
    offer = {
        "hotel": hotel,
        "offers": [{"id": "OFF1", "price": {"total": "90.00", "currency": "GBP"}}],
    }
    assert normalize_amadeus_offer_row(
        hotel, offer, check_in="2027-03-28", check_out="2027-03-29"
    ) is None

    near = {
        "hotelId": "HLEDI002",
        "name": "Near Good",
        "geoCode": {"latitude": 55.9505, "longitude": -3.1885},
        "rating": 4.2,
    }
    offer2 = {
        "hotel": near,
        "offers": [{"id": "OFF2", "price": {"total": "120.00", "currency": "GBP"}}],
    }
    row = normalize_amadeus_offer_row(
        near, offer2, check_in="2027-03-28", check_out="2027-03-29"
    )
    assert row is not None
    assert row["hotel_name"] == "Near Good"
    assert row["total_price"] == 120.0
    assert row["nightly_rate"] == 120.0
    assert row["currency"] == "GBP"
    assert row["distance_km_to_center"] <= 0.8
    assert row["provider"] == "amadeus"
    assert "booking.com" in row["booking_url"]
    # Center distance sanity
    assert distance_km_to_center(55.9505, -3.1885, center=EDINBURGH_CENTER) < 0.2

    hill_ok = {
        "hotelId": "HLEDI099",
        "name": "Crags Lodge",
        "geoCode": {"latitude": 55.9442, "longitude": -3.1618},
        "rating": 4.5,
    }
    hill_offer = {
        "hotel": hill_ok,
        "offers": [{"id": "OFF9", "price": {"total": "80.00", "currency": "GBP"}}],
    }
    assert (
        normalize_amadeus_offer_row(
            hill_ok, hill_offer, check_in="2027-03-28", check_out="2027-03-29"
        )
        is None
    )

    new_town = {
        "hotelId": "HLEDI003",
        "name": "New Town Bargain",
        "geoCode": {"latitude": 55.9580, "longitude": -3.2010},
        "rating": 3.8,
    }
    nt_offer = {
        "hotel": new_town,
        "offers": [{"id": "OFF3", "price": {"total": "90.00", "currency": "GBP"}}],
    }
    nt_row = normalize_amadeus_offer_row(
        new_town, nt_offer, check_in="2027-03-28", check_out="2027-03-29"
    )
    assert nt_row is not None
    assert nt_row["hotel_name"] == "New Town Bargain"
    assert nt_row["distance_km_to_center"] > 0.8
    assert nt_row["distance_km_to_center"] <= MAP_RADIUS_KM
