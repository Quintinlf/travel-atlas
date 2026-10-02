"""
Phase 1 unit tests.

Run with:
    cd travel_code
    python -m pytest travel/tests/test_phase1.py -v
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import List

import pytest

# Ensure src_phase1 is importable regardless of cwd
import sys
_TRAVEL = Path(__file__).parent.parent
if str(_TRAVEL) not in sys.path:
    sys.path.insert(0, str(_TRAVEL))

from src_phase1.clustering import ClusterConfig, PinClusterer
from src_phase1.insights import (
    BOOST_DEFAULT,
    BOOST_MAX,
    BOOST_MIN,
    DestinationInsights,
    _minmax_norm,
    clamp_boost,
    real_note,
)
from src_phase1.models import Cluster, SavedLocation
from src_phase1.pin_repository import PinRepository, haversine_km
from src_phase1.takeout_parser import TakeoutParser, _parse_address, _name_from_google_maps_url, _valid_coords, _coords_from_google_url, check_takeout_completeness


# ------------------------------------------------------------------ #
# Fixtures                                                             #
# ------------------------------------------------------------------ #

def _pin(
    lat: float = 51.5,
    lng: float = -0.1,
    name: str = "Test Place",
    city: str = "London",
    country: str = "UK",
    list_name: str = "Saved Places",
    notes: str = "",
) -> SavedLocation:
    return SavedLocation(
        id=str(uuid.uuid4()),
        name=name,
        latitude=lat,
        longitude=lng,
        city=city,
        country=country,
        list_name=list_name,
        notes=notes or None,
        source_type="saved_places",
        source_file="test.json",
        raw_json="{}",
    )


@pytest.fixture
def tmp_db(tmp_path: Path) -> PinRepository:
    return PinRepository(tmp_path / "test.db")


@pytest.fixture
def sample_pins() -> List[SavedLocation]:
    """Small multi-city pin set for tests."""
    return [
        _pin(51.5074, -0.1276, "Trafalgar Square",   "London",    "UK"),
        _pin(51.5007, -0.1245, "Parliament",          "London",    "UK"),
        _pin(51.5081, -0.0972, "Globe Theatre",       "London",    "UK",
             list_name="Want To Go"),
        _pin(48.8566,  2.3522, "Eiffel Tower",        "Paris",     "France"),
        _pin(48.8603,  2.3308, "Louvre",              "Paris",     "France"),
        _pin(55.9533, -3.1883, "Edinburgh Castle",    "Edinburgh", "UK"),
        _pin(55.9484, -3.1893, "The Hairy Coo",       "Edinburgh", "UK",
             list_name="Reviews"),
        _pin(53.3498, -6.2603, "Trinity College",     "Dublin",    "Ireland"),
    ]


# ------------------------------------------------------------------ #
# models.py                                                            #
# ------------------------------------------------------------------ #

class TestSavedLocation:
    def test_to_dict_round_trip(self) -> None:
        pin = _pin()
        d = pin.to_dict()
        restored = SavedLocation.from_row(d)
        assert restored.id == pin.id
        assert restored.name == pin.name
        assert restored.latitude == pin.latitude
        assert restored.city == pin.city

    def test_tags_serialise_as_json(self) -> None:
        pin = _pin()
        pin.tags.extend(["scenic", "historic"])
        d = pin.to_dict()
        assert isinstance(d["tags"], str)
        assert json.loads(d["tags"]) == ["scenic", "historic"]

    def test_imported_at_is_isoformat(self) -> None:
        pin = _pin()
        d = pin.to_dict()
        # Should not raise
        datetime.fromisoformat(d["imported_at"])

    def test_from_row_with_string_imported_at(self) -> None:
        pin = _pin()
        d = pin.to_dict()
        d["imported_at"] = "2026-06-10T12:00:00"
        restored = SavedLocation.from_row(d)
        assert restored.imported_at == datetime(2026, 6, 10, 12, 0, 0)


# ------------------------------------------------------------------ #
# takeout_parser.py                                                    #
# ------------------------------------------------------------------ #

class TestTakeoutParser:
    def test_parse_feature_collection(self, tmp_path: Path) -> None:
        fc = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [-0.1276, 51.5074]},
                    "properties": {
                        "name": "Trafalgar Square",
                        "address": "London, UK",
                    },
                }
            ],
        }
        f = tmp_path / "Saved Places.json"
        f.write_text(json.dumps(fc))
        parser = TakeoutParser()
        locs = parser.parse_file(f)
        assert len(locs) == 1
        assert locs[0].name == "Trafalgar Square"
        assert abs(locs[0].latitude - 51.5074) < 0.001
        assert abs(locs[0].longitude - -0.1276) < 0.001

    def test_parse_array_format(self, tmp_path: Path) -> None:
        items = [
            {"name": "Place A", "latitude": 48.8566, "longitude": 2.3522},
            {"name": "Place B", "lat": 53.3498, "lng": -6.2603},
        ]
        f = tmp_path / "Want to go.json"
        f.write_text(json.dumps(items))
        parser = TakeoutParser()
        locs = parser.parse_file(f)
        assert len(locs) == 2
        assert locs[0].name == "Place A"
        assert locs[1].name == "Place B"

    def test_missing_coords_skipped_by_default(self, tmp_path: Path) -> None:
        items = [
            {"name": "No Coords Place"},
            {"name": "Has Coords", "latitude": 51.5, "longitude": -0.1},
        ]
        f = tmp_path / "Custom.json"
        f.write_text(json.dumps(items))
        parser = TakeoutParser(skip_missing_coords=True)
        locs = parser.parse_file(f)
        assert len(locs) == 1
        assert locs[0].name == "Has Coords"

    def test_missing_coords_kept_when_flag_off(self, tmp_path: Path) -> None:
        items = [{"name": "No Coords Place"}]
        f = tmp_path / "Custom.json"
        f.write_text(json.dumps(items))
        parser = TakeoutParser(skip_missing_coords=False)
        locs = parser.parse_file(f)
        assert len(locs) == 1
        assert locs[0].latitude == 0.0

    def test_malformed_json_returns_empty(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.json"
        f.write_text("{broken json!!!")
        parser = TakeoutParser()
        locs = parser.parse_file(f)
        assert locs == []

    def test_raw_json_preserved(self, tmp_path: Path) -> None:
        items = [{"name": "Place", "latitude": 51.5, "longitude": -0.1,
                  "extra_field": "should be preserved"}]
        f = tmp_path / "Custom.json"
        f.write_text(json.dumps(items))
        parser = TakeoutParser()
        locs = parser.parse_file(f)
        assert "extra_field" in locs[0].raw_json

    def test_parse_zip(self, tmp_path: Path) -> None:
        import zipfile
        items = [{"name": "Zipped Place", "latitude": 51.5, "longitude": -0.1}]
        json_path = tmp_path / "Saved Places.json"
        json_path.write_text(json.dumps(items))
        zip_path = tmp_path / "takeout.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.write(json_path, arcname="Takeout/Maps/Saved Places.json")
        parser = TakeoutParser()
        locs = parser.parse_zip(zip_path)
        assert len(locs) == 1
        assert locs[0].name == "Zipped Place"

    def test_notes_extracted(self, tmp_path: Path) -> None:
        items = [{"name": "X", "latitude": 1.0, "longitude": 1.0,
                  "notes": "Great place"}]
        f = tmp_path / "Custom.json"
        f.write_text(json.dumps(items))
        parser = TakeoutParser()
        locs = parser.parse_file(f)
        assert locs[0].notes == "Great place"

    def test_address_parse_helper(self) -> None:
        city, country = _parse_address("Baker St, London, UK")
        assert country == "UK"
        assert city == "London"

    def test_address_parse_ignores_free_text_notes(self) -> None:
        city, country = _parse_address(
            "Howth (right outside dublin) has best fish and chips, really"
        )
        assert city is None
        assert country is None

    def test_zero_zero_coords_invalid(self) -> None:
        assert _valid_coords(0.0, 0.0) is False
        assert _valid_coords(51.5, -0.1) is True

    def test_name_from_google_maps_url(self) -> None:
        url = "http://maps.google.com/?q=San+Jose,+CA&ftid=0x123"
        assert _name_from_google_maps_url(url) == "San Jose, CA"

    def test_parse_review_feature_collection(self, tmp_path: Path) -> None:
        fc = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-118.4938285, 34.1943846]},
                "properties": {
                    "location": {
                        "name": "Airintel HVAC Inc",
                        "address": "16537 Vanowen St #215, Van Nuys, CA 91406, United States",
                    },
                    "review_text_published": "Great service.",
                },
            }],
        }
        f = tmp_path / "Reviews.json"
        f.write_text(json.dumps(fc))
        locs = TakeoutParser().parse_file(f)
        assert len(locs) == 1
        assert locs[0].name == "Airintel HVAC Inc"
        assert locs[0].country == "United States"
        assert locs[0].notes == "Great service."

    def test_skip_zero_zero_saved_places(self, tmp_path: Path) -> None:
        fc = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [0, 0]},
                "properties": {
                    "google_maps_url": "http://maps.google.com/?q=Oaxaca,+Mexico",
                    "Comment": "No location information is available for this saved place",
                },
            }],
        }
        f = tmp_path / "Saved Places.json"
        f.write_text(json.dumps(fc))
        parser = TakeoutParser(import_coordinateless=False)
        locs = parser.parse_file(f)
        assert len(locs) == 0
        assert parser.last_report.drops_by_reason.get("zero_sentinel", 0) == 1

    def test_import_coordinateless_saved_places_with_name(self, tmp_path: Path) -> None:
        fc = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [0, 0]},
                "properties": {
                    "google_maps_url": "http://maps.google.com/?q=Oaxaca,+Mexico",
                    "Comment": "No location information is available for this saved place",
                },
            }],
        }
        f = tmp_path / "Saved Places.json"
        f.write_text(json.dumps(fc))
        parser = TakeoutParser(import_coordinateless=True)
        locs = parser.parse_file(f)
        assert len(locs) == 1
        assert locs[0].name == "Oaxaca, Mexico"
        assert locs[0].latitude == 0.0

    def test_coords_from_google_url_at_format(self) -> None:
        url = "https://www.google.com/maps/place/X/@34.0167898,-118.4709157,17z"
        lat, lng = _coords_from_google_url(url)
        assert lat is not None
        assert abs(lat - 34.0167898) < 0.001

    def test_coords_from_google_url_q_latlng(self) -> None:
        url = "http://maps.google.com/?q=41.993752,5.326894"
        lat, lng = _coords_from_google_url(url)
        assert abs(lat - 41.993752) < 0.001
        assert abs(lng - 5.326894) < 0.001

    def test_parse_saved_list_csv(self, tmp_path: Path) -> None:
        csv_content = (
            "Title,Note,URL,Tags,Comment\n"
            '"Tokyo Tower","must visit","https://www.google.com/maps/place//@35.6585805,139.7454329,17z",,\n'
            '"Oaxaca","food","http://maps.google.com/?q=Oaxaca,+Mexico",,\n'
        )
        csv_path = tmp_path / "Want to go.csv"
        csv_path.write_text(csv_content, encoding="utf-8")
        parser = TakeoutParser()
        locs = parser.parse_file(csv_path) if csv_path.suffix == ".json" else parser._parse_csv_text(csv_content, "Saved/Want to go.csv")
        assert len(locs) >= 2
        tokyo = next(l for l in locs if "Tokyo" in l.name)
        assert abs(tokyo.latitude - 35.6585805) < 0.01

    def test_takeout_completeness_detects_missing_saved(self, tmp_path: Path) -> None:
        # Simulate Maps-only export (like user's current Takeout)
        maps_dir = tmp_path / "Takeout" / "Maps (your places)"
        maps_dir.mkdir(parents=True)
        (maps_dir / "Saved Places.json").write_text('{"type":"FeatureCollection","features":[]}')
        report = check_takeout_completeness(tmp_path / "Takeout")
        assert report["likely_incomplete"] is True

    def test_parse_labeled_places_features_array(self, tmp_path: Path) -> None:
        data = {
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-118.3541429, 34.0676671]},
                "properties": {
                    "address": "432 S Curson Ave #5j, Los Angeles, CA 90036, USA",
                    "name": "Home",
                },
            }],
        }
        f = tmp_path / "Labeled places.json"
        f.write_text(json.dumps(data))
        locs = TakeoutParser().parse_file(f)
        assert len(locs) == 1
        assert locs[0].name == "Home"
        assert abs(locs[0].latitude - 34.0676671) < 0.001


# ------------------------------------------------------------------ #
# pin_repository.py                                                    #
# ------------------------------------------------------------------ #

class TestPinRepository:
    def test_db_created(self, tmp_db: PinRepository) -> None:
        assert tmp_db.db_path.exists()

    def test_insert_and_retrieve(self, tmp_db: PinRepository) -> None:
        pin = _pin()
        tmp_db.insert_pin(pin)
        all_pins = tmp_db.get_all_pins()
        assert len(all_pins) == 1
        assert all_pins[0].name == pin.name

    def test_bulk_insert(self, tmp_db: PinRepository, sample_pins: List[SavedLocation]) -> None:
        inserted = tmp_db.insert_pins_batch(sample_pins)
        assert inserted == len(sample_pins)
        assert tmp_db.count() == len(sample_pins)

    def test_duplicate_id_ignored(self, tmp_db: PinRepository) -> None:
        pin = _pin()
        tmp_db.insert_pin(pin)
        tmp_db.insert_pin(pin)  # same id
        assert tmp_db.count() == 1

    def test_deduplication_by_proximity(self, tmp_db: PinRepository) -> None:
        pin1 = _pin(51.5074, -0.1276, "Trafalgar Square")
        # Same name, 30 m away — should be deduped
        pin2 = _pin(51.5074 + 0.0001, -0.1276, "Trafalgar Square")
        tmp_db.insert_pins_batch([pin1, pin2])
        removed = tmp_db.deduplicate(proximity_m=100)
        assert removed == 1
        assert tmp_db.count() == 1

    def test_deduplication_keeps_richer_pin(self, tmp_db: PinRepository) -> None:
        rich = _pin(51.5074, -0.1276, "Trafalgar Square",
                    notes="Famous landmark with fountains")
        poor = _pin(51.5074 + 0.0001, -0.1276, "Trafalgar Square")
        tmp_db.insert_pins_batch([poor, rich])
        tmp_db.deduplicate(proximity_m=100)
        remaining = tmp_db.get_all_pins()
        assert len(remaining) == 1
        assert remaining[0].notes is not None

    def test_get_pins_by_city(self, tmp_db: PinRepository, sample_pins: List[SavedLocation]) -> None:
        tmp_db.insert_pins_batch(sample_pins)
        london = tmp_db.get_pins_by_city("London")
        assert len(london) == 3

    def test_get_stats(self, tmp_db: PinRepository, sample_pins: List[SavedLocation]) -> None:
        tmp_db.insert_pins_batch(sample_pins)
        stats = tmp_db.get_stats()
        assert stats["total"] == len(sample_pins)
        assert "London" in stats["by_city"]
        assert "UK" in stats["by_country"]
        assert "Saved Places" in stats["by_list"]

    def test_delete_all(self, tmp_db: PinRepository, sample_pins: List[SavedLocation]) -> None:
        tmp_db.insert_pins_batch(sample_pins)
        tmp_db.delete_all_pins()
        assert tmp_db.count() == 0


# ------------------------------------------------------------------ #
# clustering.py                                                        #
# ------------------------------------------------------------------ #

class TestPinClusterer:
    def test_pins_in_same_city_cluster_together(self, sample_pins: List[SavedLocation]) -> None:
        clusterer = PinClusterer(ClusterConfig(distance_threshold_km=20))
        clusters = clusterer.cluster_pins(sample_pins)
        # London pins should form one cluster
        london_cluster = next(
            (c for c in clusters if c.city == "London"), None
        )
        assert london_cluster is not None
        assert london_cluster.pin_count == 3

    def test_pins_in_different_cities_form_different_clusters(self, sample_pins: List[SavedLocation]) -> None:
        clusterer = PinClusterer(ClusterConfig(distance_threshold_km=20))
        clusters = clusterer.cluster_pins(sample_pins)
        city_names = {c.city for c in clusters if c.city}
        assert "London" in city_names
        assert "Paris" in city_names

    def test_threshold_affects_clustering(self, sample_pins: List[SavedLocation]) -> None:
        tight = PinClusterer(ClusterConfig(distance_threshold_km=1))
        loose = PinClusterer(ClusterConfig(distance_threshold_km=500))
        tight_clusters = tight.cluster_pins(sample_pins)
        loose_clusters = loose.cluster_pins(sample_pins)
        assert len(tight_clusters) >= len(loose_clusters)

    def test_centroid_within_reasonable_range(self, sample_pins: List[SavedLocation]) -> None:
        clusterer = PinClusterer(ClusterConfig(distance_threshold_km=20))
        clusters = clusterer.cluster_pins(sample_pins)
        for c in clusters:
            assert -90 <= c.centroid_lat <= 90
            assert -180 <= c.centroid_lng <= 180

    def test_empty_pins_returns_empty(self) -> None:
        clusterer = PinClusterer()
        assert clusterer.cluster_pins([]) == []

    def test_invalid_config_raises(self) -> None:
        with pytest.raises(ValueError):
            ClusterConfig(distance_threshold_km=-1)


# ------------------------------------------------------------------ #
# insights.py                                                          #
# ------------------------------------------------------------------ #

class TestDestinationInsights:
    def test_top_destinations_sorted_by_score(self, sample_pins: List[SavedLocation]) -> None:
        ins = DestinationInsights(sample_pins)
        top = ins.get_top_destinations()
        assert top[0][0] == "United Kingdom"

    def test_scores_between_0_and_100(self, sample_pins: List[SavedLocation]) -> None:
        ins = DestinationInsights(sample_pins)
        for destination, score, count in ins.get_top_destinations():
            assert 0.0 <= score <= 100.0

    def test_pin_counts_match(self, sample_pins: List[SavedLocation]) -> None:
        ins = DestinationInsights(sample_pins)
        top = ins.get_top_destinations()
        united_kingdom = next(t for t in top if t[0] == "United Kingdom")
        assert united_kingdom[2] == 5

    def test_top_countries(self, sample_pins: List[SavedLocation]) -> None:
        ins = DestinationInsights(sample_pins)
        countries = dict(ins.get_top_countries())
        # Normalized destination buckets (UK nations when region known).
        assert countries.get("United Kingdom") == 5  # London 3 + Edinburgh 2
        assert countries["France"] == 2
        assert countries["Ireland"] == 1

    def test_list_breakdown(self, sample_pins: List[SavedLocation]) -> None:
        ins = DestinationInsights(sample_pins)
        breakdown = ins.get_list_breakdown()
        assert "Saved Places" in breakdown
        assert "Want To Go" in breakdown
        assert breakdown["Saved Places"] >= breakdown["Want To Go"]

    def test_statistics(self, sample_pins: List[SavedLocation]) -> None:
        ins = DestinationInsights(sample_pins)
        stats = ins.get_statistics()
        assert stats["total_pins"] == len(sample_pins)
        assert stats["unique_cities"] == 4
        assert stats["unique_countries"] == 3

    def test_generate_top_destinations_alias(self, sample_pins: List[SavedLocation]) -> None:
        ins = DestinationInsights(sample_pins)
        assert ins.generate_top_destinations() == ins.get_top_destinations()

    def test_empty_pins(self) -> None:
        ins = DestinationInsights([])
        assert ins.get_destination_scores() == []
        assert ins.get_top_destinations() == []
        assert ins.get_top_countries() == []
        assert ins.get_statistics()["total_pins"] == 0


# ------------------------------------------------------------------ #
# insights.py — note-based scoring                                     #
# ------------------------------------------------------------------ #

GEOCODE_PENDING = "Imported from CSV without coordinates — geocode pending"


def _rank(insights: DestinationInsights) -> List[str]:
    return [destination for destination, _, _ in insights.get_top_destinations(n=50)]


def _score_of(insights: DestinationInsights, destination: str) -> float:
    return next(
        score
        for name, score, _ in insights.get_top_destinations(n=50)
        if name == destination
    )


class TestNoteSignal:
    def test_placeholder_note_is_not_a_real_note(self) -> None:
        assert real_note(_pin(notes=GEOCODE_PENDING)) is None
        assert real_note(_pin(notes="  ")) is None
        assert real_note(_pin(notes="")) is None
        assert real_note(_pin(notes="Matcha capital")) == "Matcha capital"

    def test_note_quoting_the_placeholder_still_counts(self) -> None:
        note = f"Was '{GEOCODE_PENDING}' but I actually want to go"
        assert real_note(_pin(notes=note)) == note

    def test_placeholder_scores_the_same_as_no_note(self) -> None:
        pins = [
            _pin(name="A", city="Placeholderville", country="Placeholderland",
                 notes=GEOCODE_PENDING),
            _pin(name="B", city="Blankville", country="Blankland", notes=""),
            _pin(name="C", city="Realville", country="Realland",
                 notes="Street food\nNight market"),
        ]
        ins = DestinationInsights(pins)
        assert _score_of(ins, "Placeholderland") == _score_of(ins, "Blankland")
        assert _score_of(ins, "Realland") > _score_of(ins, "Blankland")

    def test_note_density_outranks_pin_count(self) -> None:
        """The regression this scoring rewrite exists to fix.

        Bulkland is saved 10 times across 10 cities with nothing written about it;
        Noteland is saved twice but annotated in detail. Noteland is what the user
        actually wants.
        """
        bulk = [
            _pin(name=f"Place {i}", city=f"City {i}", country="Bulkland")
            for i in range(10)
        ]
        notes = [
            _pin(name="Food", city="Hanoi", country="Noteland",
                 notes="Bun bo hue\nCom tam\nBanh goi\nEgg coffee"),
            _pin(name="Region", city="Hue", country="Noteland",
                 notes="Cao lau\nBanh beo\nBun bo"),
        ]
        ranking = _rank(DestinationInsights(bulk + notes))
        assert ranking.index("Noteland") < ranking.index("Bulkland")

    def test_one_long_note_competes_with_several_short_ones(self) -> None:
        """Depth is per annotated pin, so a single thorough note is not penalised."""
        deep = [
            _pin(name="Thailand", city="Bangkok", country="Deepland",
                 notes="Khao soi\nLaab\nCustard apple\nCoconut milk\nKratom"),
            _pin(name="Bare", city="Chiang Mai", country="Deepland"),
        ]
        shallow = [
            _pin(name="A", city="Alpha", country="Shallowland", notes="Nice"),
            _pin(name="B", city="Beta", country="Shallowland", notes="Good"),
        ]
        ranking = _rank(DestinationInsights(deep + shallow))
        assert ranking.index("Deepland") < ranking.index("Shallowland")


class TestDegenerateComponents:
    def test_minmax_norm_returns_zero_when_all_equal(self) -> None:
        """Returning 1.0 here is what silently inflated every destination's score."""
        assert _minmax_norm(5.0, [5.0, 5.0, 5.0]) == 0.0
        assert _minmax_norm(0.0, [0.0, 10.0]) == 0.0
        assert _minmax_norm(10.0, [0.0, 10.0]) == 1.0

    def test_constant_list_and_priority_do_not_affect_ranking(self) -> None:
        """Every real pin shares one list and priority; that must contribute nothing."""
        pins = [
            _pin(name="A", city="Alpha", country="Alphaland", notes="one\ntwo"),
            _pin(name="B", city="Beta", country="Betaland", notes="one"),
        ]
        varied = [
            _pin(name="A", city="Alpha", country="Alphaland", notes="one\ntwo",
                 list_name="Want To Go"),
            _pin(name="B", city="Beta", country="Betaland", notes="one",
                 list_name="Reviews"),
        ]
        for pin in varied:
            pin.user_priority = 1

        assert DestinationInsights(pins).get_top_destinations() == \
            DestinationInsights(varied).get_top_destinations()

    def test_no_varying_signal_yields_equal_scores(self) -> None:
        """With nothing to separate them, don't fabricate a ranking."""
        pins = [
            _pin(name="A", city="Alpha", country="Alphaland"),
            _pin(name="B", city="Beta", country="Betaland"),
        ]
        scores = {s for _, s, _ in DestinationInsights(pins).get_top_destinations()}
        assert len(scores) == 1


class TestDestinationBoost:
    def _pins(self) -> List[SavedLocation]:
        return [
            _pin(name="A", city="Alpha", country="Alphaland", notes="one\ntwo\nthree"),
            _pin(name="B", city="Beta", country="Betaland", notes="one\ntwo"),
            _pin(name="C", city="Gamma", country="Gammaland", notes="one"),
        ]

    def test_default_boosts_are_a_no_op(self) -> None:
        pins = self._pins()
        baseline = DestinationInsights(pins).get_top_destinations()
        for boosts in ({}, None, {name: BOOST_DEFAULT for name in
                                  ("Alphaland", "Betaland", "Gammaland")}):
            assert DestinationInsights(pins, boosts=boosts).get_top_destinations() == \
                baseline

    def test_boost_promotes_a_destination(self) -> None:
        pins = self._pins()
        assert _rank(DestinationInsights(pins))[-1] == "Gammaland"
        boosted = _rank(DestinationInsights(pins, boosts={"Gammaland": 3.0}))
        assert boosted[0] == "Gammaland"

    def test_boost_below_one_demotes(self) -> None:
        pins = self._pins()
        assert _rank(DestinationInsights(pins))[0] == "Alphaland"
        demoted = _rank(DestinationInsights(pins, boosts={"Alphaland": BOOST_MIN}))
        assert demoted[-1] == "Alphaland"

    def test_boosted_scores_stay_in_range(self) -> None:
        pins = self._pins()
        ins = DestinationInsights(pins, boosts={"Alphaland": BOOST_MAX})
        for _, score, _ in ins.get_top_destinations():
            assert 0.0 <= score <= 100.0

    def test_clamp_boost(self) -> None:
        assert clamp_boost(99.0) == BOOST_MAX
        assert clamp_boost(-5.0) == BOOST_MIN
        assert clamp_boost(1.5) == 1.5
        assert clamp_boost("not a number") == BOOST_DEFAULT
        assert clamp_boost(None) == BOOST_DEFAULT

    def test_repository_round_trip(self, tmp_db: PinRepository) -> None:
        assert tmp_db.get_destination_boosts() == {}

        tmp_db.set_destination_boost("Indonesia", 2.0)
        tmp_db.set_destination_boost("Vietnam", 99.0)  # clamped
        assert tmp_db.get_destination_boosts() == {"Indonesia": 2.0, "Vietnam": BOOST_MAX}

        tmp_db.set_destination_boost("Indonesia", 1.5)
        assert tmp_db.get_destination_boosts()["Indonesia"] == 1.5

        # Resetting to the default drops the row so it matches an untouched DB.
        tmp_db.set_destination_boost("Indonesia", BOOST_DEFAULT)
        tmp_db.set_destination_boost("Vietnam", BOOST_DEFAULT)
        assert tmp_db.get_destination_boosts() == {}


# ------------------------------------------------------------------ #
# haversine helper                                                     #
# ------------------------------------------------------------------ #

class TestHaversine:
    def test_same_point_is_zero(self) -> None:
        assert haversine_km(51.5, -0.1, 51.5, -0.1) == pytest.approx(0.0)

    def test_london_paris_approx(self) -> None:
        # London → Paris ≈ 340 km
        dist = haversine_km(51.5074, -0.1276, 48.8566, 2.3522)
        assert 330 < dist < 360

    def test_symmetry(self) -> None:
        a = haversine_km(51.5, -0.1, 48.8, 2.3)
        b = haversine_km(48.8, 2.3, 51.5, -0.1)
        assert abs(a - b) < 0.001
