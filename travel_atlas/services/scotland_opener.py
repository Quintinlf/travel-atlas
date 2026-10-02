"""Dundee 2-day car loop + Glasgow as Days 1–3 of the West Europe trip."""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, Mapping
from urllib.parse import quote_plus

from src_phase1.models import SavedLocation

OPENER_VERSION = "dundee_v1"
SCOTLAND_DAY_COUNT = 3
DEFAULT_FLIGHT_ORIGIN = "Seattle"

EDI_LAT, EDI_LON = 55.9508, -3.3615
DUNDEE_LAT, DUNDEE_LON = 56.4620, -2.9707
GLASGOW_LAT, GLASGOW_LON = 55.8642, -4.2518

DAY1_CAPTION = (
    "Day 1 of this trip: land EDI → Edinburgh cluster → car → "
    "Eagle Rock → St Andrews → Dundee."
)

# Unique titles — apply is idempotent by matching these.
BOOKING_SPECS: tuple[dict[str, Any], ...] = (
    {
        "key": "flight_edi",
        "kind": "flight",
        "title": "Inbound flight to EDI (open-jaw)",
        "itinerary_day": 1,
        "place_ref": "Edinburgh",
        "booking_url": (
            "https://www.google.com/travel/flights?q="
            + quote_plus(f"Flights from {DEFAULT_FLIGHT_ORIGIN} to EDI")
        ),
        "notes": (
            f"One-way / open-jaw into Edinburgh. Origin default {DEFAULT_FLIGHT_ORIGIN}. "
            "Do not book a return to the same city."
        ),
    },
    {
        "key": "car_edi",
        "kind": "other",
        "title": "EDI rental car (Day 1 pickup / Day 2 drop)",
        "itinerary_day": 1,
        "place_ref": "Edinburgh Airport",
        "booking_url": (
            "https://www.google.com/search?q="
            + quote_plus("car rental Edinburgh Airport EDI")
        ),
        "notes": "Pickup Day 1 midday at EDI. Drop Day 2 afternoon at EDI.",
    },
    {
        "key": "hotel_dundee",
        "kind": "hotel",
        "title": "Dundee hotel (1 night)",
        "itinerary_day": 1,
        "place_ref": "Dundee",
        "booking_url": "https://www.booking.com/searchresults.html?ss=Dundee%2C+Scotland",
        "notes": "Night 1 only — after St Andrews. Bidet if required.",
    },
    {
        "key": "hotel_glasgow",
        "kind": "hotel",
        "title": "Glasgow hotel (2 nights)",
        "itinerary_day": 2,
        "place_ref": "Glasgow",
        "booking_url": "https://www.booking.com/searchresults.html?ss=Glasgow%2C+Scotland",
        "notes": "Arrive evening Day 2; full Day 3 in the city. No car.",
    },
    {
        "key": "train_glasgow",
        "kind": "train",
        "title": "EDI Waverley → Glasgow (evening Day 2)",
        "itinerary_day": 2,
        "place_ref": "Glasgow",
        "booking_url": (
            "https://www.thetrainline.com/book/results?origin=Edinburgh&destination=Glasgow"
        ),
        "notes": "After EDI car drop. ~50 min ScotRail to Glasgow Central / Queen Street.",
    },
)

BOOK_FIRST_KEYS = ("flight_edi", "car_edi", "hotel_dundee", "hotel_glasgow")


def is_scotland_leg(destination: Mapping[str, Any] | object) -> bool:
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
    ).replace(" (UK)", "").strip()
    return label.casefold() == "scotland"


def _logistics_stop(
    name: str,
    *,
    city: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> dict[str, Any]:
    return {
        "pin_id": None,
        "name": name,
        "city": city,
        "country": "United Kingdom",
        "region": "Scotland",
        "latitude": latitude,
        "longitude": longitude,
        "distance_km_from_anchor": 0.0,
        "kind": "logistics",
    }


def _stop_from_pin(pin: SavedLocation) -> dict[str, Any]:
    return {
        "pin_id": pin.id,
        "name": pin.name,
        "city": pin.city,
        "country": pin.country,
        "region": pin.region,
        "latitude": pin.latitude,
        "longitude": pin.longitude,
        "distance_km_from_anchor": 0.0,
        "kind": "pin",
    }


def _pin_lookup(pins: list[SavedLocation]) -> dict[str, SavedLocation]:
    index: dict[str, SavedLocation] = {}
    for pin in pins:
        key = (pin.name or "").strip().casefold()
        if key and key not in index:
            index[key] = pin
    return index


def _named(
    index: dict[str, SavedLocation],
    name: str,
    *,
    city: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> dict[str, Any]:
    pin = index.get(name.casefold())
    if pin is not None:
        return _stop_from_pin(pin)
    return _logistics_stop(name, city=city, latitude=latitude, longitude=longitude)


def opener_day_templates(index: dict[str, SavedLocation]) -> list[dict[str, Any]]:
    """Three Scotland days: EDI landing, Perth/car-drop, Glasgow."""
    museum = _named(index, "National Museum of Scotland", city="Edinburgh")
    hume = _named(index, "David Hume Statue", city="Edinburgh")
    calton = _named(index, "Calton Hill", city="Edinburgh")
    seat = _named(index, "Arthur's Seat", city="Edinburgh")
    eagle = _named(index, "Eagle Rock", city="Dalgety Bay")
    uni = _named(index, "University of St Andrews", city="Saint Andrews")
    cathedral = _named(index, "St Andrews Cathedral", city="Saint Andrews")
    molly = _named(index, "Molly Malones", city="Saint Andrews")
    scone = _named(index, "Scone Palace", city="Perth")
    perth_museum = _named(index, "Perth Museum", city="Perth")
    tesco = _named(index, "Tesco Extra", city="Almondbank")
    mcdonalds = _named(index, "McDonald's", city="Almondbank")
    morrisons = _named(index, "Morrisons", city="Perth")
    glasgow = _named(
        index, "Glasgow", city="Glasgow", latitude=GLASGOW_LAT, longitude=GLASGOW_LON
    )

    land = _logistics_stop(
        "Land EDI (tram into centre)", city="Edinburgh", latitude=EDI_LAT, longitude=EDI_LON
    )
    car_pickup = _logistics_stop(
        "Pick up rental car at EDI", city="Edinburgh", latitude=EDI_LAT, longitude=EDI_LON
    )
    forth = _logistics_stop("Cross the Forth Bridge", city="Dalgety Bay")
    dundee = _logistics_stop(
        "Check in — Dundee overnight",
        city="Dundee",
        latitude=DUNDEE_LAT,
        longitude=DUNDEE_LON,
    )
    car_drop = _logistics_stop(
        "Drop rental car at EDI", city="Edinburgh", latitude=EDI_LAT, longitude=EDI_LON
    )
    train = _logistics_stop(
        "ScotRail EDI Waverley → Glasgow (~50 min)",
        city="Glasgow",
        latitude=GLASGOW_LAT,
        longitude=GLASGOW_LON,
    )
    glasgow_in = _logistics_stop(
        "Check in — Glasgow (2 nights)",
        city="Glasgow",
        latitude=GLASGOW_LAT,
        longitude=GLASGOW_LON,
    )

    return [
        {
            "day": 1,
            "title": "Edinburgh + Fife + overnight Dundee",
            "anchor": museum,
            "morning": [land, museum, hume, calton, seat],
            "afternoon": [car_pickup, forth, eagle, uni, cathedral, molly],
            "evening": [dundee],
            "optional": [],
            "source": "scotland_opener_dundee_v1",
            "message": DAY1_CAPTION,
        },
        {
            "day": 2,
            "title": "Perth loop, EDI car drop, train to Glasgow",
            "anchor": scone,
            "morning": [scone, perth_museum, tesco, mcdonalds, morrisons],
            "afternoon": [car_drop],
            "evening": [train, glasgow_in],
            "optional": [],
            "source": "scotland_opener_dundee_v1",
            "message": (
                "Day 2: Perth / Almondbank in the morning, EDI car drop, "
                "then the evening train to Glasgow."
            ),
        },
        {
            "day": 3,
            "title": "Glasgow (no car)",
            "anchor": glasgow,
            "morning": [glasgow],
            "afternoon": [],
            "evening": [],
            "optional": [],
            "source": "scotland_opener_dundee_v1",
            "message": "Day 3: central Glasgow. No car.",
        },
    ]


def build_opener_itinerary(
    pins: list[SavedLocation],
    *,
    start_date: date | None,
    day_count: int = SCOTLAND_DAY_COUNT,
) -> dict[str, Any]:
    templates = opener_day_templates(_pin_lookup(pins))[: max(1, int(day_count))]
    days_out: list[dict[str, Any]] = []
    for template in templates:
        day_index = int(template["day"])
        day_date = None
        if start_date:
            day_date = (start_date + timedelta(days=day_index - 1)).isoformat()
        days_out.append({**template, "date": day_date})
    return {
        "destination_kind": "uk_nation",
        "destination_label": "Scotland",
        "days": days_out,
        "message": (
            f"Dundee car loop + Glasgow ({len(days_out)} days) — "
            "not clustered by pin count."
        ),
    }


def _definition(trip: Mapping[str, Any]) -> dict[str, Any]:
    raw = trip.get("definition") or {}
    return dict(raw)


def already_applied(trip: Mapping[str, Any]) -> bool:
    return _definition(trip).get("scotland_opener") == OPENER_VERSION


def should_apply(trip: Mapping[str, Any]) -> bool:
    if already_applied(trip):
        return False
    dests = trip.get("destinations") or []
    if not any(is_scotland_leg(d) for d in dests):
        return False
    name = (trip.get("name") or "").casefold()
    if "west europe" in name:
        return True
    labels = {
        (
            d.get("destination_label") or d.get("label") or ""
        ).replace(" (UK)", "").strip().casefold()
        for d in dests
    }
    west = {"scotland", "england", "ireland", "france", "spain", "portugal", "wales"}
    return len(labels & west) >= 2


def _put_scotland_first(conn: Any, trip_id: str, departure: str | None) -> None:
    rows = conn.execute(
        """
        SELECT destination_kind, destination_label, day_count, start_date
        FROM trip_plan_destination
        WHERE trip_id = ?
        ORDER BY order_index
        """,
        (trip_id,),
    ).fetchall()
    dests = [dict(row) for row in rows]
    scotland = next((d for d in dests if is_scotland_leg(d)), None)
    others = [d for d in dests if not is_scotland_leg(d)]
    if scotland is None:
        scotland = {
            "destination_kind": "uk_nation",
            "destination_label": "Scotland",
            "day_count": SCOTLAND_DAY_COUNT,
            "start_date": departure,
        }
    else:
        scotland = dict(scotland)
        scotland["day_count"] = SCOTLAND_DAY_COUNT
        scotland["start_date"] = departure or scotland.get("start_date")
    ordered = [scotland, *others]
    if ordered and departure:
        ordered[0]["start_date"] = departure
        for extra in ordered[1:]:
            extra["start_date"] = None
    conn.execute("DELETE FROM trip_plan_destination WHERE trip_id = ?", (trip_id,))
    for index, dest in enumerate(ordered):
        conn.execute(
            """
            INSERT INTO trip_plan_destination(
                trip_id, destination_kind, destination_label,
                order_index, day_count, start_date
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                trip_id,
                dest.get("destination_kind") or dest.get("kind") or "uk_nation",
                dest.get("destination_label") or dest.get("label") or "Scotland",
                index,
                int(dest.get("day_count") or SCOTLAND_DAY_COUNT),
                dest.get("start_date"),
            ),
        )


def apply_scotland_opener(
    trip_service: Any,
    reservation_service: Any,
    *,
    trip_id: str,
    origin: str = DEFAULT_FLIGHT_ORIGIN,
    prep_service: Any | None = None,
) -> dict[str, Any]:
    """Idempotent: Scotland first, 3 days, book_now seeds. Does not commit the trip."""
    trip = trip_service.get_trip(trip_id)
    if already_applied(trip):
        return {"applied": False, "reason": "already_applied", "trip": trip}

    definition = _definition(trip)
    departure = definition.get("departure_date")
    if not departure:
        first = (trip.get("destinations") or [{}])[0]
        departure = first.get("start_date") or first.get("resolved_start_date")

    with trip_service.repository.database.connect() as conn:
        _put_scotland_first(conn, trip_id, departure)
        definition["scotland_opener"] = OPENER_VERSION
        if departure and not definition.get("departure_date"):
            definition["departure_date"] = departure
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
    for spec in BOOKING_SPECS:
        key = (spec["kind"], spec["title"])
        if key in existing_titles:
            continue
        booking_url = spec["booking_url"]
        if spec["key"] == "flight_edi" and origin != DEFAULT_FLIGHT_ORIGIN:
            booking_url = (
                "https://www.google.com/travel/flights?q="
                + quote_plus(f"Flights from {origin} to EDI")
            )
        reservation_service.create(
            trip_id,
            kind=spec["kind"],
            title=spec["title"],
            status="book_now",
            place_ref=spec.get("place_ref"),
            booking_url=booking_url,
            notes=spec.get("notes"),
            itinerary_day=spec.get("itinerary_day"),
        )
        created += 1

    if prep_service is not None:
        prep_service.seed_checklist(trip_id)

    trip = trip_service.get_trip(trip_id)
    return {"applied": True, "reservations_created": created, "trip": trip}


def book_first_items(reservations: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Flight → car → Dundee hotel → Glasgow hotel, for the Command Center strip."""
    by_title = {row.get("title"): dict(row) for row in reservations}
    out: list[dict[str, Any]] = []
    for spec in BOOKING_SPECS:
        if spec["key"] not in BOOK_FIRST_KEYS:
            continue
        row = by_title.get(spec["title"], {})
        out.append(
            {
                "key": spec["key"],
                "kind": spec["kind"],
                "title": spec["title"],
                "booking_url": row.get("booking_url") or spec["booking_url"],
                "status": row.get("status") or "book_now",
                "notes": spec.get("notes"),
            }
        )
    return out
