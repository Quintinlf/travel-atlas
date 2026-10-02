"""NOAA SWPC space-weather hints for aurora planning.

Network is optional. Callers inject text/JSON in tests. A miss returns empty
data rather than raising — this is a hint overlay, not a booking dependency.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from datetime import date, datetime
from typing import Any

from .base import StubResult

OUTLOOK_27_DAY_URL = "https://services.swpc.noaa.gov/text/27-day-outlook.txt"
KP_FORECAST_URL = (
    "https://services.swpc.noaa.gov/products/noaa-planetary-k-index-forecast.json"
)

_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

_OUTLOOK_LINE = re.compile(
    r"^(?P<year>\d{4})\s+(?P<mon>[A-Za-z]{3})\s+(?P<day>\d{1,2})"
    r"\s+\S+\s+\S+\s+(?P<kp>\d+(?:\.\d+)?)\s*$"
)


def parse_27_day_outlook(text: str) -> dict[date, float]:
    """Parse SWPC 27-day outlook text into calendar date → largest Kp."""
    out: dict[date, float] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(":") or line.startswith("#"):
            continue
        match = _OUTLOOK_LINE.match(line)
        if not match:
            continue
        month = _MONTHS.get(match.group("mon")[:3].casefold())
        if month is None:
            continue
        try:
            on = date(int(match.group("year")), month, int(match.group("day")))
            out[on] = float(match.group("kp"))
        except ValueError:
            continue
    return out


def parse_kp_forecast(payload: Any) -> dict[date, float]:
    """Collapse the 3-day Kp forecast JSON to the daily maximum Kp."""
    rows = payload
    if isinstance(payload, dict):
        rows = payload.get("data") or payload.get("table") or []
    if not isinstance(rows, list):
        return {}
    daily: dict[date, float] = {}
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        stamp, kp_raw = row[0], row[1]
        if isinstance(stamp, str) and stamp.casefold().startswith("time"):
            continue
        try:
            if isinstance(stamp, str):
                on = datetime.fromisoformat(stamp.replace("Z", "+00:00")).date()
            else:
                continue
            kp = float(kp_raw)
        except (TypeError, ValueError):
            continue
        daily[on] = max(kp, daily.get(on, 0.0))
    return daily


class NoaaSwpcProvider:
    key = "noaa-swpc-v1"

    def __init__(self, *, timeout_s: float = 8.0) -> None:
        self.timeout_s = timeout_s

    def fetch_kp_hints(self) -> StubResult:
        outlook: dict[date, float] = {}
        forecast: dict[date, float] = {}
        errors: list[str] = []
        try:
            outlook = parse_27_day_outlook(self._get_text(OUTLOOK_27_DAY_URL))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            errors.append(f"27-day: {exc}")
        try:
            forecast = parse_kp_forecast(self._get_json(KP_FORECAST_URL))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"3-day: {exc}")
        merged = dict(outlook)
        merged.update(forecast)
        status = "ok" if merged else "unavailable"
        return StubResult(
            provider=self.key,
            status=status,
            payload={
                "kp_by_date": {d.isoformat(): kp for d, kp in sorted(merged.items())},
                "outlook_days": len(outlook),
                "forecast_days": len(forecast),
                "errors": errors,
            },
        )

    def _get_text(self, url: str) -> str:
        with urllib.request.urlopen(url, timeout=self.timeout_s) as resp:
            return resp.read().decode("utf-8", errors="replace")

    def _get_json(self, url: str) -> Any:
        return json.loads(self._get_text(url))
