"""Tests for optional add-ons in Fairbanks trip budget."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

_TRAVEL = Path(__file__).parent.parent
if str(_TRAVEL) not in sys.path:
    sys.path.insert(0, str(_TRAVEL))

from travel_atlas.services.fairbanks_guide import fairbanks_guide
from travel_atlas.services.fairbanks_trip_budget import build_trip_budget


def test_guide_has_optional_add_ons():
    guide = fairbanks_guide(arrive=date(2026, 9, 26), leave=date(2026, 9, 30))
    assert guide["hot_springs"]["optional"] is True
    assert "why_add" in guide["hot_springs"]
    assert "car_rental" in guide["optional_add_ons"]


def test_core_budget_excludes_car_and_chena():
    budget = build_trip_budget(
        arrive=date(2026, 9, 26),
        leave=date(2026, 9, 30),
        travelers=2,
        hotel_total=477.0,
        flight_party_low=758.0,
        flight_party_high=1200.0,
        include_car_rental=False,
        include_chena=False,
        include_aurora_tour=False,
    )
    core_labels = " ".join(i["label"] for i in budget["line_items"])
    assert "Airport rides" in core_labels
    assert "car rental" not in core_labels.lower()
    optional_labels = " ".join(i["label"] for i in budget["optional_line_items"])
    assert "Optional: car rental" in optional_labels
    assert "Optional: Chena Hot Springs" in optional_labels


def test_adding_car_drops_airport_rides():
    budget = build_trip_budget(
        arrive=date(2026, 9, 26),
        leave=date(2026, 9, 30),
        travelers=2,
        hotel_total=477.0,
        flight_party_low=758.0,
        flight_party_high=1200.0,
        include_car_rental=True,
    )
    core_labels = " ".join(i["label"] for i in budget["line_items"])
    assert "Airport rides" not in core_labels
    assert budget["grand_total_mid"] > budget["core_total_mid"]
