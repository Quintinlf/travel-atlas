"""Preferred trip and West Europe map defaults (no Streamlit widgets)."""

from __future__ import annotations

import sys
from pathlib import Path

_TRAVEL = Path(__file__).parent.parent
if str(_TRAVEL) not in sys.path:
    sys.path.insert(0, str(_TRAVEL))

from src_phase1.geo_grouping import WEST_EUROPE_MAP_CENTER, world_map_view
from travel_atlas.services.trip_context import preferred_trip, preferred_trip_index
from travel_atlas.services.trip_map import (
    SCOTLAND_CAR_LOOP_LABEL,
    default_city_index,
    default_leg_index,
)


def test_preferred_trip_picks_west_europe_over_kazakhstan() -> None:
    trips = [
        {"id": "kz", "name": "Kazakhstan research"},
        {"id": "we", "name": "West Europe trip"},
        {"id": "jp", "name": "Japan"},
    ]
    chosen = preferred_trip(trips)
    assert chosen is not None
    assert chosen["id"] == "we"
    assert preferred_trip_index(trips) == 1


def test_preferred_trip_honors_session_id() -> None:
    trips = [
        {"id": "kz", "name": "Kazakhstan research"},
        {"id": "we", "name": "West Europe trip"},
    ]
    chosen = preferred_trip(trips, session_trip_id="kz")
    assert chosen is not None
    assert chosen["id"] == "kz"


def test_preferred_trip_falls_back_to_first() -> None:
    trips = [
        {"id": "kz", "name": "Kazakhstan research"},
        {"id": "jp", "name": "Japan"},
    ]
    chosen = preferred_trip(trips)
    assert chosen is not None
    assert chosen["id"] == "kz"


def test_default_leg_and_city_open_scotland_edinburgh() -> None:
    names = ["All trip pins", SCOTLAND_CAR_LOOP_LABEL, "Glasgow", "London Hub"]
    assert default_leg_index(names) == 1
    cities = ["All cities in Scotland car loop (Dundee)", "Perth", "Edinburgh", "St Andrews"]
    assert default_city_index(cities) == 2


def test_world_map_view_defaults_to_west_europe_box() -> None:
    coords = [
        (43.24, 76.91),  # Almaty
        (55.95, -3.19),  # Edinburgh
        (51.51, -0.13),  # London
        (35.68, 139.76),  # Tokyo
    ]
    lat, lon, zoom, plot = world_map_view(coords, show_all=False)
    assert (lat, lon) == WEST_EUROPE_MAP_CENTER
    assert zoom == 5
    assert (43.24, 76.91) not in plot
    assert (35.68, 139.76) not in plot
    assert (55.95, -3.19) in plot
    assert (51.51, -0.13) in plot

    glob_lat, glob_lon, glob_zoom, glob_plot = world_map_view(coords, show_all=True)
    assert glob_zoom == 3
    assert len(glob_plot) == 4
    assert glob_lon > lon  # pulled east by Kazakhstan/Japan
