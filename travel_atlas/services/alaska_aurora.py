"""Stay-put Alaska aurora opener — Fairbanks only, no walking loop.

Home is always Los Angeles (LAX). Stay put in Fairbanks for aurora nights;
Chena Hot Springs is an optional darker-sky outing, not a second booking.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, Mapping
from urllib.parse import quote_plus

from .alaska_bases import (
    DEFAULT_BASE_KEY,
    HOME_AIRPORT,
    HOME_CITY,
    OPENER_VERSION,
    AlaskaAuroraBase,
    get_base,
)

CHENA_LAT = 65.0519
CHENA_LON = -146.0478

FLIGHT_TITLE = "LAX round-trip to aurora base"
HOTEL_TITLE = "Stay-put hotel (all nights)"
CAR_TITLE = "Airport rental car (stay-put transfer)"
BOOK_FIRST_KEYS = ("flight_lax", "hotel_stay", "car_airport")


def is_alaska_leg(destination: Mapping[str, Any] | object) -> bool:
    if hasattr(destination, "keys"):
        try:
            data = dict(destination)  # type: ignore[arg-type]
        except TypeError:
            data = destination  # type: ignore[assignment]
    else:
        data = destination  # type: ignore[assignment]
    label = (
        data.get("destination_label")  # type: ignore[union-attr]
        or data.get("label")  # type: ignore[union-attr]
        or ""
    ).strip()
    kind = (
        data.get("destination_kind")  # type: ignore[union-attr]
        or data.get("kind")  # type: ignore[union-attr]
        or ""
    )
    return label.casefold() == "alaska" and (
        not kind or str(kind).casefold() in {"us_state", "country"}
    )


def is_alaska_aurora_trip(trip: Mapping[str, Any]) -> bool:
    definition = _definition(trip)
    if definition.get("alaska_aurora") == OPENER_VERSION:
        return True
    return any(is_alaska_leg(dest) for dest in trip.get("destinations") or [])


def _definition(trip: Mapping[str, Any]) -> dict[str, Any]:
    return dict(trip.get("definition") or {})


def already_applied(trip: Mapping[str, Any]) -> bool:
    return bool(_definition(trip).get("alaska_aurora_seeded"))


def should_apply(trip: Mapping[str, Any]) -> bool:
    if already_applied(trip):
        return False
    if not any(is_alaska_leg(d) for d in trip.get("destinations") or []):
        return False
    return _definition(trip).get("alaska_aurora") == OPENER_VERSION


def _stop(name: str, *, city: str, lat: float, lon: float) -> dict[str, Any]:
    return {
        "pin_id": None,
        "name": name,
        "city": city,
        "country": "United States",
        "region": "Alaska",
        "latitude": lat,
        "longitude": lon,
        "distance_km_from_anchor": 0.0,
        "kind": "logistics",
    }


def build_stayput_itinerary(
    *,
    start_date: date | None,
    day_count: int = 4,
    base_key: str = DEFAULT_BASE_KEY,
) -> dict[str, Any]:
    base = get_base(base_key)
    city = base.label
    lat, lon = base.latitude, base.longitude
    count = max(3, min(int(day_count), 4))
    land = _stop(
        f"Land {base.airport} from {HOME_AIRPORT}, drive to {city}",
        city=city,
        lat=lat,
        lon=lon,
    )
    hotel = _stop(f"Check in — {city} (all nights)", city=city, lat=lat, lon=lon)
    town = _stop(f"Fairbanks day — rest, supplies, optional museums", city=city, lat=lat, lon=lon)
    chena = _stop(
        "Chena Hot Springs aurora outing (~1h drive, darker skies)",
        city="Chena Hot Springs",
        lat=CHENA_LAT,
        lon=CHENA_LON,
    )
    aurora = _stop("Aurora watch from Fairbanks (stay put)", city=city, lat=lat, lon=lon)
    depart = _stop(
        f"Drive back to {base.airport}, fly {HOME_AIRPORT}",
        city=city,
        lat=lat,
        lon=lon,
    )

    templates = [
        {
            "day": 1,
            "title": f"Arrive {city}",
            "anchor": hotel,
            "morning": [land],
            "afternoon": [hotel],
            "evening": [aurora],
            "optional": [],
            "source": f"alaska_aurora_{OPENER_VERSION}",
            "message": (
                f"Stay put in {city}. Fly {HOME_AIRPORT}→{base.airport}, "
                "check in once, aurora after dark."
            ),
        },
        {
            "day": 2,
            "title": "Fairbanks + aurora",
            "anchor": town,
            "morning": [town],
            "afternoon": [town],
            "evening": [aurora],
            "optional": [chena],
            "source": f"alaska_aurora_{OPENER_VERSION}",
            "message": (
                "Easy town day. Optional Chena Hot Springs run for darker skies — "
                "same hotel, one evening outing."
            ),
        },
        {
            "day": 3,
            "title": "Second aurora night",
            "anchor": hotel,
            "morning": [town],
            "afternoon": [town],
            "evening": [aurora],
            "optional": [chena],
            "source": f"alaska_aurora_{OPENER_VERSION}",
            "message": "More nights raise aurora odds. Do not add a second town.",
        },
        {
            "day": 4,
            "title": f"Home to {HOME_CITY}",
            "anchor": depart,
            "morning": [depart],
            "afternoon": [],
            "evening": [],
            "optional": [],
            "source": f"alaska_aurora_{OPENER_VERSION}",
            "message": f"Round-trip back to {HOME_AIRPORT}.",
        },
    ]
    if count == 3:
        templates = [templates[0], templates[1], templates[3]]
        templates[2] = {**templates[2], "day": 3}

    days_out: list[dict[str, Any]] = []
    for index, template in enumerate(templates[:count], start=1):
        day_date = None
        if start_date:
            day_date = (start_date + timedelta(days=index - 1)).isoformat()
        days_out.append({**template, "day": index, "date": day_date})
    return {
        "destination_kind": "us_state",
        "destination_label": "Alaska",
        "days": days_out,
        "message": (
            f"Stay-put {city} ({len(days_out)} days) — Fairbanks aurora nights, "
            "not clustered from saved pins."
        ),
    }


def _booking_specs(
    base: AlaskaAuroraBase,
    *,
    start: date | None,
    end: date | None,
    airport_override: str | None = None,
) -> list[dict[str, Any]]:
    airport = airport_override or base.airport
    depart = start.isoformat() if start else ""
    back = end.isoformat() if end else ""
    flight_q = quote_plus(f"Flights from {HOME_CITY} to {airport}")
    kayak = f"{HOME_AIRPORT}-{airport}"
    if depart:
        kayak += f"/{depart}"
        if back:
            kayak += f"/{back}"
    hotel_q = quote_plus(base.hotel_query)
    hotel_url = f"https://www.booking.com/searchresults.html?ss={hotel_q}"
    if depart and back:
        hotel_url += f"&checkin={depart}&checkout={back}"
    nights = 3
    if start and end:
        nights = max((end - start).days, 1)
    return [
        {
            "key": "flight_lax",
            "kind": "flight",
            "title": FLIGHT_TITLE,
            "itinerary_day": 1,
            "place_ref": f"{airport}",
            "booking_url": f"https://www.google.com/travel/flights?q={flight_q}",
            "notes": (
                f"Round-trip {HOME_AIRPORT} → {airport} from {HOME_CITY}. "
                f"Kayak: https://www.kayak.com/flights/{kayak}. "
                "Not Seattle. Not open-jaw."
            ),
        },
        {
            "key": "hotel_stay",
            "kind": "hotel",
            "title": HOTEL_TITLE,
            "itinerary_day": 1,
            "place_ref": base.label,
            "booking_url": hotel_url,
            "notes": (
                f"One property in {base.hotel_query} for {nights} night(s). "
                "Stay put — no second city."
            ),
        },
        {
            "key": "car_airport",
            "kind": "other",
            "title": CAR_TITLE,
            "itinerary_day": 1,
            "place_ref": airport,
            "booking_url": (
                "https://www.google.com/search?q="
                + quote_plus(f"car rental {airport} airport")
            ),
            "notes": (
                f"Pickup {airport}, drop {airport}. Drive to {base.label} "
                f"(~{base.drive_hours_from_airport:.0f}h) and stay."
            ),
        },
    ]


def apply_alaska_aurora(
    trip_service: Any,
    reservation_service: Any,
    *,
    trip_id: str,
    prep_service: Any | None = None,
) -> dict[str, Any]:
    """Idempotent: seed LAX round-trip + one hotel. Does not commit the trip."""
    trip = trip_service.get_trip(trip_id)
    if already_applied(trip):
        return {"applied": False, "reason": "already_applied", "trip": trip}

    definition = _definition(trip)
    base_key = str(definition.get("aurora_base") or DEFAULT_BASE_KEY)
    airport_override = definition.get("aurora_airport")
    base = get_base(base_key)
    departure = definition.get("departure_date")
    returning = definition.get("return_date")
    start = date.fromisoformat(str(departure)[:10]) if departure else None
    end = date.fromisoformat(str(returning)[:10]) if returning else None
    if start and not end:
        days = int((trip.get("destinations") or [{}])[0].get("day_count") or 4)
        end = start + timedelta(days=max(days - 1, 1))

    definition["alaska_aurora"] = OPENER_VERSION
    definition["alaska_aurora_seeded"] = True
    definition["aurora_base"] = base.key
    definition["aurora_airport"] = airport_override or base.airport
    definition["home_city"] = HOME_CITY
    definition["home_airport"] = HOME_AIRPORT
    if start and not definition.get("departure_date"):
        definition["departure_date"] = start.isoformat()
    if end and not definition.get("return_date"):
        definition["return_date"] = end.isoformat()

    with trip_service.repository.database.connect() as conn:
        conn.execute(
            """
            UPDATE trip_plan
            SET definition_json = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (json.dumps(definition), trip_id),
        )

    existing_titles = {
        (row.get("kind"), row.get("title"))
        for row in reservation_service.list_for_trip(trip_id)
    }
    created = 0
    for spec in _booking_specs(
        base, start=start, end=end, airport_override=airport_override
    ):
        key = (spec["kind"], spec["title"])
        if key in existing_titles:
            continue
        reservation_service.create(
            trip_id,
            kind=spec["kind"],
            title=spec["title"],
            status="book_now",
            place_ref=spec.get("place_ref"),
            booking_url=spec.get("booking_url"),
            notes=spec.get("notes"),
            itinerary_day=spec.get("itinerary_day"),
            starts_at=start.isoformat() if start else None,
            ends_at=end.isoformat() if end else None,
        )
        created += 1

    if prep_service is not None:
        prep_service.seed_checklist(trip_id)

    trip = trip_service.get_trip(trip_id)
    return {"applied": True, "reservations_created": created, "trip": trip}


def book_first_items(reservations: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_title = {row.get("title"): dict(row) for row in reservations}
    fallback = {
        "flight_lax": {
            "kind": "flight",
            "title": FLIGHT_TITLE,
            "booking_url": (
                "https://www.google.com/travel/flights?q="
                + quote_plus(f"Flights from {HOME_CITY} to FAI")
            ),
            "notes": f"Round-trip from {HOME_AIRPORT}.",
        },
        "hotel_stay": {
            "kind": "hotel",
            "title": HOTEL_TITLE,
            "booking_url": (
                "https://www.booking.com/searchresults.html?ss=Fairbanks%2C+Alaska"
            ),
            "notes": "One hotel in Fairbanks, all nights.",
        },
        "car_airport": {
            "kind": "other",
            "title": CAR_TITLE,
            "booking_url": (
                "https://www.google.com/search?q=" + quote_plus("car rental FAI airport")
            ),
            "notes": "Airport pickup / drop only.",
        },
    }
    out: list[dict[str, Any]] = []
    for key in BOOK_FIRST_KEYS:
        spec = fallback[key]
        row = by_title.get(spec["title"], {})
        out.append(
            {
                "key": key,
                "kind": row.get("kind") or spec["kind"],
                "title": spec["title"],
                "booking_url": row.get("booking_url") or spec["booking_url"],
                "status": row.get("status") or "book_now",
                "notes": row.get("notes") or spec.get("notes"),
            }
        )
    return out
