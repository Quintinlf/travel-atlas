"""Pull late-September Fairbanks prices for 2 adults, queen rooms."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from travel_atlas.env_loader import load_travel_env
from travel_atlas.services.alaska_bases import FAIRBANKS_BASE
from travel_atlas.services.flight_search import search_roundtrip_fares
from travel_atlas.services.hotel_search import search_hotels_by_geocode

load_travel_env()

TRAVELERS = 2
BED_TYPES = ["queen"]

windows = [
    ("3-night", date(2026, 9, 26), date(2026, 9, 29)),
    ("4-night", date(2026, 9, 26), date(2026, 9, 30)),
]

out: dict = {
    "travelers": TRAVELERS,
    "room_preference": "2 queen beds, 1 room",
    "bed_types": BED_TYPES,
    "windows": {},
    "chena": {},
}

for label, arrive, leave in windows:
    flights = search_roundtrip_fares(
        origin="LAX",
        destination="FAI",
        depart=arrive,
        return_on=leave,
        currency="usd",
        limit=10,
        adults=TRAVELERS,
    )
    hotels = search_hotels_by_geocode(
        latitude=FAIRBANKS_BASE.latitude,
        longitude=FAIRBANKS_BASE.longitude,
        check_in=arrive.isoformat(),
        check_out=leave.isoformat(),
        radius_km=20.0,
        adults=TRAVELERS,
        bed_types=BED_TYPES,
        currency="USD",
        city=FAIRBANKS_BASE.hotel_query,
        include_google_lodging=False,
    )
    fares = flights.get("fares") or []
    hotel_rows = hotels.get("sorted_by_price") or hotels.get("hotels") or []
    out["windows"][label] = {
        "arrive": arrive.isoformat(),
        "leave": leave.isoformat(),
        "flights": {
            "ok": flights.get("ok"),
            "fare_source": flights.get("fare_source"),
            "message": flights.get("message"),
            "adults": flights.get("adults"),
            "links": flights.get("links"),
            "fares": fares[:10],
            "cheapest": fares[0] if fares else None,
        },
        "hotels": {
            "ok": hotels.get("ok"),
            "message": hotels.get("message"),
            "query": hotels.get("query"),
            "area_links": hotels.get("area_links"),
            "count": len(hotel_rows),
            "hotels": [
                {
                    "hotel": r.get("hotel_name"),
                    "room": r.get("room_name"),
                    "total": r.get("total_price"),
                    "nightly": r.get("nightly_rate"),
                    "currency": r.get("currency"),
                    "rating": r.get("rating"),
                    "bed_verify": r.get("bed_verify"),
                    "photo_url": r.get("photo_url"),
                    "booking_url": r.get("booking_url"),
                    "google_hotels_url": r.get("google_hotels_url"),
                    "lat": r.get("lat"),
                    "lon": r.get("lon"),
                }
                for r in hotel_rows
            ],
            "cheapest": (
                {
                    "hotel": hotel_rows[0].get("hotel_name"),
                    "room": hotel_rows[0].get("room_name"),
                    "total": hotel_rows[0].get("total_price"),
                    "nightly": hotel_rows[0].get("nightly_rate"),
                }
                if hotel_rows
                else None
            ),
        },
    }

arrive, leave = date(2026, 9, 26), date(2026, 9, 30)
chena = search_hotels_by_geocode(
    latitude=65.0519,
    longitude=-146.0478,
    check_in=arrive.isoformat(),
    check_out=leave.isoformat(),
    radius_km=15.0,
    adults=TRAVELERS,
    bed_types=BED_TYPES,
    currency="USD",
    city="Chena Hot Springs, Alaska",
    include_google_lodging=False,
)
chena_rows = chena.get("sorted_by_price") or chena.get("hotels") or []
out["chena"] = {
    "ok": chena.get("ok"),
    "message": chena.get("message"),
    "count": len(chena_rows),
    "hotels": [
        {
            "hotel": r.get("hotel_name"),
            "room": r.get("room_name"),
            "total": r.get("total_price"),
        }
        for r in chena_rows[:8]
    ],
}

if not any((out["windows"][w]["flights"].get("fares") or []) for w in out["windows"]):
    out["flight_benchmark"] = {
        "per_adult_low_usd": 379,
        "per_adult_mid_usd": 415,
        "per_adult_high_usd": 600,
        "party_of_2_mid_usd": 830,
        "note": "Aviasales cache empty for LAX-FAI; verify on Kayak/Google",
    }

out_path = _ROOT / "fairbanks_price_snapshot.json"
out_path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
print("wrote", out_path)
print(json.dumps(out, indent=2, default=str)[:4000])
