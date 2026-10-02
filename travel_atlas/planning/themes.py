"""Weekly planning themes — default modes that give days a rhythm."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Sequence


@dataclass(frozen=True)
class DayTheme:
    key: str
    title: str
    focus: tuple[str, ...]
    categories: frozenset[str]
    energy: str  # low | medium | high
    open_time: bool = False  # Thursday-style spontaneity


# Default modes (overridable). Friday/Sunday stay flexible until history teaches more.
WEEKDAY_THEMES: dict[int, DayTheme] = {
    0: DayTheme(  # Monday
        key="body_nourishment",
        title="Body & Nourishment",
        focus=(
            "walking",
            "parks",
            "markets",
            "restaurants",
            "wellness",
            "local food traditions",
        ),
        categories=frozenset({"market_food", "nature_gardens", "general_travel"}),
        energy="medium",
    ),
    1: DayTheme(  # Tuesday
        key="strength_action",
        title="Strength & Action",
        focus=(
            "hiking",
            "adventure",
            "historic battlefields",
            "military museums",
            "climbing",
        ),
        categories=frozenset({"nature_gardens", "museum_history", "temple_spirituality"}),
        energy="high",
    ),
    2: DayTheme(  # Wednesday
        key="local_life",
        title="Local Life",
        focus=(
            "neighborhoods",
            "transit",
            "cafes",
            "bookstores",
            "everyday culture",
        ),
        categories=frozenset({"market_food", "transport", "shopping", "general_travel"}),
        energy="medium",
    ),
    3: DayTheme(  # Thursday
        key="discovery",
        title="Discovery",
        focus=("spontaneity", "nearby opportunities", "open time"),
        categories=frozenset(
            {"general_travel", "market_food", "nature_gardens", "museum_history"}
        ),
        energy="low",
        open_time=True,
    ),
    4: DayTheme(  # Friday — flexible
        key="flexible_friday",
        title="Flexible Friday",
        focus=("follow your energy", "mix of favorites and leftovers"),
        categories=frozenset(
            {
                "market_food",
                "museum_history",
                "nature_gardens",
                "temple_spirituality",
                "general_travel",
            }
        ),
        energy="medium",
    ),
    5: DayTheme(  # Saturday
        key="organized_saturday",
        title="Major Day",
        focus=("museums", "big attractions", "reservations", "long day"),
        categories=frozenset({"museum_history", "temple_spirituality", "shopping"}),
        energy="high",
    ),
    6: DayTheme(  # Sunday — flexible
        key="flexible_sunday",
        title="Open Sunday",
        focus=("rest", "cafes", "light neighborhood walks"),
        categories=frozenset({"market_food", "nature_gardens", "general_travel"}),
        energy="low",
    ),
}


def theme_for_date(on_date: date) -> DayTheme:
    return WEEKDAY_THEMES[on_date.weekday()]


def themes_for_trip(start: date | None, day_count: int) -> list[dict]:
    """Return theme metadata for each trip day."""
    out: list[dict] = []
    for index in range(max(day_count, 1)):
        if start:
            day_date = start + timedelta(days=index)
            theme = theme_for_date(day_date)
            date_iso = day_date.isoformat()
            weekday = day_date.strftime("%A")
        else:
            # Without dates, cycle Monday→… themes by day index.
            theme = WEEKDAY_THEMES[index % 7]
            date_iso = None
            weekday = None
        out.append(
            {
                "day": index + 1,
                "date": date_iso,
                "weekday": weekday,
                "theme_key": theme.key,
                "theme_title": theme.title,
                "focus": list(theme.focus),
                "categories": sorted(theme.categories),
                "energy": theme.energy,
                "open_time": theme.open_time,
            }
        )
    return out


def theme_fit(category: str, theme: DayTheme | None) -> float:
    if theme is None:
        return 0.5
    if category in theme.categories:
        return 1.0
    if theme.open_time:
        return 0.65
    return 0.25


def energy_fit(duration_hours: float, theme_energy: str, trip_pace: str) -> float:
    """Prefer durations that won't exhaust a medium-effort traveler."""
    # Medium energy is the default success posture.
    caps = {"low": 1.5, "medium": 2.0, "high": 3.0}
    pace_adj = {"slow": 0.75, "medium": 1.0, "fast": 1.25}
    target = caps.get(theme_energy, 2.0) * pace_adj.get(trip_pace, 1.0)
    delta = abs(duration_hours - target)
    return max(0.0, 1.0 - delta / 3.0)


def filter_by_theme(
    categories: Sequence[str], theme: DayTheme | None
) -> list[str]:
    if theme is None:
        return list(categories)
    preferred = [c for c in categories if c in theme.categories]
    return preferred or list(categories)
