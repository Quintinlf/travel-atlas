"""Pure date-window matching helpers for recurring annual seasonal claims.

Season windows are MM-DD strings (season_start_month_day / season_end_month_day)
on knowledge_claim rows. They are NOT tied to a specific year, unlike
valid_from/valid_until (absolute calendar-date validity of a claim's accuracy).
A window may wrap the December/January year boundary (e.g. "12-15" to "01-15").
"""

from __future__ import annotations

import re
from datetime import date, timedelta

_MONTH_DAY_RE = re.compile(r"^\d{2}-\d{2}$")


def is_valid_month_day(value: str | None) -> bool:
    return value is None or bool(_MONTH_DAY_RE.match(value))


def month_day(value: date) -> str:
    return value.strftime("%m-%d")


def month_day_in_window(check: str, start: str, end: str) -> bool:
    if start <= end:
        return start <= check <= end
    return check >= start or check <= end  # window wraps the year boundary


def date_range_touches_window(
    range_start: date,
    range_end: date,
    start: str,
    end: str,
    *,
    max_span_days: int = 366,
) -> bool:
    span_days = (range_end - range_start).days
    if span_days < 0:
        return False
    span_days = min(span_days, max_span_days)
    return any(
        month_day_in_window(month_day(range_start + timedelta(days=offset)), start, end)
        for offset in range(span_days + 1)
    )
