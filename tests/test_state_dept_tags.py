"""State Dept tag mapping and traveler docs helpers."""

from __future__ import annotations

from src_phase1.geo_grouping import destination_label  # noqa: F401 — import smoke
from travel_atlas.providers.state_dept import country_tag
from travel_atlas.services.traveler_docs import expand_trip_regions


def test_uk_maps_to_uk_not_gabon() -> None:
    assert country_tag("United Kingdom") == "UK"
    assert country_tag("England") == "UK"
    assert country_tag("Scotland") == "UK"
    assert country_tag("Ireland") == "EI"
    assert country_tag("Spain") == "SP"
    assert country_tag("Portugal") == "PO"


def test_expand_uk_into_nations_keeps_ireland() -> None:
    regions = expand_trip_regions(["United Kingdom", "Ireland", "France"])
    assert "England" in regions
    assert "Scotland" in regions
    assert "Ireland" in regions
    assert "France" in regions
