"""Cloud-cover overlay and DIY vs guided aurora recommendations."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Mapping

from travel_atlas.providers.open_meteo_weather import OpenMeteoWeatherProvider
from travel_atlas.services.alaska_bases import AlaskaAuroraBase, get_base

CHENA_PULLOUT_MAPS = (
    "https://www.google.com/maps/search/Chena+Hot+Springs+Road+aurora+viewing+Fairbanks"
)
AURORA_TOUR_MAPS = "https://www.google.com/maps/search/Fairbanks+aurora+tour"

# Cloud cover thresholds (daily mean, 0–100%).
DIY_OK_MAX = 35.0
CONSIDER_TOUR_MAX = 60.0


def cloud_recommendation(cloud_cover_pct: float | None) -> str:
    """Return diy_ok | consider_tour | tour_recommended | unknown."""
    if cloud_cover_pct is None:
        return "unknown"
    if cloud_cover_pct <= DIY_OK_MAX:
        return "diy_ok"
    if cloud_cover_pct <= CONSIDER_TOUR_MAX:
        return "consider_tour"
    return "tour_recommended"


def recommendation_label(key: str) -> str:
    return {
        "diy_ok": "DIY OK — clear enough from outskirts",
        "consider_tour": "Mixed — DIY or one guided night",
        "tour_recommended": "Cloudy — book a guided chase",
        "unknown": "Unknown — use historical odds",
    }.get(key, key)


def build_aurora_weather_report(
    *,
    arrive: date,
    leave: date,
    base: AlaskaAuroraBase | str | None = None,
    allow_network: bool = True,
    provider: OpenMeteoWeatherProvider | None = None,
) -> dict[str, Any]:
    """Per-night cloud cover and viewing strategy for a Fairbanks stay."""
    resolved = get_base(base) if base else get_base("fairbanks")
    weather = provider or OpenMeteoWeatherProvider()

    hist: dict[str, Any] = {}
    if allow_network:
        hist_result = weather.historical_month_cloud_stats(
            latitude=resolved.latitude,
            longitude=resolved.longitude,
            month=arrive.month,
        )
        if hist_result.status == "ok":
            hist = dict(hist_result.payload)

    forecast_by_date: dict[str, float] = {}
    forecast_note = ""
    if allow_network:
        last_night = leave - timedelta(days=1)
        forecast_result = weather.forecast_range(
            latitude=resolved.latitude,
            longitude=resolved.longitude,
            start=arrive,
            end=last_night,
        )
        payload = dict(forecast_result.payload or {})
        forecast_by_date = dict(payload.get("by_date") or {})
        if forecast_result.status != "ok":
            forecast_note = str(payload.get("message") or "Live forecast unavailable.")

    nights: list[dict[str, Any]] = []
    cursor = arrive
    last_night = leave - timedelta(days=1)
    while cursor <= last_night:
        iso = cursor.isoformat()
        cloud = forecast_by_date.get(iso)
        source = "forecast" if cloud is not None else "historical"
        rec = cloud_recommendation(cloud)
        if cloud is None and hist:
            mean = float(hist.get("mean_cloud_cover_pct") or 0)
            cloud = mean
            rec = cloud_recommendation(mean)
        nights.append(
            {
                "date": iso,
                "cloud_cover_pct": cloud,
                "source": source,
                "recommendation": rec,
                "recommendation_label": recommendation_label(rec),
            }
        )
        cursor += timedelta(days=1)

    diy_nights = sum(1 for n in nights if n["recommendation"] == "diy_ok")
    tour_nights = sum(1 for n in nights if n["recommendation"] == "tour_recommended")

    if forecast_by_date:
        strategy = (
            "Live cloud forecast is available for your aurora nights. "
            "DIY from Chena Hot Springs Road pullouts is fine on clear nights; "
            "book a cancelable guided tour for cloudy nights."
        )
    elif hist:
        clear_pct = hist.get("clear_night_pct")
        strategy = (
            f"Trip is too far out for a day-specific forecast. Historical {arrive.strftime('%B')} "
            f"shows ~{clear_pct}% of nights with cloud cover ≤50% at Fairbanks. "
            "Plan DIY as default; budget one optional guided tour ($150–300 for 2) as insurance."
        )
    else:
        strategy = (
            "Cloud data unavailable offline. Fairbanks is aurora-capable on clear nights — "
            "DIY from darker outskirts works; guided tours help on cloudy nights."
        )

    return {
        "nights": nights,
        "historical": hist,
        "forecast_note": forecast_note,
        "has_live_forecast": bool(forecast_by_date),
        "diy_night_count": diy_nights,
        "tour_recommended_count": tour_nights,
        "strategy_summary": strategy,
        "chena_maps_url": CHENA_PULLOUT_MAPS,
        "tour_maps_url": AURORA_TOUR_MAPS,
        "aurora_tour_cost_party_usd": (150, 300),
    }
