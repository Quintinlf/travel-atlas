"""Tests for Alaska flight routing facts and HTML trip briefing."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

_TRAVEL = Path(__file__).parent.parent
if str(_TRAVEL) not in sys.path:
    sys.path.insert(0, str(_TRAVEL))

from travel_atlas.services.alaska_briefing import build_alaska_briefing_html
from travel_atlas.services.alaska_flight_routes import route_briefing
from travel_atlas.services.fairbanks_guide import fairbanks_guide, market_days_during_stay


def test_route_briefing_lax_fai_no_nonstop():
    routes = route_briefing(adults=2)
    assert routes["lax_fai_nonstop"] is False
    assert routes["lax_anc_nonstop"] is True
    assert "SEA" in routes["typical_hubs"]
    assert routes["flight_benchmark_party_low"] == 379 * 2
    assert routes["flight_benchmark_party_high"] == 415 * 2
    assert "layover" in routes["no_nonstop_summary"].lower()
    assert "red-eye" in routes["no_red_eye_summary"].lower()


def test_market_days_sep_26_30():
    days = market_days_during_stay(date(2026, 9, 26), date(2026, 9, 30))
    assert date(2026, 9, 26) in days  # Saturday (not Sep 27)
    assert (date(2026, 9, 30) - date(2026, 9, 26)).days == 4


def test_fairbanks_guide_has_chena_and_market():
    guide = fairbanks_guide(arrive=date(2026, 9, 26), leave=date(2026, 9, 30))
    assert "Chena" in guide["hot_springs"]["name"]
    assert "Tanana Valley" in guide["markets"]["name"]
    assert any("reindeer" in f.lower() for f, _, _ in guide["native_foods"]["try"])
    assert len(guide["suggested_days"]) >= 4


def test_build_briefing_html_from_snapshot(tmp_path: Path):
    snapshot = {
        "travelers": 2,
        "windows": {
            "4-night": {
                "arrive": "2026-09-26",
                "leave": "2026-09-30",
                "flights": {
                    "links": {
                        "kayak": (
                            "https://www.kayak.com/flights/LAX-FAI/"
                            "2026-09-26/2026-09-30/2adults?sort=bestflight_a"
                        ),
                        "google_flights": "https://www.google.com/travel/flights?q=test",
                    }
                },
                "hotels": {
                    "area_links": {
                        "booking": (
                            "https://www.booking.com/searchresults.html?"
                            "ss=Fairbanks&group_adults=2"
                        )
                    },
                    "hotels": [
                        {
                            "hotel": "Best Western Plus Pioneer Park",
                            "room": "2 QUEEN BEDS",
                            "total": 379.44,
                            "nightly": 126.48,
                            "rating": 8.1,
                            "photo_url": "https://example.com/hotel.jpg",
                            "booking_url": "https://www.booking.com/hotel/us/test.html",
                            "google_hotels_url": "https://www.google.com/maps/search/test+hotel",
                        }
                    ],
                },
            }
        },
        "flight_benchmark": {
            "per_adult_low_usd": 379,
            "per_adult_high_usd": 415,
            "party_of_2_mid_usd": 830,
            "note": "Aviasales cache empty for LAX-FAI; verify on Kayak/Google",
        },
    }
    snap_path = tmp_path / "snapshot.json"
    snap_path.write_text(json.dumps(snapshot), encoding="utf-8")

    html = build_alaska_briefing_html(
        arrive=date(2026, 9, 26),
        leave=date(2026, 9, 30),
        travelers=2,
        flight_result=None,
        hotel_result=None,
        stay_nights=None,
        snapshot_path=snap_path,
        allow_live_fetch=False,
    )

    assert "2 QUEEN BEDS" in html
    assert "Best Western Plus Pioneer Park" in html
    assert "Chena Hot Springs" in html
    assert "Tanana Valley" in html
    assert "reindeer" in html.lower()
    assert "red-eye" in html.lower()
    assert "no nonstop" in html.lower() or "No nonstop" in html
    assert ">4<" in html  # 4 nights
    assert "@media print" in html
    assert "379" in html
    assert "415" in html
    assert "hotel-card" in html
    assert "<img" in html
    assert "booking.com" in html.lower()
    assert "google.com/maps" in html.lower()
    assert "Estimated full trip cost" in html
    assert "Core trip (mid)" in html
    assert "Aurora viewing strategy" in html
    assert "Optional add-ons" in html
    assert "Core trip (mid)" in html
    assert "Optional: car rental" in html
    assert "Optional: Chena Hot Springs" in html
