"""Tests for aurora cloud-cover recommendations."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

_TRAVEL = Path(__file__).parent.parent
if str(_TRAVEL) not in sys.path:
    sys.path.insert(0, str(_TRAVEL))

from travel_atlas.providers.base import StubResult
from travel_atlas.services.aurora_weather import (
    build_aurora_weather_report,
    cloud_recommendation,
    recommendation_label,
)


class _FakeWeather:
    def historical_month_cloud_stats(self, **kwargs):
        return StubResult(
            provider="fake",
            status="ok",
            payload={
                "month": 9,
                "mean_cloud_cover_pct": 55.0,
                "clear_night_pct": 42.0,
                "clear_night_threshold_pct": 50.0,
            },
        )

    def forecast_range(self, **kwargs):
        return StubResult(
            provider="fake",
            status="ok",
            payload={
                "by_date": {
                    "2026-09-26": 25.0,
                    "2026-09-27": 70.0,
                    "2026-09-28": 40.0,
                    "2026-09-29": 30.0,
                }
            },
        )


def test_cloud_recommendation_thresholds():
    assert cloud_recommendation(20.0) == "diy_ok"
    assert cloud_recommendation(45.0) == "consider_tour"
    assert cloud_recommendation(80.0) == "tour_recommended"
    assert cloud_recommendation(None) == "unknown"


def test_recommendation_label():
    assert "DIY" in recommendation_label("diy_ok")
    assert "guided" in recommendation_label("tour_recommended").lower()


def test_build_aurora_weather_report_with_fake_provider():
    report = build_aurora_weather_report(
        arrive=date(2026, 9, 26),
        leave=date(2026, 9, 30),
        allow_network=True,
        provider=_FakeWeather(),  # type: ignore[arg-type]
    )
    assert len(report["nights"]) == 4
    assert report["has_live_forecast"] is True
    assert report["nights"][0]["recommendation"] == "diy_ok"
    assert report["nights"][1]["recommendation"] == "tour_recommended"
    assert report["historical"]["clear_night_pct"] == 42.0


def test_build_aurora_weather_report_offline():
    report = build_aurora_weather_report(
        arrive=date(2026, 9, 26),
        leave=date(2026, 9, 30),
        allow_network=False,
    )
    assert len(report["nights"]) == 4
    assert report["has_live_forecast"] is False
