"""When is this place actually bearable? Monthly climate normals from Open-Meteo.

Open-Meteo's historical archive is free, keyless and unmetered for this volume, so a
destination's real ten-year climatology can be computed rather than guessed. Daily
records are folded into per-month averages once and cached in ``climate_normals``.

The ranking answers a specific question — *which months are not unpleasantly hot and
wet* — via :func:`best_months`. Comfort is scored from daytime heat and rainfall only.
It knows nothing about festivals, crowds or prices, and humidity is represented only
indirectly through rainfall, so treat it as a first filter and not a verdict.
"""

from __future__ import annotations

import calendar
import json
import sqlite3
import statistics
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Optional, Sequence

ARCHIVE_API = "https://archive-api.open-meteo.com/v1/archive"

#: Years of history folded into the normals. Ten is enough to smooth out odd seasons
#: without reaching so far back that the average misrepresents the current climate.
DEFAULT_YEARS = 10

#: Daily highs above this are what "hot as hell" means in practice.
COMFORT_CEILING_C = 30.0
#: Below this, heat stops being the limiting factor at all.
COMFORT_FLOOR_C = 18.0
#: Monthly rainfall at or above this reads as a wet season month.
WET_MONTH_MM = 150.0


@dataclass(frozen=True)
class MonthClimate:
    month: int
    avg_high_c: float
    avg_low_c: float
    rain_mm: float
    wet_days: float

    @property
    def name(self) -> str:
        return calendar.month_name[self.month]

    @property
    def abbr(self) -> str:
        return calendar.month_abbr[self.month]

    def comfort_score(self) -> float:
        """0–100, higher is more comfortable. Heat dominates, rain penalises."""
        heat = (self.avg_high_c - COMFORT_FLOOR_C) / (
            COMFORT_CEILING_C - COMFORT_FLOOR_C
        )
        heat_penalty = min(1.0, max(0.0, heat))
        rain_penalty = min(1.0, self.rain_mm / (WET_MONTH_MM * 2))
        return round(100 * (1 - (0.65 * heat_penalty + 0.35 * rain_penalty)), 1)

    def mosquito_pressure(self) -> str:
        """Rough proxy, not an entomological measurement.

        Mosquito activity tracks standing water and warmth, so warm wet months are
        flagged as higher risk. This is a heuristic from rainfall and temperature only —
        it is not a dengue or malaria forecast, and it does not know about altitude,
        drainage or local control programmes.
        """
        if self.avg_high_c < 18:
            return "low"
        if self.rain_mm >= WET_MONTH_MM:
            return "high"
        if self.rain_mm >= WET_MONTH_MM / 2:
            return "moderate"
        return "low"


def best_months(months: Sequence[MonthClimate], n: int = 3) -> list[MonthClimate]:
    """The *n* most comfortable months, best first."""
    return sorted(months, key=lambda m: -m.comfort_score())[:n]


class ClimateService:
    """Fetches and caches monthly climate normals for a coordinate."""

    def __init__(self, atlas_db_path: Path, *, years: int = DEFAULT_YEARS) -> None:
        self.path = Path(atlas_db_path)
        self.years = years

    def get_normals(
        self,
        latitude: float,
        longitude: float,
        *,
        allow_network: bool = True,
        timeout: int = 60,
    ) -> list[MonthClimate]:
        """Twelve months of normals, or ``[]`` when unavailable offline."""
        if latitude == 0 and longitude == 0:
            return []

        end_year = date.today().year - 1
        start_year = end_year - self.years + 1
        key = self._cache_key(latitude, longitude, start_year, end_year)

        cached = self._read_cache(key)
        if cached is not None:
            return cached

        if not allow_network:
            return []

        months = self._fetch(latitude, longitude, start_year, end_year, timeout)
        if months:
            self._write_cache(key, latitude, longitude, start_year, end_year, months)
        return months

    # ---------------------------------------------------------------- #
    # Fetch                                                              #
    # ---------------------------------------------------------------- #

    def _fetch(
        self,
        latitude: float,
        longitude: float,
        start_year: int,
        end_year: int,
        timeout: int,
    ) -> list[MonthClimate]:
        params = {
            "latitude": round(latitude, 3),
            "longitude": round(longitude, 3),
            "start_date": f"{start_year}-01-01",
            "end_date": f"{end_year}-12-31",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
            "timezone": "auto",
        }
        url = f"{ARCHIVE_API}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers={"User-Agent": "TravelAtlas/0.1"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
            return []

        daily = payload.get("daily") or {}
        return _fold_to_months(
            daily.get("time") or [],
            daily.get("temperature_2m_max") or [],
            daily.get("temperature_2m_min") or [],
            daily.get("precipitation_sum") or [],
            years=end_year - start_year + 1,
        )

    # ---------------------------------------------------------------- #
    # Cache                                                              #
    # ---------------------------------------------------------------- #

    @staticmethod
    def _cache_key(lat: float, lon: float, start_year: int, end_year: int) -> str:
        # ~11 km resolution: far finer than climate varies, coarse enough that nearby
        # pins in the same city share one cached answer.
        return f"{round(lat, 1)}|{round(lon, 1)}|{start_year}-{end_year}"

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _read_cache(self, key: str) -> Optional[list[MonthClimate]]:
        if not self.path.exists():
            return None
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT payload FROM climate_normals WHERE cache_key = ?", (key,)
                ).fetchone()
        except sqlite3.OperationalError:
            return None
        if not row:
            return None
        try:
            return [MonthClimate(**item) for item in json.loads(row["payload"])]
        except (json.JSONDecodeError, TypeError):
            return None

    def _write_cache(
        self,
        key: str,
        latitude: float,
        longitude: float,
        start_year: int,
        end_year: int,
        months: list[MonthClimate],
    ) -> None:
        if not self.path.exists():
            return
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO climate_normals(
                        cache_key, latitude, longitude, start_year, end_year, payload
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(cache_key) DO UPDATE SET
                        payload=excluded.payload,
                        fetched_at=CURRENT_TIMESTAMP
                    """,
                    (
                        key,
                        latitude,
                        longitude,
                        start_year,
                        end_year,
                        json.dumps([asdict(m) for m in months]),
                    ),
                )
                conn.commit()
        except sqlite3.OperationalError:
            return


def _fold_to_months(
    days: Sequence[str],
    highs: Sequence[Optional[float]],
    lows: Sequence[Optional[float]],
    rain: Sequence[Optional[float]],
    *,
    years: int,
) -> list[MonthClimate]:
    """Collapse daily records into one row per calendar month."""
    buckets: dict[int, dict[str, list[float]]] = {
        m: {"high": [], "low": [], "rain": []} for m in range(1, 13)
    }
    wet_days: dict[int, int] = dict.fromkeys(range(1, 13), 0)

    for day, high, low, precipitation in zip(days, highs, lows, rain):
        try:
            month = int(day[5:7])
        except (ValueError, IndexError):
            continue
        if high is not None:
            buckets[month]["high"].append(high)
        if low is not None:
            buckets[month]["low"].append(low)
        if precipitation is not None:
            buckets[month]["rain"].append(precipitation)
            if precipitation >= 1.0:
                wet_days[month] += 1

    months: list[MonthClimate] = []
    for month in range(1, 13):
        values = buckets[month]
        if not values["high"]:
            continue
        months.append(
            MonthClimate(
                month=month,
                avg_high_c=round(statistics.mean(values["high"]), 1),
                avg_low_c=round(
                    statistics.mean(values["low"]) if values["low"] else 0.0, 1
                ),
                # Totals are per-year, so divide the summed history by the span.
                rain_mm=round(sum(values["rain"]) / max(1, years), 1),
                wet_days=round(wet_days[month] / max(1, years), 1),
            )
        )
    return months
