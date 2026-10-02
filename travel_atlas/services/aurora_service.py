"""Aurora visibility scoring for a stay-put Alaska trip.

Moon illumination is ignored on purpose — the ranking is about whether
the night is dark enough and whether the place is far enough north that
a typical Kp storm is visible. NOAA Kp is an optional near-term overlay.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta, timezone
from typing import Any, Mapping, Sequence

from astral import Observer
from astral.sun import sun

from travel_atlas.providers.base import StubResult
from travel_atlas.providers.noaa_swpc import NoaaSwpcProvider

from .alaska_bases import ALASKA_AURORA_BASES, AlaskaAuroraBase, get_base


def _local_timezone(longitude: float) -> timezone:
    offset_hours = round(longitude / 15)
    return timezone(timedelta(hours=offset_hours))


def night_hours(latitude: float, longitude: float, on_date: date) -> float | None:
    """Hours from sunset to the next sunrise. None during polar day/night."""
    observer = Observer(latitude=latitude, longitude=longitude)
    tz = _local_timezone(longitude)
    try:
        today = sun(observer, date=on_date, tzinfo=tz)
        tomorrow = sun(observer, date=on_date + timedelta(days=1), tzinfo=tz)
    except ValueError:
        return None
    sunset = today.get("sunset")
    sunrise = tomorrow.get("sunrise")
    if sunset is None or sunrise is None:
        return None
    hours = (sunrise - sunset).total_seconds() / 3600
    if hours < 0:
        hours += 24
    return round(hours, 2)


def _darkness_score(hours: float | None) -> float:
    if hours is None or hours < 1.0:
        return 0.0
    return round(min(100.0, (hours / 8.0) * 100.0), 1)


def _location_score(typical_kp: float) -> float:
    """Lower typical Kp needed = better odds on a quiet night."""
    return round(max(0.0, 100.0 * (1.0 - (typical_kp - 1.0) / 6.0)), 1)


def _noaa_score(kp: float | None, typical_kp: float) -> float | None:
    if kp is None:
        return None
    return round(max(0.0, min(100.0, 50.0 + (kp - typical_kp) * 20.0)), 1)


def _equinox_bonus(on_date: date) -> float:
    """Geomagnetic storms cluster around the September equinox (~the 22nd)."""
    if on_date.month == 9 and 15 <= on_date.day <= 29:
        return 5.0
    return 0.0


def _combine(location: float, darkness: float, noaa: float | None, bonus: float) -> float:
    if noaa is None:
        raw = 0.65 * location + 0.35 * darkness
    else:
        raw = 0.45 * location + 0.25 * darkness + 0.30 * noaa
    return round(min(100.0, raw + bonus), 1)


@dataclass(frozen=True)
class NightScore:
    on_date: date
    night_hours: float | None
    location_score: float
    darkness_score: float
    noaa_kp: float | None
    noaa_score: float | None
    combined: float
    visible_enough: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "date": self.on_date.isoformat(),
            "night_hours": self.night_hours,
            "location_score": self.location_score,
            "darkness_score": self.darkness_score,
            "noaa_kp": self.noaa_kp,
            "noaa_score": self.noaa_score,
            "combined": self.combined,
            "visible_enough": self.visible_enough,
        }


class AuroraService:
    def __init__(self, noaa_provider: NoaaSwpcProvider | None = None) -> None:
        self.noaa_provider = noaa_provider or NoaaSwpcProvider()

    def score_night(
        self,
        base: AlaskaAuroraBase | str,
        on_date: date,
        *,
        kp_by_date: Mapping[date, float] | None = None,
    ) -> NightScore:
        resolved = get_base(base) if isinstance(base, str) else base
        hours = night_hours(resolved.latitude, resolved.longitude, on_date)
        location = _location_score(resolved.typical_kp_visible)
        darkness = _darkness_score(hours)
        kp = None
        if kp_by_date is not None:
            kp = kp_by_date.get(on_date)
        noaa = _noaa_score(kp, resolved.typical_kp_visible)
        bonus = _equinox_bonus(on_date)
        combined = _combine(location, darkness, noaa, bonus)
        return NightScore(
            on_date=on_date,
            night_hours=hours,
            location_score=location,
            darkness_score=darkness,
            noaa_kp=kp,
            noaa_score=noaa,
            combined=combined,
            visible_enough=hours is not None and hours >= 2.0 and combined >= 45.0,
        )

    def score_window(
        self,
        base: AlaskaAuroraBase | str,
        start: date,
        end: date,
        *,
        kp_by_date: Mapping[date, float] | None = None,
        inclusive_end: bool = False,
    ) -> list[NightScore]:
        """Score aurora nights from *start* through the last scored night.

        For trip stays, pass the leave/check-out date as *end* (exclusive) so
        arrive Sep 9 / leave Sep 13 scores Sep 9–12. For calendar months, set
        ``inclusive_end=True`` so Sep 1–Sep 30 includes the 30th.
        """
        if end < start:
            start, end = end, start
        nights: list[NightScore] = []
        cursor = start
        while cursor < end or (inclusive_end and cursor <= end):
            nights.append(self.score_night(base, cursor, kp_by_date=kp_by_date))
            cursor += timedelta(days=1)
            if inclusive_end and cursor > end:
                break
        if not nights:
            nights.append(self.score_night(base, start, kp_by_date=kp_by_date))
        return nights

    def score_month(
        self,
        base: AlaskaAuroraBase | str,
        year: int,
        month: int,
        *,
        kp_by_date: Mapping[date, float] | None = None,
        allow_network: bool = False,
    ) -> list[NightScore]:
        """Score every aurora night in a calendar month (inclusive)."""
        hints = kp_by_date
        if hints is None and allow_network:
            result = self.load_noaa_hints()
            hints = {
                date.fromisoformat(key): float(value)
                for key, value in (result.payload or {}).get("kp_by_date", {}).items()
            }
        last_day = calendar.monthrange(year, month)[1]
        start = date(year, month, 1)
        end = date(year, month, last_day)
        return self.score_window(base, start, end, kp_by_date=hints, inclusive_end=True)

    @staticmethod
    def best_stay_window(
        nights: Sequence[NightScore],
        *,
        min_length: int = 3,
        max_length: int = 4,
    ) -> dict[str, Any] | None:
        """Pick the highest-mean 3–4 night sliding window from scored nights."""
        if not nights:
            return None
        ordered = sorted(nights, key=lambda n: n.on_date)
        best: dict[str, Any] | None = None
        for length in range(min_length, max_length + 1):
            if len(ordered) < length:
                continue
            for index in range(0, len(ordered) - length + 1):
                window = ordered[index : index + length]
                if (window[-1].on_date - window[0].on_date).days != length - 1:
                    continue
                mean = round(
                    sum(n.combined for n in window) / len(window),
                    1,
                )
                candidate = {
                    "arrive": window[0].on_date,
                    "leave": window[-1].on_date + timedelta(days=1),
                    "length": length,
                    "mean_aurora_score": mean,
                    "nights": [n.as_dict() for n in window],
                    "best_night": max(window, key=lambda n: n.combined).as_dict(),
                }
                if best is None or mean > float(best["mean_aurora_score"]):
                    best = candidate
        return best

    def compare_bases(
        self,
        start: date,
        end: date,
        *,
        bases: Sequence[AlaskaAuroraBase] | None = None,
        kp_by_date: Mapping[date, float] | None = None,
        allow_network: bool = False,
    ) -> list[dict[str, Any]]:
        hints = kp_by_date
        noaa_payload: dict[str, Any] = {}
        if hints is None and allow_network:
            result = self.load_noaa_hints()
            noaa_payload = dict(result.payload or {})
            hints = {
                date.fromisoformat(key): float(value)
                for key, value in (noaa_payload.get("kp_by_date") or {}).items()
            }
        rows: list[dict[str, Any]] = []
        for base in bases or ALASKA_AURORA_BASES:
            nights = self.score_window(base, start, end, kp_by_date=hints)
            mean = round(sum(n.combined for n in nights) / max(len(nights), 1), 1)
            rows.append(
                {
                    **base.as_dict(),
                    "mean_aurora_score": mean,
                    "nights": [n.as_dict() for n in nights],
                    "best_night": max(nights, key=lambda n: n.combined).as_dict(),
                }
            )
        rows.sort(key=lambda row: (-float(row["mean_aurora_score"]), row["typical_kp_visible"]))
        return rows

    def load_noaa_hints(self) -> StubResult:
        return self.noaa_provider.fetch_kp_hints()
