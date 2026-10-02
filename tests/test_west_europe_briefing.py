"""Tests for West Europe HTML trip briefing."""

from __future__ import annotations

import html as html_lib
import sys
from pathlib import Path
from types import SimpleNamespace

_TRAVEL = Path(__file__).parent.parent
if str(_TRAVEL) not in sys.path:
    sys.path.insert(0, str(_TRAVEL))

from travel_atlas.services.west_europe_briefing import (
    _hotel_maps_url,
    _pdf_safe_maps_url,
    _pin_maps_url,
    build_west_europe_briefing_html,
    load_leg_plan,
    load_scotland_hotels,
    total_planned_days,
)

_FAKE_ANGULAR = [
    {
        "body": "Sun",
        "angle": "mc",
        "kind": "meridian",
        "points": [[35.0, -5.0], [62.0, -5.0]],
    }
]
_FAKE_ASPECTS = [
    {
        "body": "Venus",
        "aspect": "trine",
        "line_kind": "aspect",
        "points": [[40.0, -10.0], [55.0, 8.0]],
    }
]


def _sample_pins() -> list:
    return [
        SimpleNamespace(
            name="Edinburgh Castle",
            city="Edinburgh",
            region="Scotland",
            country="United Kingdom",
            latitude=55.9486,
            longitude=-3.1999,
        ),
        SimpleNamespace(
            name="Glasgow",
            city="Glasgow",
            region="Scotland",
            country="United Kingdom",
            latitude=55.8642,
            longitude=-4.2518,
        ),
        SimpleNamespace(
            name="Tate Modern",
            city="London",
            region="England",
            country="United Kingdom",
            latitude=51.5076,
            longitude=-0.0994,
        ),
        SimpleNamespace(
            name="Bad overseas geocode",
            city="Belper",
            region="England",
            country="United Kingdom",
            latitude=17.9,
            longitude=102.6,
        ),
    ]


def test_leg_days_sum_to_seventy() -> None:
    plan = load_leg_plan()
    assert total_planned_days(plan) == 45
    assert sum(int(leg["days"]) for leg in plan["legs"]) == 45
    assert len(plan["legs"]) == 11
    assert all(leg.get("image_url") for leg in plan["legs"])


def test_scotland_hotels_have_shuttle_stars() -> None:
    hotels = load_scotland_hotels()
    starred = [
        h
        for city in hotels["cities"]
        for h in city["hotels"]
        if h.get("airport_shuttle")
    ]
    assert len(starred) >= 3
    assert any("Edinburgh" in (c.get("city") or "") for c in hotels["cities"])
    assert any("Glasgow" in (c.get("city") or "") for c in hotels["cities"])
    assert any("Dundee" in (c.get("city") or "") for c in hotels["cities"])
    assert all(
        h.get("photo_url")
        for city in hotels["cities"]
        for h in city["hotels"]
    )
    assert all(
        h.get("lat") is not None and h.get("lng") is not None
        for city in hotels["cities"]
        for h in city["hotels"]
    )


def test_pdf_safe_maps_url_place_and_search() -> None:
    anchored = _pdf_safe_maps_url("Edinburgh Castle", lat=55.9486, lon=-3.1999)
    assert anchored.startswith("https://www.google.com/maps/search/")
    assert "/@55.9486,-3.1999,15z" in anchored
    assert "/maps/place/" not in anchored
    assert "?api=1" not in anchored
    search = _pdf_safe_maps_url("Glynhill Hotel & Spa", city="Renfrew")
    assert search.startswith("https://www.google.com/maps/search/")
    assert "?api=1" not in search
    assert "Renfrew" in search


def test_hotel_maps_url_uses_coords_not_api1() -> None:
    hotels = load_scotland_hotels()
    for city_block in hotels["cities"]:
        city = city_block["city"]
        for hotel in city_block["hotels"]:
            url = _hotel_maps_url(hotel, city=city)
            assert "?api=1" not in url
            assert "/maps/place/" not in url
            assert "/maps/search/" in url
            assert f"@{hotel['lat']},{hotel['lng']},15z" in url


def test_pin_maps_url_uses_place_path_not_query_at() -> None:
    pin = SimpleNamespace(
        name="The Cumberland Hotel, London",
        city="London",
        latitude=51.5136404,
        longitude=-0.1588683,
    )
    url = _pin_maps_url(pin)
    assert "/maps/search/" in url
    assert "/@51.5136404,-0.1588683,15z" in url
    assert "?api=1" not in url
    assert "query=" not in url
    assert "/maps/place/" not in url


def test_briefing_html_has_debrief_legs_and_stars() -> None:
    hotels = load_scotland_hotels()
    # Pre-seed one photo so we assert <img> without network.
    hotels["cities"][0]["hotels"][0]["photo_url"] = (
        "https://example.com/hotel-photo.jpg"
    )
    primary = {
        "display_name": "Traveler One (me)",
        "birth_date": "2000-01-01",
        "birth_time": "12:00",
        "birth_timezone": "America/Los_Angeles",
        "birth_place": "Los Angeles, California",
    }
    companion = {
        "display_name": "Companion (Traveler Two)",
        "birth_date": "1990-06-15",
        "birth_time": "09:30",
        "birth_timezone": "America/Los_Angeles",
        "birth_place": "Los Angeles, California",
    }
    html = build_west_europe_briefing_html(
        pins=_sample_pins(),
        scotland_hotels=hotels,
        primary_traveler=primary,
        companion_traveler=companion,
        primary_layers=(_FAKE_ANGULAR, _FAKE_ASPECTS),
        companion_layers=(_FAKE_ANGULAR, _FAKE_ASPECTS),
        enrich_hotel_photos=False,
        include_acg_maps=True,
        embed_images=False,
    )
    assert "Route debrief" in html
    assert "land EDI" in html.casefold() or "Land EDI" in html or "EDI" in html
    assert "45" in html
    for leg in load_leg_plan()["legs"]:
        assert html_lib.escape(leg["name"]) in html
        assert f'{leg["days"]} day' in html
        assert html_lib.escape(leg["image_url"], quote=True) in html
    assert "★ shuttle" in html
    assert "Holiday Inn Express Edinburgh Airport" in html
    assert "Scotland hotels to look into" in html
    assert "google.com/maps" in html
    assert "maps/search/?api=1" not in html
    assert "maps/place/" not in html
    assert "maps/search/" in html
    assert "Edinburgh Castle" in html
    assert "@55.9486,-3.1999,15z" in html
    assert "Open-jaw" in html
    assert "different arrival and departure" in html or "fly home from" in html.casefold()
    assert "Bad overseas geocode" not in html
    assert "Astrocartography" in html
    assert "Traveler One (me)" in html
    assert "Companion (Traveler Two)" in html
    assert "data:image/png;base64," in html
    assert 'class="hotel-photo"' in html
    assert 'class="region-photo"' in html
    assert "Astrocartography — Portugal" in html
