"""Lodging preference questions + hotel-vs-apartment + location suggestions."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Any, Sequence

from src_phase1.geo_grouping import destination_matches


@dataclass(frozen=True)
class LodgingAdvice:
    recommendation: str  # "hotel" | "apartment" | "either"
    summary: str
    reasons: list[str]


@dataclass(frozen=True)
class LocationPick:
    city: str
    pin_count: int
    sample_pins: list[str]
    rationale: str


def nights_between(check_in: date, check_out: date) -> int:
    return max(0, (check_out - check_in).days)


def advise_lodging_type(
    *,
    nights: int,
    needs_kitchen: bool,
    traveling_with_others: bool,
    want_daily_cleaning: bool,
    early_checkout_flexibility: bool,
    prefer_local_neighborhood: bool,
    requires_bidet: bool = False,
) -> LodgingAdvice:
    """Heuristic hotel vs apartment guidance (not a booking engine)."""
    hotel_score = 0
    apt_score = 0
    reasons: list[str] = []

    if nights <= 2:
        hotel_score += 3
        reasons.append("Short stay (1–2 nights) usually favors a hotel — less setup, easier late arrival.")
    elif nights <= 4:
        hotel_score += 1
        apt_score += 1
        reasons.append("Mid-length stay (3–4 nights): either works; pick by neighborhood vs amenities.")
    else:
        apt_score += 3
        reasons.append("Longer stay (5+ nights): apartments often win on space, laundry, and kitchen.")

    if needs_kitchen:
        apt_score += 3
        reasons.append("Kitchen / self-catering points strongly to an apartment or aparthotel.")
    if traveling_with_others:
        apt_score += 2
        reasons.append("Multiple people usually get better space/value in an apartment.")
    if want_daily_cleaning:
        hotel_score += 3
        reasons.append("Daily cleaning / front desk is a hotel strength.")
    if early_checkout_flexibility:
        hotel_score += 1
        reasons.append("Flexible / one-night changes are easier with hotels.")
    if prefer_local_neighborhood:
        apt_score += 1
        reasons.append("Residential neighborhoods lean apartment; tourist cores lean hotel.")
    if requires_bidet:
        reasons.append(
            "Bidet is required — filter listings for a bidet / washlet / shower toilet. "
            "Add 'bidet' to Booking/Google hotel search; skip places that only have a toilet."
        )

    if hotel_score >= apt_score + 2:
        rec = "hotel"
        summary = "Lean hotel for this stay."
    elif apt_score >= hotel_score + 2:
        rec = "apartment"
        summary = "Lean apartment / Airbnb-style stay."
    else:
        rec = "either"
        summary = "Hotel or apartment both fit — decide by exact pin cluster and price."

    return LodgingAdvice(recommendation=rec, summary=summary, reasons=reasons)


def suggest_lodging_locations(
    pins: Sequence[Any],
    trip_destinations: Sequence[dict[str, Any]],
    *,
    limit: int = 5,
) -> list[LocationPick]:
    """Rank cities by how many trip-matching saved pins sit there."""
    matched: list[Any] = []
    for dest in trip_destinations:
        kind = dest.get("destination_kind") or dest.get("kind") or "country"
        label = (dest.get("destination_label") or dest.get("label") or "").replace(
            " (UK)", ""
        )
        if not label:
            continue
        for pin in pins:
            if destination_matches(pin, kind, label):
                matched.append(pin)

    by_city: Counter[str] = Counter()
    samples: dict[str, list[str]] = {}
    for pin in matched:
        city = (getattr(pin, "city", None) or "").strip()
        if not city:
            # Fall back to region/country for coarse legs (e.g. Scotland)
            city = (
                getattr(pin, "region", None)
                or getattr(pin, "country", None)
                or "Unknown"
            ).strip()
        by_city[city] += 1
        samples.setdefault(city, [])
        if len(samples[city]) < 3:
            samples[city].append(getattr(pin, "name", "pin"))

    picks: list[LocationPick] = []
    for city, count in by_city.most_common(limit):
        picks.append(
            LocationPick(
                city=city,
                pin_count=count,
                sample_pins=samples.get(city, []),
                rationale=(
                    f"{count} saved pin(s) you want to visit cluster around {city} — "
                    "sleeping here cuts transit time."
                ),
            )
        )
    return picks


def property_name_from_url(url: str) -> str | None:
    """Best-effort property hint from a pasted booking URL (not site APIs)."""
    if not url or not url.startswith("http"):
        return None
    # Common patterns: /hotel/gb/name.html, /rooms/123-name, path slug
    try:
        from urllib.parse import unquote, urlparse

        path = unquote(urlparse(url).path or "")
    except Exception:
        return None
    parts = [p for p in path.split("/") if p and p not in {"hotel", "hotels", "rooms", "s"}]
    if not parts:
        return None
    slug = parts[-1]
    if slug.endswith(".html"):
        slug = slug[:-5]
    # Drop pure ids
    if slug.isdigit() or len(slug) < 3:
        if len(parts) >= 2:
            slug = parts[-2]
        else:
            return None
    name = slug.replace("-", " ").replace("_", " ").strip()
    # Ignore generic search pages
    lowered = name.lower()
    if any(x in lowered for x in ("searchresults", "hotel-search", "homes", "travel hotels")):
        return None
    if len(name) < 3:
        return None
    return name.title()
