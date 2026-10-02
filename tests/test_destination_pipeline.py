"""Tests for destination grouping and geocoding helpers."""

from __future__ import annotations

from pathlib import Path

from src_phase1.geo_grouping import (
    destination_label,
    destination_matches,
    is_wishlist_country_name,
    top_level_destination,
)
from src_phase1.geocoding import GeocodeResult, reverse_geocode_pin
from src_phase1.models import SavedLocation


def _pin(**kwargs) -> SavedLocation:
    defaults = {
        "id": "pin-1",
        "name": "Test Place",
        "latitude": 35.6762,
        "longitude": 139.6503,
        "list_name": "Want To Go",
        "source_type": "saved_list_csv",
        "source_file": "Want to go.csv",
        "raw_json": "{}",
    }
    defaults.update(kwargs)
    return SavedLocation(**defaults)


def test_top_level_destination_groups_us_pins_by_state() -> None:
    pin = _pin(country="United States", region="Louisiana", city="New Orleans")
    assert top_level_destination(pin) == ("us_state", "Louisiana")


def test_top_level_destination_groups_foreign_pins_by_country() -> None:
    pin = _pin(country="Japan", city="Tokyo")
    assert top_level_destination(pin) == ("country", "Japan")


def test_wishlist_country_name() -> None:
    pin = _pin(name="Japan", city=None, country=None)
    assert top_level_destination(pin) == ("wishlist_country", "Japan")
    assert is_wishlist_country_name("Japan")


def test_destination_label_for_us_state() -> None:
    assert destination_label("us_state", "Louisiana") == "Louisiana, USA"


def test_uk_nation_subdivision_keeps_ireland_separate() -> None:
    glasgow = _pin(
        name="Glasgow",
        country="United Kingdom",
        region="Scotland",
        city="Glasgow",
        latitude=55.86,
        longitude=-4.25,
    )
    dublin = _pin(
        name="Temple Bar",
        country="Ireland",
        region="Leinster",
        city="Dublin",
        latitude=53.34,
        longitude=-6.26,
    )
    ireland_wishlist = _pin(name="Ireland", city=None, country=None, latitude=0, longitude=0)
    assert top_level_destination(glasgow) == ("uk_nation", "Scotland")
    assert top_level_destination(dublin) == ("country", "Ireland")
    assert top_level_destination(ireland_wishlist) == ("wishlist_country", "Ireland")
    assert destination_label("uk_nation", "Scotland") == "Scotland (UK)"


def test_destination_matches_country_includes_wishlist_alias() -> None:
    wishlist = _pin(name="France", city=None, country=None, latitude=0, longitude=0)
    assert top_level_destination(wishlist) == ("wishlist_country", "France")
    assert destination_matches(wishlist, "country", "France") is True
    assert destination_matches(wishlist, "wishlist_country", "France") is True
    assert destination_matches(wishlist, "country", "Spain") is False


def test_destination_matches_uk_nation_with_country_kind() -> None:
    england = _pin(
        name="Tower Bridge",
        country="United Kingdom",
        region="England",
        city="London",
        latitude=51.5,
        longitude=-0.07,
    )
    assert top_level_destination(england) == ("uk_nation", "England")
    assert destination_matches(england, "uk_nation", "England") is True
    assert destination_matches(england, "country", "England") is True
    assert destination_matches(england, "country", "United Kingdom") is True


def test_ireland_aliases_and_inference() -> None:
    eire = _pin(name="Pub", country="Eire", city="Dublin", latitude=53.34, longitude=-6.26)
    republic = _pin(
        name="Pub", country="Republic of Ireland", city=None, latitude=53.34, longitude=-6.26
    )
    museum = _pin(
        name="National Museum of Ireland, Kildare Street",
        city=None,
        country=None,
        latitude=53.3402,
        longitude=-6.2549,
    )
    dublin_only = _pin(name="Temple Bar", city="Dublin", country=None, latitude=0, longitude=0)
    ni = _pin(
        name="Titanic Belfast",
        country="United Kingdom",
        region="Northern Ireland",
        city="Belfast",
        latitude=54.60,
        longitude=-5.91,
    )
    stolen = _pin(
        name="Galway market",
        country="Ireland",
        region="Northern Ireland",
        city="Galway",
        latitude=53.27,
        longitude=-9.05,
    )
    assert top_level_destination(eire) == ("country", "Ireland")
    assert top_level_destination(republic) == ("country", "Ireland")
    assert top_level_destination(museum) == ("country", "Ireland")
    assert top_level_destination(dublin_only) == ("country", "Ireland")
    assert destination_matches(museum, "country", "Ireland") is True
    assert destination_matches(eire, "country", "Republic of Ireland") is True
    assert destination_matches(ni, "country", "Ireland") is False
    assert top_level_destination(ni) == ("uk_nation", "Northern Ireland")
    assert top_level_destination(stolen) == ("country", "Ireland")


def test_offline_reverse_geocode_fallback(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)

    def fake_offline(latitude: float, longitude: float) -> GeocodeResult | None:
        return GeocodeResult(
            city="Tokyo",
            region=None,
            country="Japan",
            provider="offline",
        )

    monkeypatch.setattr(
        "src_phase1.geocoding._offline_geocode",
        fake_offline,
    )
    result = reverse_geocode_pin(35.6762, 139.6503)
    assert result is not None
    assert result.city == "Tokyo"
    assert result.country == "Japan"


def test_score_place_against_supportive_meridian() -> None:
    from travel_atlas.services.astro_helper import score_place_against_lines

    angular = [{"body": "Venus", "kind": "MC", "longitude": -9.14}]
    rated = score_place_against_lines(38.72, -9.14, angular, [])
    assert rated["score"] > 0
    assert any("Venus" in h for h in rated["hits"])


def test_entry_conditionals_ireland_not_schengen() -> None:
    from travel_atlas.services.traveler_docs import ENTRY_CONDITIONALS

    text = " ".join(ENTRY_CONDITIONALS["Ireland"]).lower()
    assert "schengen" in text
    assert "not" in text


def test_bidet_reason_in_lodging_advice() -> None:
    from travel_atlas.services.lodging_advisor import advise_lodging_type

    advice = advise_lodging_type(
        nights=3,
        needs_kitchen=False,
        traveling_with_others=False,
        want_daily_cleaning=True,
        early_checkout_flexibility=False,
        prefer_local_neighborhood=False,
        requires_bidet=True,
    )
    assert any("Bidet" in r or "bidet" in r for r in advice.reasons)


def test_curated_substance_image_resolves_local_file() -> None:
    from travel_atlas.services.substance_images import MEDIA_DIR, resolve_substance_image

    src, caption = resolve_substance_image(
        {"name": "Heather ale", "image_file": "heather_ale_fraoch.png"}
    )
    assert src
    assert Path(src).name == "heather_ale_fraoch.png"
    assert Path(src).is_file()
    assert caption == "Curated photo"
    assert MEDIA_DIR.is_dir()
