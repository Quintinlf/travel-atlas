"""Tests for the local, offline sky-event computation adapter."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

_TRAVEL = Path(__file__).parent.parent
if str(_TRAVEL) not in sys.path:
    sys.path.insert(0, str(_TRAVEL))

from travel_atlas.adapters import AstronomyAdapter, SkySnapshot
from travel_atlas.astronomy import AstralAstronomyAdapter


def _event_keys(snapshot: SkySnapshot) -> set[str]:
    return {event.key for event in snapshot.events}


def test_perseids_peak_on_august_12() -> None:
    adapter = AstralAstronomyAdapter()
    snapshot = adapter.fetch(latitude=35.6762, longitude=139.6503, on_date=date(2026, 8, 12))
    assert "meteor_shower_perseids" in _event_keys(snapshot)


def test_geminids_peak_on_december_14() -> None:
    adapter = AstralAstronomyAdapter()
    snapshot = adapter.fetch(latitude=35.6762, longitude=139.6503, on_date=date(2026, 12, 14))
    assert "meteor_shower_geminids" in _event_keys(snapshot)


def test_neutral_date_has_no_meteor_shower_event() -> None:
    adapter = AstralAstronomyAdapter()
    snapshot = adapter.fetch(latitude=35.6762, longitude=139.6503, on_date=date(2026, 2, 14))
    assert not any(key.startswith("meteor_shower_") for key in _event_keys(snapshot))
    assert "day_length" in _event_keys(snapshot)
    assert "moon_phase" in _event_keys(snapshot)
    assert "solar_year_position" in _event_keys(snapshot)


def test_june_solstice_is_a_landmark_event() -> None:
    adapter = AstralAstronomyAdapter()
    snapshot = adapter.fetch(latitude=48.0196, longitude=66.9237, on_date=date(2026, 6, 21))
    kinds = {event.kind for event in snapshot.events}
    assert "solstice" in kinds


def test_polar_latitude_does_not_raise() -> None:
    adapter = AstralAstronomyAdapter()
    snapshot = adapter.fetch(latitude=78.2232, longitude=15.6267, on_date=date(2026, 6, 21))
    assert snapshot.events  # moon phase / solar year position still present


def test_astronomy_adapter_contract_allows_swappable_implementation() -> None:
    class ExampleAdapter:
        key = "mcp-astronomy-v1"

        def fetch(self, *, latitude: float, longitude: float, on_date: date) -> SkySnapshot:
            raise NotImplementedError

    assert isinstance(ExampleAdapter(), AstronomyAdapter)
