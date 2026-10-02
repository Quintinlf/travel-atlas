"""Tests for Google CID parsing and media strategy helpers."""

from __future__ import annotations

from src_phase1.commons_media import location_search_queries, titles_similar
from src_phase1.google_place_identity import (
    MEDIA_STRATEGY_VERSION,
    coords_conflict,
    extract_cid_decimal,
)


def test_extract_cid_from_feature_url() -> None:
    url = (
        "https://www.google.com/maps/place/Links+N'+Ice/"
        "data=!4m2!3m1!1s0x88f505a2422c30b3:0xc08873ca92419386"
    )
    assert extract_cid_decimal(url) == int("c08873ca92419386", 16)


def test_coords_conflict_detects_wrong_country() -> None:
    # Blyth UK vs Atlanta US
    assert coords_conflict(55.1093343, -1.5007166, 33.8083003, -84.3635288)


def test_titles_similar_requires_overlap() -> None:
    assert titles_similar("Hachiko Statue", "Hachiko statue Shibuya")
    assert not titles_similar("Hachiko Statue", "Japanese kaiseki meal tray")


def test_location_search_queries_prefer_name_city_country() -> None:
    queries = location_search_queries(
        "Tate Modern", city="London", country="United Kingdom"
    )
    assert queries[0] == "Tate Modern London United Kingdom"
    assert "Tate Modern London" in queries
    assert queries[-1] == "Tate Modern"


def test_media_strategy_version_set() -> None:
    assert MEDIA_STRATEGY_VERSION.startswith("exact-maps-link")
