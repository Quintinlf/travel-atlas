"""Normalize and rank hotel search rows (provider-agnostic)."""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence
from urllib.parse import quote_plus

from src_phase1.pin_repository import haversine_km

# Old Town / Waverley corridor (plan defaults).
EDINBURGH_CENTER = (55.9500, -3.1880)
WAVERLEY_STATION = (55.9520, -3.1890)
DEFAULT_RADIUS_KM = 0.8
MAP_RADIUS_KM = 2.0
SLEEP_EXCLUSION_RADIUS_KM = 0.5
WALK_FACTOR = 1.25

CONTEXT_PINS: dict[str, tuple[float, float]] = {
    "calton_hill": (55.9549, -3.1824),
    "david_hume": (55.9497, -3.1906),
    "national_museum": (55.9470, -3.1898),
    "arthurs_seat": (55.9442, -3.1618),
}

CONTEXT_PIN_LABELS: dict[str, str] = {
    "calton_hill": "Calton Hill",
    "david_hume": "David Hume Statue",
    "national_museum": "National Museum of Scotland",
    "arthurs_seat": "Arthur's Seat",
}


def _photo_url(meta: Mapping[str, Any]) -> str | None:
    for key in ("main_photo", "mainPhoto", "photo_url", "thumbnail", "thumbnailUrl"):
        raw = meta.get(key)
        if raw and str(raw).startswith("http"):
            return str(raw)
    images = meta.get("hotelImages") or meta.get("images") or []
    if isinstance(images, list):
        for item in images:
            if not isinstance(item, Mapping):
                continue
            url = item.get("url") or item.get("thumbnailUrl")
            if url and str(url).startswith("http"):
                return str(url)
    return None


def distance_km_to_center(
    lat: float,
    lon: float,
    *,
    center: tuple[float, float] = EDINBURGH_CENTER,
) -> float:
    return round(haversine_km(lat, lon, center[0], center[1]), 3)


def walking_km_to_waverley(
    lat: float,
    lon: float,
    *,
    station: tuple[float, float] = WAVERLEY_STATION,
    walk_factor: float = WALK_FACTOR,
) -> float:
    return round(haversine_km(lat, lon, station[0], station[1]) * walk_factor, 3)


def within_radius(
    lat: float,
    lon: float,
    *,
    center: tuple[float, float] = EDINBURGH_CENTER,
    radius_km: float = DEFAULT_RADIUS_KM,
) -> bool:
    return haversine_km(lat, lon, center[0], center[1]) <= radius_km + 1e-9


def is_sleep_zone(
    lat: float,
    lon: float,
    *,
    center: tuple[float, float] = EDINBURGH_CENTER,
    radius_km: float = MAP_RADIUS_KM,
) -> bool:
    """True for urban lodging in the map window; Arthur's Seat hillside is out.

    Arthur's Seat exclusion only applies when the search center is Edinburgh.
    """
    if not within_radius(lat, lon, center=center, radius_km=radius_km):
        return False
    edinburgh_center = (
        abs(center[0] - EDINBURGH_CENTER[0]) < 0.05
        and abs(center[1] - EDINBURGH_CENTER[1]) < 0.05
    )
    if edinburgh_center:
        seat = CONTEXT_PINS["arthurs_seat"]
        if haversine_km(lat, lon, seat[0], seat[1]) <= SLEEP_EXCLUSION_RADIUS_KM:
            return False
    return True


def bbox_from_center(
    lat: float,
    lon: float,
    *,
    radius_km: float = MAP_RADIUS_KM,
) -> dict[str, float]:
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * max(0.2, math.cos(math.radians(lat))))
    return {
        "sw_lat": lat - dlat,
        "sw_lon": lon - dlon,
        "ne_lat": lat + dlat,
        "ne_lon": lon + dlon,
    }


def passes_rating_filter(
    rating: float | None,
    *,
    scale: float | None = None,
) -> tuple[bool, bool]:
    """Return (include, rating_unknown).

    Drop rated hotels below 3.5/5 or 7.0/10. Unrated hotels are kept with
    rating_unknown=True so they sort after rated ones.
    """
    if rating is None:
        return True, True
    try:
        value = float(rating)
    except (TypeError, ValueError):
        return True, True
    if scale is None:
        scale = 10.0 if value > 5.0 else 5.0
    if float(scale) >= 9.5:
        return value >= 7.0, False
    return value >= 3.5, False


def consumer_booking_links(
    hotel_name: str,
    *,
    check_in: str,
    check_out: str,
    city: str = "Edinburgh",
    adults: int = 2,
) -> dict[str, str]:
    q = quote_plus(f"{hotel_name} {city}")
    date_q = f"&checkin={check_in}&checkout={check_out}"
    if adults > 1:
        date_q += f"&group_adults={adults}"
    return {
        "booking": f"https://www.booking.com/searchresults.html?ss={q}{date_q}",
        "google_hotels": f"https://www.google.com/travel/hotels/{q}",
        "airbnb": (
            f"https://www.airbnb.com/s/{q}/homes?checkin={check_in}&checkout={check_out}"
        ),
    }


def area_booking_links(
    *,
    city: str,
    check_in: str,
    check_out: str,
    center: tuple[float, float] = EDINBURGH_CENTER,
    radius_km: float = MAP_RADIUS_KM,
    adults: int = 2,
) -> dict[str, str]:
    q = quote_plus(city)
    bbox = bbox_from_center(center[0], center[1], radius_km=radius_km)
    date_q = f"&checkin={check_in}&checkout={check_out}"
    if adults > 1:
        date_q += f"&group_adults={adults}"
    airbnb_bbox = (
        f"&ne_lat={bbox['ne_lat']:.5f}&ne_lng={bbox['ne_lon']:.5f}"
        f"&sw_lat={bbox['sw_lat']:.5f}&sw_lng={bbox['sw_lon']:.5f}"
    )
    return {
        "booking": f"https://www.booking.com/searchresults.html?ss={q}{date_q}",
        "expedia": f"https://www.expedia.com/Hotel-Search?destination={q}",
        "hotels_com": f"https://www.hotels.com/Hotel-Search?destination={q}",
        "airbnb": (
            f"https://www.airbnb.com/s/{q}/homes?checkin={check_in}"
            f"&checkout={check_out}{airbnb_bbox}"
        ),
        "google_hotels": f"https://www.google.com/travel/hotels/{q}",
    }


def _normalize(values: Sequence[float]) -> list[float]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-12:
        return [0.0 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def weighted_rank_score(
    *,
    price: float,
    distance_km: float,
    price_norm: float,
    distance_norm: float,
    price_weight: float = 0.7,
    distance_weight: float = 0.3,
) -> float:
    """Lower is better (cheaper + closer)."""
    _ = (price, distance_km)
    return round(price_weight * price_norm + distance_weight * distance_norm, 6)


def rank_hotel_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    price_weight: float = 0.7,
    distance_weight: float = 0.3,
) -> list[dict[str, Any]]:
    """Attach weighted_score and return rows sorted best-first.

    Rated hotels come before unrated; within each group use weighted score,
    then total_price, then distance.
    """
    priced = [dict(r) for r in rows if r.get("total_price") is not None]
    if not priced:
        return [dict(r) for r in rows]

    prices = [float(r["total_price"]) for r in priced]
    dists = [float(r.get("distance_km_to_center") or 0.0) for r in priced]
    price_norms = _normalize(prices)
    dist_norms = _normalize(dists)

    for row, p_n, d_n in zip(priced, price_norms, dist_norms):
        row["weighted_score"] = weighted_rank_score(
            price=float(row["total_price"]),
            distance_km=float(row.get("distance_km_to_center") or 0.0),
            price_norm=p_n,
            distance_norm=d_n,
            price_weight=price_weight,
            distance_weight=distance_weight,
        )

    priced.sort(
        key=lambda r: (
            1 if r.get("rating_unknown") else 0,
            float(r.get("weighted_score") or 0.0),
            float(r.get("total_price") or 0.0),
            float(r.get("distance_km_to_center") or 0.0),
            str(r.get("hotel_name") or ""),
        )
    )
    return priced


def sorted_by_price(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    priced = [dict(r) for r in rows if r.get("total_price") is not None]
    priced.sort(
        key=lambda r: (
            float(r["total_price"]),
            float(r.get("distance_km_to_center") or 0.0),
            str(r.get("hotel_name") or ""),
        )
    )
    return priced


def build_summary(ranked: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_price = sorted_by_price(ranked)
    lowest = by_price[0] if by_price else None
    return {
        "count": len(ranked),
        "lowest_rate": (
            {
                "hotel_name": lowest.get("hotel_name"),
                "total_price": lowest.get("total_price"),
                "nightly_rate": lowest.get("nightly_rate"),
                "currency": lowest.get("currency"),
                "distance_km_to_center": lowest.get("distance_km_to_center"),
                "amadeus_hotel_id": lowest.get("amadeus_hotel_id"),
            }
            if lowest
            else None
        ),
    }


def _nights(check_in: str, check_out: str) -> int:
    from datetime import date

    start = date.fromisoformat(check_in)
    end = date.fromisoformat(check_out)
    return max(1, (end - start).days)


def _hotel_coords(hotel: Mapping[str, Any]) -> tuple[float, float] | None:
    geo = hotel.get("geoCode") or hotel.get("geo_code") or {}
    lat = geo.get("latitude") if isinstance(geo, Mapping) else None
    lon = geo.get("longitude") if isinstance(geo, Mapping) else None
    if lat is None:
        lat = hotel.get("latitude")
    if lon is None:
        lon = hotel.get("longitude")
    try:
        if lat is None or lon is None:
            return None
        return float(lat), float(lon)
    except (TypeError, ValueError):
        return None


def _extract_rating(
    hotel: Mapping[str, Any], offer_hotel: Mapping[str, Any]
) -> tuple[float | None, float | None]:
    for source in (offer_hotel, hotel):
        rating = source.get("rating") or source.get("hotelRating")
        ratings = source.get("ratings")
        if rating is None and isinstance(ratings, list) and ratings:
            first = ratings[0] if isinstance(ratings[0], Mapping) else {}
            rating = first.get("rating") or first.get("value")
        if rating is None:
            continue
        try:
            value = float(rating)
        except (TypeError, ValueError):
            continue
        scale = 10.0 if value > 5.0 else 5.0
        return value, scale
    return None, None


def normalize_amadeus_offer_row(
    hotel: Mapping[str, Any],
    offer_block: Mapping[str, Any],
    *,
    check_in: str,
    check_out: str,
    center: tuple[float, float] = EDINBURGH_CENTER,
    radius_km: float = MAP_RADIUS_KM,
) -> dict[str, Any] | None:
    """Turn one Amadeus hotel + offers block into a compare row, or None if filtered."""
    coords = _hotel_coords(hotel) or _hotel_coords(dict(offer_block.get("hotel") or {}))
    if coords is None:
        return None
    lat, lon = coords
    if not is_sleep_zone(lat, lon, center=center, radius_km=radius_km):
        return None

    offer_hotel = dict(offer_block.get("hotel") or {})
    name = (
        offer_hotel.get("name")
        or hotel.get("name")
        or hotel.get("hotelId")
        or "Unknown hotel"
    )
    hotel_id = str(
        offer_hotel.get("hotelId")
        or hotel.get("hotelId")
        or hotel.get("hotel_id")
        or ""
    )
    rating, scale = _extract_rating(hotel, offer_hotel)
    include, unknown = passes_rating_filter(rating, scale=scale)
    if not include:
        return None

    offers = offer_block.get("offers") or []
    if not offers:
        return None
    best = offers[0] if isinstance(offers[0], Mapping) else {}
    price = best.get("price") or {}
    try:
        total = float(price.get("total") or price.get("grandTotal") or 0)
    except (TypeError, ValueError):
        return None
    if total <= 0:
        return None
    currency = str(price.get("currency") or "GBP")
    nights = _nights(check_in, check_out)
    nightly = round(total / nights, 2)
    links = consumer_booking_links(str(name), check_in=check_in, check_out=check_out)

    context_distances = {
        key: round(distance_km_to_center(lat, lon, center=pin), 3)
        for key, pin in CONTEXT_PINS.items()
    }

    return {
        "hotel_name": str(name),
        "provider": "amadeus",
        "nightly_rate": nightly,
        "total_price": round(total, 2),
        "currency": currency,
        "rating": rating,
        "rating_scale": scale,
        "rating_unknown": unknown,
        "lat": lat,
        "lon": lon,
        "distance_km_to_center": distance_km_to_center(lat, lon, center=center),
        "walking_km_to_waverley": walking_km_to_waverley(lat, lon),
        "distance_km_to_context_pins": context_distances,
        "booking_url": links["booking"],
        "google_hotels_url": links["google_hotels"],
        "airbnb_url": links["airbnb"],
        "amadeus_hotel_id": hotel_id,
        "offer_id": str(best.get("id") or ""),
    }


def normalize_nuitee_offer_row(
    hotel: Mapping[str, Any],
    offer_block: Mapping[str, Any],
    *,
    check_in: str,
    check_out: str,
    center: tuple[float, float] = EDINBURGH_CENTER,
    radius_km: float = MAP_RADIUS_KM,
    adults: int = 2,
    city: str = "Edinburgh",
    bed_verify: bool = False,
) -> dict[str, Any] | None:
    """Turn one Nuitee hotel + offers block into a compare row, or None if filtered."""
    coords = _hotel_coords(hotel) or _hotel_coords(dict(offer_block.get("hotel") or {}))
    if coords is None:
        # Rates-only rows may lack coords; keep them if the provider already
        # filtered by geocode radius.
        lat = lon = None
    else:
        lat, lon = coords
        if not is_sleep_zone(lat, lon, center=center, radius_km=radius_km):
            return None

    offer_hotel = dict(offer_block.get("hotel") or {})
    name = (
        offer_hotel.get("name")
        or hotel.get("name")
        or hotel.get("hotelId")
        or "Unknown hotel"
    )
    hotel_id = str(
        offer_hotel.get("hotelId")
        or hotel.get("hotelId")
        or hotel.get("hotel_id")
        or hotel.get("id")
        or ""
    )
    rating, scale = _extract_rating(hotel, offer_hotel)
    include, unknown = passes_rating_filter(rating, scale=scale)
    if not include:
        return None

    offers = offer_block.get("offers") or []
    if not offers:
        return None
    best = offers[0] if isinstance(offers[0], Mapping) else {}
    price = best.get("price") or {}
    try:
        total = float(price.get("total") or price.get("grandTotal") or 0)
    except (TypeError, ValueError):
        return None
    if total <= 0:
        return None
    currency = str(price.get("currency") or "USD")
    nights = _nights(check_in, check_out)
    nightly = round(total / nights, 2)
    room_name = str(best.get("room_name") or "")
    links = consumer_booking_links(
        str(name),
        check_in=check_in,
        check_out=check_out,
        city=city,
        adults=adults,
    )

    context_distances = {}
    distance_center = None
    walking = None
    if lat is not None and lon is not None:
        context_distances = {
            key: round(distance_km_to_center(lat, lon, center=pin), 3)
            for key, pin in CONTEXT_PINS.items()
        }
        distance_center = distance_km_to_center(lat, lon, center=center)
        walking = walking_km_to_waverley(lat, lon)

    return {
        "hotel_name": str(name),
        "provider": "nuitee",
        "room_name": room_name,
        "bed_verify": bed_verify,
        "nightly_rate": nightly,
        "total_price": round(total, 2),
        "currency": currency,
        "rating": rating,
        "rating_scale": scale,
        "rating_unknown": unknown,
        "lat": lat,
        "lon": lon,
        "distance_km_to_center": distance_center,
        "walking_km_to_waverley": walking,
        "distance_km_to_context_pins": context_distances,
        "booking_url": links["booking"],
        "google_hotels_url": links["google_hotels"],
        "airbnb_url": links["airbnb"],
        "photo_url": _photo_url(hotel) or _photo_url(offer_hotel),
        "nuitee_hotel_id": hotel_id,
        "offer_id": str(best.get("id") or ""),
    }
