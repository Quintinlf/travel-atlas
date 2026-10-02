"""Tests for static matplotlib ACG maps."""

from __future__ import annotations

import sys
from pathlib import Path

_TRAVEL = Path(__file__).parent.parent
if str(_TRAVEL) not in sys.path:
    sys.path.insert(0, str(_TRAVEL))

from travel_atlas.services.static_acg_map import (
    bbox_from_coords,
    png_to_data_uri,
    render_acg_map_png,
)


def test_render_acg_map_png_has_png_header() -> None:
    angular = [
        {
            "body": "Sun",
            "angle": "mc",
            "kind": "meridian",
            "points": [[35.0, -5.0], [60.0, -5.0]],
        },
        {
            "body": "Moon",
            "angle": "ascendant",
            "kind": "horizon",
            "points": [[50.0, -12.0], [50.0, 10.0]],
        },
    ]
    aspects = [
        {
            "body": "Venus",
            "aspect": "trine",
            "line_kind": "aspect",
            "points": [[40.0, -8.0], [55.0, 5.0]],
        }
    ]
    png = render_acg_map_png(
        angular_lines=angular,
        aspect_lines=aspects,
        bbox=(40.0, -10.0, 58.0, 8.0),
        title="Test ACG",
        markers=[(51.5, -0.12, "London")],
        use_osm_tiles=False,  # offline / deterministic in CI
    )
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 2000
    uri = png_to_data_uri(png)
    assert uri.startswith("data:image/png;base64,")
    assert len(uri) > 100


def test_country_geojson_is_available() -> None:
    from travel_atlas.services.static_acg_map import (
        _GEOJSON_10M,
        _GEOJSON_50M,
        _GEOJSON_110M,
        _country_features,
        _geojson_path,
    )

    assert _GEOJSON_10M.is_file() or _GEOJSON_50M.is_file() or _GEOJSON_110M.is_file()
    assert _geojson_path().is_file()
    assert len(_country_features()) > 50


def test_glasgow_uses_wide_scotland_frame() -> None:
    from travel_atlas.services.static_acg_map import LEG_ACG_BBOX, bbox_for_leg_pins

    south, west, north, east = bbox_for_leg_pins("Glasgow", [])
    assert (south, west, north, east) == LEG_ACG_BBOX["Glasgow"]
    assert (north - south) > 3.0
    assert (east - west) > 5.0


def test_spaced_markers_avoid_collision() -> None:
    from travel_atlas.services.static_acg_map import _spaced_markers

    markers = [
        (48.86, 2.35, "Paris"),
        (48.90, 2.33, "Saint-Ouen"),
        (49.25, 4.03, "Reims"),
    ]
    chosen = _spaced_markers(
        markers, south=46.8, west=-2.2, north=51.4, east=5.2, limit=5
    )
    names = {m[2] for m in chosen}
    assert "Paris" in names
    assert "Saint-Ouen" not in names
    assert "Reims" in names
    assert len(chosen) == 2


def test_angular_edge_label_uses_glyph() -> None:
    from travel_atlas.services.static_acg_map import _angular_edge_label

    label = _angular_edge_label({"body": "Sun", "angle": "mc"})
    assert "MC" in label
    assert "☉" in label
    assert "Su " not in label


def test_bbox_from_coords_pads() -> None:
    south, west, north, east = bbox_from_coords([(51.5, -0.1), (51.6, 0.1)])
    assert south < 51.5
    assert north > 51.6
    assert west < -0.1
    assert east > 0.1
