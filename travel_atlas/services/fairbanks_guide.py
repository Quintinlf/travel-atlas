"""Curated Fairbanks activities, food, and sights for trip briefings."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from urllib.parse import quote_plus

CHENA_MAPS = "https://www.google.com/maps/search/Chena+Hot+Springs+Resort"
MARKET_MAPS = "https://www.google.com/maps/search/Tanana+Valley+Farmers+Market+Fairbanks"
MORRIS_THOMPSON_MAPS = "https://www.google.com/maps/search/Morris+Thompson+Cultural+Center+Fairbanks"
MUSEUM_NORTH_MAPS = "https://www.google.com/maps/search/University+of+Alaska+Museum+of+the+North"
CHENA_TOUR = "https://www.chenahotsprings.com/"
BOWL_CO_MAPS = "https://www.google.com/maps/search/Great+Alaskan+Bowl+Company+Fairbanks"


def _maps(query: str) -> str:
    return f"https://www.google.com/maps/search/{quote_plus(query)}"


def market_days_during_stay(arrive: date, leave: date) -> list[date]:
    """Wednesdays and Saturdays between check-in and last hotel night."""
    days: list[date] = []
    cursor = arrive
    last_night = leave - timedelta(days=1)
    while cursor <= last_night:
        if cursor.weekday() in (2, 5):  # Wed=2, Sat=5
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def fairbanks_guide(*, arrive: date, leave: date) -> dict[str, Any]:
    """Structured guide content for HTML briefing and Streamlit."""
    market_days = market_days_during_stay(arrive, leave)
    night_count = (leave - arrive).days
    if market_days:
        labels = ", ".join(d.strftime("%A %b %d") for d in market_days)
        market_note = f"During your stay: market open on {labels}."
    else:
        market_note = "No Wednesday/Saturday market falls on your hotel nights."

    return {
        "night_count": night_count,
        "market_days": [d.isoformat() for d in market_days],
        "market_note": market_note,
        "hot_springs": {
            "name": "Chena Hot Springs Resort",
            "tag": "Optional add-on — Mom's pick (hot springs)",
            "optional": True,
            "drive": "~60 miles / ~1 hour northeast on Chena Hot Springs Road",
            "summary": (
                "Geothermal outdoor rock lake and indoor pools. Day passes available; "
                "Aurora Ice Museum on site; resort restaurant for lunch or dinner. "
                "Best as a full daytime trip so you are not driving back in the dark."
            ),
            "est_cost_party_usd": (60, 90),
            "shuttle_cost_party_usd": (160, 300),
            "why_add": [
                "Mom's priority — iconic Alaska soak in an outdoor rock lake.",
                "Ice Museum is unique and works even if aurora clouds roll in that night.",
                "Fall colors on the drive (or shuttle ride) are excellent in late September.",
            ],
            "skip_if": [
                "You would rather spend the day at Museum of the North and Pioneer Park.",
                "Without a car, shuttle cost may not feel worth it — the rest of the trip still works.",
                "Chena is not required for aurora; it is a daytime activity only.",
            ],
            "without_car_note": (
                "No rental car? Book a Chena day shuttle or guided tour from Fairbanks "
                "(~$160–300 for 2 round-trip) instead of self-driving."
            ),
            "tips": [
                "Book a day pass at the lodge — valid all day; bring a swimsuit and warm layers.",
                "Add the Ice Museum tour (indoor, year-round).",
                "Guided tours from Fairbanks are available if you prefer not to drive.",
                "Fall colors on the drive are excellent in late September.",
            ],
            "url": CHENA_TOUR,
            "maps_url": CHENA_MAPS,
        },
        "optional_add_ons": {
            "car_rental": {
                "title": "Rental car",
                "optional": True,
                "est_cost_party_usd": (240, 420),
                "cost_note": "Includes ~4 days rental ($200–350) + gas for town and Chena ($40–70).",
                "why_add": [
                    "Cheapest way to reach Chena Hot Springs on your own schedule.",
                    "DIY aurora from Chena Hot Springs Road pullouts — darker skies than downtown.",
                    "Easy hops to the farmers market, Museum of the North, and dinner without booking rides.",
                    "Airport ↔ hotel on your timeline (FAI is ~15 min from town).",
                ],
                "skip_if": [
                    "You prefer not to drive unfamiliar roads, especially at night.",
                    "You will use guided aurora tours (hotel pickup) instead of chasing lights yourself.",
                    "Taxi/rideshare for airport and in-town meals is fine — saves ~$240–420.",
                ],
            },
            "chena_day": {
                "title": "Chena Hot Springs day",
                "optional": True,
                "cross_ref": "hot_springs",
            },
        },
        "markets": {
            "name": "Tanana Valley Farmers Market",
            "address": "2600 College Road, Fairbanks",
            "hours": "Wednesdays 11 am–4 pm, Saturdays 9 am–4 pm (May–September)",
            "note": market_note,
            "est_cost_party_usd": (30, 80),
            "buy": [
                "Greenhouse tomatoes and cucumbers grown under the midnight sun",
                "Root vegetables, herbs, and late-season berries",
                "Birch syrup and wildflower honey",
                "Wild berry jams, preserves, and Alaska-raised meats",
                "Silver Hand–certified Alaska Native crafts (authentic artwork)",
            ],
            "la_note": (
                "Interior Alaska produce and pantry items you will not find at LA farmers markets — "
                "especially birch products, salmonberry jams, and sub-arctic greenhouse veg."
            ),
            "maps_url": MARKET_MAPS,
        },
        "native_foods": {
            "intro": (
                "Fairbanks has few restaurants devoted solely to traditional Alaska Native cuisine. "
                "You will still find indigenous ingredients on menus and at the market — and cultural "
                "context at the Morris Thompson Center."
            ),
            "try": [
                ("Reindeer sausage", "The Crepery", _maps("The Crepery Fairbanks")),
                ("Smoked / grilled salmon", "Pike's Landing", _maps("Pike's Landing Fairbanks")),
                ("Birch syrup", "Great Alaskan Bowl Company", BOWL_CO_MAPS),
                ("Wild berry jams", "Farmers market", MARKET_MAPS),
                ("Salmonberries / cloudberries", "Farmers market (seasonal)", MARKET_MAPS),
            ],
            "culture_url": MORRIS_THOMPSON_MAPS,
        },
        "things_to_see": [
            {
                "name": "Morris Thompson Cultural & Visitors Center",
                "why": "Free downtown museum — Alaska Native cultures, Athabascan heritage, local history.",
                "maps_url": MORRIS_THOMPSON_MAPS,
                "est_cost_party_usd": (0, 0),
            },
            {
                "name": "University of Alaska Museum of the North",
                "why": "Gold of Alaska, wildlife, and art — one of the state's best museums.",
                "maps_url": MUSEUM_NORTH_MAPS,
                "est_cost_party_usd": (28, 36),
            },
            {
                "name": "Pioneer Park",
                "why": "Historic village, river walk, local shops — easy half-day in town.",
                "maps_url": _maps("Pioneer Park Fairbanks"),
                "est_cost_party_usd": (0, 20),
            },
            {
                "name": "Georgeson Botanical Garden (UAF)",
                "why": "Sub-arctic gardening under the midnight sun — late-season flowers.",
                "maps_url": _maps("Georgeson Botanical Garden Fairbanks"),
                "est_cost_party_usd": (10, 16),
            },
            {
                "name": "Creamer's Field Migratory Waterfowl Refuge",
                "why": "Short nature walks close to town; fall migration.",
                "maps_url": _maps("Creamer's Field Fairbanks"),
                "est_cost_party_usd": (0, 0),
            },
        ],
        "places_to_eat": [
            {
                "name": "The Pumphouse Restaurant & Saloon",
                "style": "Alaskan seafood & steak",
                "note": "Gold Rush atmosphere; salmon, halibut, birch-glazed dishes.",
                "maps_url": _maps("The Pumphouse Restaurant Fairbanks"),
                "est_cost_party_usd": (80, 140),
            },
            {
                "name": "Pike's Landing",
                "style": "Waterfront Alaskan",
                "note": "King salmon, river views — popular with visitors.",
                "maps_url": _maps("Pike's Landing Fairbanks"),
                "est_cost_party_usd": (70, 120),
            },
            {
                "name": "Lavelle's Bistro",
                "style": "Fine dining",
                "note": "Local ingredients; birch syrup glazed salmon.",
                "maps_url": _maps("Lavelle's Bistro Fairbanks"),
                "est_cost_party_usd": (90, 150),
            },
            {
                "name": "The Crepery",
                "style": "Casual / breakfast",
                "note": "Reindeer sausage — easy intro to a local staple.",
                "maps_url": _maps("The Crepery Fairbanks"),
                "est_cost_party_usd": (25, 45),
            },
            {
                "name": "Alaska Coffee Roasting Co.",
                "style": "Coffee & light bites",
                "note": "Reindeer sausage breakfast items.",
                "maps_url": _maps("Alaska Coffee Roasting Co Fairbanks"),
                "est_cost_party_usd": (20, 40),
            },
            {
                "name": "Chena Hot Springs Resort restaurant",
                "style": "Resort dining",
                "note": "Pair with a soak day — book ahead in peak season.",
                "maps_url": CHENA_MAPS,
                "est_cost_party_usd": (50, 90),
            },
        ],
        "things_to_do": [
            {
                "label": "Northern lights viewing from Fairbanks",
                "maps_url": _maps("Fairbanks aurora viewing"),
                "est_cost_party_usd": (0, 80),
            },
            {
                "label": "Chena Hot Springs day trip — soak, ice museum",
                "maps_url": CHENA_MAPS,
                "est_cost_party_usd": (60, 90),
            },
            {
                "label": "Tanana Valley Farmers Market",
                "maps_url": MARKET_MAPS,
                "est_cost_party_usd": (30, 80),
            },
            {
                "label": "Morris Thompson Center + downtown riverfront",
                "maps_url": MORRIS_THOMPSON_MAPS,
                "est_cost_party_usd": (0, 0),
            },
            {
                "label": "Museum of the North or Pioneer Park",
                "maps_url": MUSEUM_NORTH_MAPS,
                "est_cost_party_usd": (0, 36),
            },
            {
                "label": "Great Alaskan Bowl Company — pantry gifts",
                "maps_url": BOWL_CO_MAPS,
                "est_cost_party_usd": (50, 100),
            },
            {
                "label": "Optional guided aurora tour",
                "maps_url": _maps("Fairbanks aurora tour"),
                "est_cost_party_usd": (150, 300),
            },
        ],
        "suggested_days": _suggested_days(arrive, leave),
    }


def _suggested_days(arrive: date, leave: date) -> list[dict[str, str]]:
    nights = (leave - arrive).days
    if nights < 1:
        return []

    days: list[dict[str, str]] = []
    d = arrive
    day_num = 1

    days.append(
        {
            "label": f"Day {day_num} — {d.strftime('%a %b %d')}",
            "plan": (
                "Arrive FAI, taxi or hotel shuttle to hotel, check in. "
                + (
                    "If you land before ~2 pm, stop at the farmers market (Saturday). "
                    if d.weekday() == 5
                    else ""
                )
                + "Easy evening — supplies, dinner in town. Aurora watch after dark "
                "(guided tour pickup or step outside if skies are clear)."
            ),
        }
    )
    d += timedelta(days=1)
    day_num += 1

    if d < leave:
        market = "Farmers market morning (if Saturday/Wednesday). " if d.weekday() in (2, 5) else ""
        days.append(
            {
                "label": f"Day {day_num} — {d.strftime('%a %b %d')}",
                "plan": (
                    f"{market}Downtown — Morris Thompson Center, river walk, "
                    "Great Alaskan Bowl Co. for pantry gifts. Aurora tonight."
                ),
            }
        )
        d += timedelta(days=1)
        day_num += 1

    if d < leave:
        days.append(
            {
                "label": f"Day {day_num} — {d.strftime('%a %b %d')}",
                "plan": (
                    "Optional: Chena Hot Springs — soak, Ice Museum, lunch at resort "
                    "(drive yourself or book a day shuttle from Fairbanks). "
                    "Or stay in town: Museum of the North / Pioneer Park."
                ),
            }
        )
        d += timedelta(days=1)
        day_num += 1

    while d < leave:
        days.append(
            {
                "label": f"Day {day_num} — {d.strftime('%a %b %d')}",
                "plan": (
                    "Museum of the North or Pioneer Park. Local dinner "
                    "(Pumphouse or Pike's Landing). Last aurora night."
                ),
            }
        )
        d += timedelta(days=1)
        day_num += 1

    days.append(
        {
            "label": f"Day {day_num} — {leave.strftime('%a %b %d')}",
            "plan": (
                "Wake up, check out, taxi or shuttle to FAI. "
                "Fly home on a daytime departure — avoid red-eyes."
            ),
        }
    )
    return days
