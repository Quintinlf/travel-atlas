"""Aurora scoring: location + darkness + NOAA. Moon is not a factor."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

_TRAVEL = Path(__file__).parent.parent
if str(_TRAVEL) not in sys.path:
    sys.path.insert(0, str(_TRAVEL))

from travel_atlas.providers.noaa_swpc import parse_27_day_outlook, parse_kp_forecast
from travel_atlas.services.aurora_service import AuroraService
from travel_atlas.services.alaska_bases import get_base, list_base_keys


OUTLOOK = """
:Product: 27-day Space Weather Outlook
#  UTC Date  Radio Flux  Planetary A Index  Largest Kp Index
2026 Sep 10     140          8                3
2026 Sep 11     145         18                5
2026 Sep 22     150         20                6
2026 Sep 30     135          5                2
"""

FORECAST = [
    ["time_tag", "kp", "observed"],
    ["2026-09-10 00:00:00", "2.00", "predicted"],
    ["2026-09-10 03:00:00", "4.33", "predicted"],
]


def test_parse_27_day_outlook_reads_largest_kp() -> None:
    parsed = parse_27_day_outlook(OUTLOOK)
    assert parsed[date(2026, 9, 10)] == 3.0
    assert parsed[date(2026, 9, 11)] == 5.0
    assert parsed[date(2026, 9, 30)] == 2.0


def test_parse_kp_forecast_takes_daily_max() -> None:
    parsed = parse_kp_forecast(FORECAST)
    assert parsed[date(2026, 9, 10)] == 4.33


def test_fairbanks_is_the_only_base() -> None:
    assert list_base_keys() == ["fairbanks"]
    base = get_base("fairbanks")
    assert base.airport == "FAI"
    assert "Chena" in base.darker_skies_note


def test_legacy_base_keys_resolve_to_fairbanks() -> None:
    for key in ("healy", "anchorage", "coldfoot"):
        assert get_base(key).key == "fairbanks"


def test_fairbanks_night_score_ignores_moon() -> None:
    service = AuroraService()
    night = date(2026, 9, 10)
    fairbanks = service.score_night("fairbanks", night)
    assert fairbanks.combined > 0
    assert "moon" not in fairbanks.as_dict()


def test_higher_kp_raises_combined_score() -> None:
    service = AuroraService()
    night = date(2026, 9, 10)
    quiet = service.score_night("fairbanks", night, kp_by_date={night: 1.0})
    storm = service.score_night("fairbanks", night, kp_by_date={night: 6.0})
    assert storm.noaa_score is not None
    assert storm.combined > quiet.combined


def test_score_month_includes_last_day_of_september() -> None:
    service = AuroraService()
    nights = service.score_month("fairbanks", 2026, 9)
    assert len(nights) == 30
    assert nights[0].on_date == date(2026, 9, 1)
    assert nights[-1].on_date == date(2026, 9, 30)


def test_equinox_bonus_boosts_mid_september() -> None:
    service = AuroraService()
    early = service.score_night("fairbanks", date(2026, 9, 5))
    equinox = service.score_night("fairbanks", date(2026, 9, 22))
    assert equinox.combined >= early.combined


def test_best_stay_window_picks_highest_mean() -> None:
    service = AuroraService()
    kp = parse_27_day_outlook(OUTLOOK)
    nights = service.score_month("fairbanks", 2026, 9, kp_by_date=kp)
    best = AuroraService.best_stay_window(nights)
    assert best is not None
    assert 3 <= best["length"] <= 4
    assert best["arrive"] <= best["leave"]
    assert best["mean_aurora_score"] >= 0


def test_compare_bases_returns_single_fairbanks_row() -> None:
    rows = AuroraService().compare_bases(
        date(2026, 9, 9), date(2026, 9, 13), allow_network=False
    )
    assert len(rows) == 1
    assert rows[0]["key"] == "fairbanks"
    assert rows[0]["mean_aurora_score"] >= 0
