"""Estimated full-trip budget for Fairbanks aurora briefings."""

from __future__ import annotations

from datetime import date
from typing import Any

from travel_atlas.services.fairbanks_guide import fairbanks_guide


def _mid(low: float, high: float) -> float:
    return round((low + high) / 2, 2)


def _sum_items(items: list[dict[str, Any]], key: str) -> float:
    return round(sum(float(i[key]) for i in items), 2)


def build_trip_budget(
    *,
    arrive: date,
    leave: date,
    travelers: int = 2,
    hotel_total: float | None,
    flight_party_low: float,
    flight_party_high: float,
    flight_label: str = "benchmark",
    include_car_rental: bool = False,
    include_chena: bool = False,
    include_chena_shuttle: bool = False,
    include_aurora_tour: bool = True,
    aurora_tour_maps_url: str | None = None,
) -> dict[str, Any]:
    """Line-item budget for 2 travelers; food/activity lines are estimates."""
    nights = max((leave - arrive).days, 1)
    guide = fairbanks_guide(arrive=arrive, leave=leave)
    party = max(1, travelers)
    hs = guide["hot_springs"]

    line_items: list[dict[str, Any]] = []
    optional_line_items: list[dict[str, Any]] = []

    def add(
        bucket: list[dict[str, Any]],
        label: str,
        category: str,
        low: float,
        high: float,
        *,
        maps_url: str | None = None,
        fixed: bool = False,
        optional: bool = False,
    ) -> None:
        bucket.append(
            {
                "label": label,
                "category": category,
                "low": round(low, 2),
                "high": round(high, 2),
                "mid": _mid(low, high),
                "maps_url": maps_url,
                "fixed": fixed,
                "optional": optional,
            }
        )

    add(
        line_items,
        f"Flights round-trip ({party} adults, {flight_label})",
        "transport",
        flight_party_low,
        flight_party_high,
        fixed=flight_party_low == flight_party_high,
    )

    if not include_car_rental:
        add(
            line_items,
            "Airport rides — FAI ↔ hotel (taxi / rideshare, est.)",
            "transport",
            80.0,
            120.0,
        )

    if hotel_total is not None and hotel_total > 0:
        add(
            line_items,
            f"Hotel ({nights} nights, best 2-queen quote)",
            "lodging",
            float(hotel_total),
            float(hotel_total),
            fixed=True,
        )

    for sight in guide["things_to_see"]:
        est = sight.get("est_cost_party_usd")
        if est is None:
            continue
        low, high = float(est[0]), float(est[1])
        if low == 0 and high == 0:
            add(
                line_items,
                sight["name"],
                "activities",
                0.0,
                0.0,
                maps_url=sight.get("maps_url"),
            )
        else:
            add(
                line_items,
                sight["name"],
                "activities",
                low,
                high,
                maps_url=sight.get("maps_url"),
            )

    mk = guide["markets"]
    mest = mk.get("est_cost_party_usd") or (30, 80)
    add(
        line_items,
        "Farmers market — produce & pantry",
        "food",
        float(mest[0]),
        float(mest[1]),
        maps_url=mk.get("maps_url"),
    )
    dinner_nights = max(nights - 1, 1)
    add(
        line_items,
        f"Dinners in town (~{dinner_nights} nights, {party} people)",
        "food",
        60.0 * dinner_nights,
        120.0 * dinner_nights,
    )
    add(
        line_items,
        f"Lunches (~{nights} days, {party} people)",
        "food",
        30.0 * nights,
        50.0 * nights,
    )
    add(line_items, "Coffee, snacks, groceries", "food", 40.0, 60.0)
    add(
        line_items,
        "Souvenirs — Great Alaskan Bowl / market",
        "shopping",
        50.0,
        100.0,
        maps_url="https://www.google.com/maps/search/Great+Alaskan+Bowl+Company+Fairbanks",
    )

    car_low, car_high = 200.0, 350.0
    if nights != 4:
        scale = nights / 4.0
        car_low = round(car_low * scale, 2)
        car_high = round(car_high * scale, 2)
    add(
        optional_line_items,
        f"Optional: car rental ({nights} days)",
        "transport",
        car_low,
        car_high,
        optional=True,
    )
    add(
        optional_line_items,
        "Optional: gas — town + Chena round trip",
        "transport",
        40.0,
        70.0,
        optional=True,
    )
    est = hs.get("est_cost_party_usd") or (60, 90)
    add(
        optional_line_items,
        "Optional: Chena Hot Springs — soak + Ice Museum (day pass)",
        "activities",
        float(est[0]),
        float(est[1]),
        maps_url=hs.get("maps_url"),
        optional=True,
    )
    shuttle = hs.get("shuttle_cost_party_usd") or (160, 300)
    add(
        optional_line_items,
        "Optional: Chena day shuttle from Fairbanks (no car)",
        "activities",
        float(shuttle[0]),
        float(shuttle[1]),
        maps_url=hs.get("maps_url"),
        optional=True,
    )
    add(
        optional_line_items,
        "Optional guided aurora tour (1 night, cloud insurance)",
        "activities",
        150.0,
        300.0,
        maps_url=aurora_tour_maps_url,
        optional=True,
    )

    if include_car_rental:
        line_items = [i for i in line_items if "Airport rides" not in i["label"]]

    selected_optional: list[dict[str, Any]] = []
    if include_car_rental:
        selected_optional.extend(
            i
            for i in optional_line_items
            if "car rental" in i["label"].lower() or i["label"].startswith("Optional: gas")
        )
    if include_chena:
        selected_optional.extend(
            i for i in optional_line_items if "day pass" in i["label"].lower()
        )
    if include_chena_shuttle and not include_car_rental:
        selected_optional.extend(
            i for i in optional_line_items if "shuttle" in i["label"].lower()
        )
    if include_aurora_tour:
        selected_optional.extend(
            i for i in optional_line_items if "aurora tour" in i["label"].lower()
        )

    all_items = line_items + selected_optional

    subtotals: dict[str, dict[str, float]] = {}
    for item in all_items:
        cat = item["category"]
        bucket = subtotals.setdefault(cat, {"low": 0.0, "high": 0.0, "mid": 0.0})
        bucket["low"] += item["low"]
        bucket["high"] += item["high"]
        bucket["mid"] += item["mid"]

    core_low = _sum_items(line_items, "low")
    core_high = _sum_items(line_items, "high")
    core_mid = _sum_items(line_items, "mid")
    optional_low = _sum_items(optional_line_items, "low")
    optional_high = _sum_items(optional_line_items, "high")
    optional_mid = _sum_items(optional_line_items, "mid")

    return {
        "travelers": party,
        "nights": nights,
        "line_items": line_items,
        "optional_line_items": optional_line_items,
        "selected_optional": selected_optional,
        "subtotals": subtotals,
        "core_total_low": core_low,
        "core_total_high": core_high,
        "core_total_mid": core_mid,
        "optional_total_low": optional_low,
        "optional_total_high": optional_high,
        "optional_total_mid": optional_mid,
        "grand_total_low": round(core_low + _sum_items(selected_optional, "low"), 2),
        "grand_total_high": round(core_high + _sum_items(selected_optional, "high"), 2),
        "grand_total_mid": round(core_mid + _sum_items(selected_optional, "mid"), 2),
        "note": (
            "Core total excludes optional car, Chena, and aurora tour unless you add them. "
            f"Flights use {flight_label}; hotel uses live Nuitee quote. "
            "Without a car, budget airport rides and consider a Chena shuttle or guided aurora tour."
        ),
    }
