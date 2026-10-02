"""Tests for recurring annual season-window matching helpers."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

_TRAVEL = Path(__file__).parent.parent
if str(_TRAVEL) not in sys.path:
    sys.path.insert(0, str(_TRAVEL))

from travel_atlas.seasonal_matching import (
    date_range_touches_window,
    is_valid_month_day,
    month_day,
    month_day_in_window,
)


def test_month_day_formats_a_date() -> None:
    assert month_day(date(2026, 5, 26)) == "05-26"


def test_is_valid_month_day() -> None:
    assert is_valid_month_day(None)
    assert is_valid_month_day("05-26")
    assert not is_valid_month_day("2026-05-26")
    assert not is_valid_month_day("bad")


def test_month_day_in_window_normal_range() -> None:
    assert month_day_in_window("05-26", "05-15", "06-15")
    assert not month_day_in_window("07-01", "05-15", "06-15")


def test_month_day_in_window_wraps_year_boundary() -> None:
    assert month_day_in_window("01-02", "12-15", "01-15")
    assert month_day_in_window("12-20", "12-15", "01-15")
    assert not month_day_in_window("06-01", "12-15", "01-15")


def test_date_range_touches_window_single_day() -> None:
    assert date_range_touches_window(date(2026, 5, 26), date(2026, 5, 26), "05-15", "06-15")
    assert not date_range_touches_window(date(2026, 7, 1), date(2026, 7, 1), "05-15", "06-15")


def test_date_range_touches_window_multi_day_overlap() -> None:
    assert date_range_touches_window(date(2026, 6, 10), date(2026, 6, 20), "05-15", "06-15")
    assert not date_range_touches_window(date(2026, 6, 20), date(2026, 6, 25), "05-15", "06-15")


def test_date_range_touches_window_wraps_year_boundary() -> None:
    assert date_range_touches_window(date(2026, 12, 30), date(2027, 1, 5), "12-15", "01-15")


def test_date_range_touches_window_reverse_range_is_false() -> None:
    assert not date_range_touches_window(date(2026, 6, 1), date(2026, 5, 1), "05-15", "06-15")


def test_date_range_touches_window_caps_span() -> None:
    assert date_range_touches_window(
        date(2026, 1, 1), date(2027, 1, 1), "06-01", "06-02", max_span_days=10
    ) is False
