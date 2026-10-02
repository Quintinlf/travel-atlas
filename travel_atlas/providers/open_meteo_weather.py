"""Open-Meteo weather — free forecast and historical cloud cover."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from typing import Any

from .base import StubResult

FORECAST_API = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_API = "https://archive-api.open-meteo.com/v1/archive"
DEFAULT_YEARS = 10
# Nights with mean cloud cover below this count as historically "clear enough" for DIY.
CLEAR_NIGHT_CLOUD_MAX = 50.0


class OpenMeteoWeatherProvider:
    key = "open-meteo-v1"

    def forecast_range(
        self,
        *,
        latitude: float,
        longitude: float,
        start: date,
        end: date,
        timeout: int = 30,
    ) -> StubResult:
        """Daily mean cloud cover (0–100%) for an inclusive date range."""
        today = date.today()
        if end < today:
            return StubResult(
                provider=self.key,
                status="unavailable",
                payload={
                    "message": "Forecast only covers today and future dates.",
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                },
            )
        fetch_start = max(start, today)
        if fetch_start > end:
            return StubResult(
                provider=self.key,
                status="unavailable",
                payload={
                    "message": "Trip dates are beyond the forecast window from today.",
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                },
            )
        params = {
            "latitude": round(latitude, 4),
            "longitude": round(longitude, 4),
            "start_date": fetch_start.isoformat(),
            "end_date": end.isoformat(),
            "daily": "cloud_cover_mean",
            "timezone": "auto",
        }
        payload = self._get_json(FORECAST_API, params, timeout)
        if not payload:
            return StubResult(
                provider=self.key,
                status="unavailable",
                payload={"message": "Open-Meteo forecast request failed."},
            )
        daily = payload.get("daily") or {}
        by_date = _daily_cloud_map(
            daily.get("time") or [],
            daily.get("cloud_cover_mean") or [],
        )
        return StubResult(
            provider=self.key,
            status="ok",
            payload={
                "source": "forecast",
                "by_date": by_date,
                "start": fetch_start.isoformat(),
                "end": end.isoformat(),
            },
        )

    def historical_month_cloud_stats(
        self,
        *,
        latitude: float,
        longitude: float,
        month: int,
        years: int = DEFAULT_YEARS,
        timeout: int = 60,
    ) -> StubResult:
        """September-style climatology: mean cloud cover and clear-night share."""
        end_year = date.today().year - 1
        start_year = end_year - years + 1
        params = {
            "latitude": round(latitude, 4),
            "longitude": round(longitude, 4),
            "start_date": f"{start_year}-{month:02d}-01",
            "end_date": f"{end_year}-{month:02d}-{_last_day(end_year, month):02d}",
            "daily": "cloud_cover_mean",
            "timezone": "auto",
        }
        payload = self._get_json(ARCHIVE_API, params, timeout)
        if not payload:
            return StubResult(
                provider=self.key,
                status="unavailable",
                payload={"message": "Open-Meteo archive request failed."},
            )
        daily = payload.get("daily") or {}
        values: list[float] = []
        clear = 0
        total = 0
        for day, cloud in zip(daily.get("time") or [], daily.get("cloud_cover_mean") or []):
            if cloud is None:
                continue
            try:
                if int(day[5:7]) != month:
                    continue
            except (ValueError, IndexError):
                continue
            total += 1
            values.append(float(cloud))
            if float(cloud) <= CLEAR_NIGHT_CLOUD_MAX:
                clear += 1
        if not values:
            return StubResult(
                provider=self.key,
                status="unavailable",
                payload={"message": f"No historical cloud data for month {month}."},
            )
        mean_cloud = round(sum(values) / len(values), 1)
        clear_pct = round(100.0 * clear / total, 1)
        return StubResult(
            provider=self.key,
            status="ok",
            payload={
                "source": "historical",
                "month": month,
                "years": years,
                "mean_cloud_cover_pct": mean_cloud,
                "clear_night_pct": clear_pct,
                "clear_night_threshold_pct": CLEAR_NIGHT_CLOUD_MAX,
                "sample_days": total,
            },
        )

    @staticmethod
    def _get_json(base_url: str, params: dict[str, Any], timeout: int) -> dict[str, Any] | None:
        url = f"{base_url}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers={"User-Agent": "TravelAtlas/0.1"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
            return None


def _daily_cloud_map(days: list[str], clouds: list[Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for day, cloud in zip(days, clouds):
        if cloud is None:
            continue
        out[str(day)] = round(float(cloud), 1)
    return out


def _last_day(year: int, month: int) -> int:
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    return (next_month - timedelta(days=1)).day
