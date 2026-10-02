"""Live hotel search (Nuitee / LiteAPI) + optional Google Places lodging, plus map specs."""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any, Mapping, Protocol, Sequence

import folium
from folium import Map

from src_phase1.places_api import search_nearby_lodging
from travel_atlas.providers.nuitee_hotel import NuiteeHotelProvider, _is_two_queen_room
from travel_atlas.services.hotel_compare import (
    CONTEXT_PIN_LABELS,
    CONTEXT_PINS,
    EDINBURGH_CENTER,
    MAP_RADIUS_KM,
    area_booking_links,
    build_summary,
    is_sleep_zone,
    normalize_amadeus_offer_row,
    normalize_nuitee_offer_row,
    rank_hotel_rows,
    sorted_by_price,
)


class _HotelGeocodeProvider(Protocol):
    key: str

    def credentials_configured(self) -> bool: ...

    def search_by_geocode(self, **kwargs: Any) -> Any: ...


def _empty_payload() -> dict[str, Any]:
    return {
        "hotels": [],
        "ranked": [],
        "sorted_by_price": [],
        "lodging": [],
        "summary": {"count": 0, "lowest_rate": None},
        "area_links": {},
    }


def _search_with_optional_bed_fallback(
    client: _HotelGeocodeProvider,
    *,
    center: tuple[float, float],
    check_in: str,
    check_out: str,
    radius_km: float,
    adults: int,
    currency: str,
    bed_types: list[str] | None,
    fallback_without_bed_filter: bool,
) -> tuple[Any, bool]:
    """Search with bed filter; optionally retry without if too few results."""
    result = client.search_by_geocode(
        latitude=center[0],
        longitude=center[1],
        check_in=check_in,
        check_out=check_out,
        radius_km=radius_km,
        adults=adults,
        currency=currency,
        bed_types=bed_types,
    )
    if not bed_types or not fallback_without_bed_filter:
        return result, False
    offers = list((result.payload or {}).get("offers") or [])
    if result.status == "ok" and len(offers) > 0:
        return result, False
    fallback = client.search_by_geocode(
        latitude=center[0],
        longitude=center[1],
        check_in=check_in,
        check_out=check_out,
        radius_km=radius_km,
        adults=adults,
        currency=currency,
        bed_types=None,
    )
    if fallback.status == "ok":
        return fallback, True
    return result, False


def search_hotels_by_geocode(
    *,
    latitude: float = EDINBURGH_CENTER[0],
    longitude: float = EDINBURGH_CENTER[1],
    check_in: str,
    check_out: str,
    radius_km: float = MAP_RADIUS_KM,
    adults: int = 2,
    bed_types: list[str] | None = None,
    fallback_without_bed_filter: bool = True,
    currency: str = "GBP",
    env: str | None = None,
    provider: _HotelGeocodeProvider | None = None,
    include_google_lodging: bool = True,
    city: str = "Edinburgh",
) -> dict[str, Any]:
    _ = env  # kept for call-site compatibility (was Amadeus env)
    center = (float(latitude), float(longitude))
    links = area_booking_links(
        city=city,
        check_in=check_in,
        check_out=check_out,
        center=center,
        radius_km=radius_km,
        adults=adults,
    )
    client: _HotelGeocodeProvider = provider or NuiteeHotelProvider()
    if not client.credentials_configured():
        lodging = _google_lodging(center, radius_km) if include_google_lodging else []
        payload = _empty_payload()
        payload.update(
            {
                "ok": False,
                "lodging": lodging,
                "area_links": links,
                "message": (
                    "Set NUITEE_API_KEY (LiteAPI / Nuitee at docs.liteapi.travel). "
                    "Sandbox keys start with sand_."
                ),
            }
        )
        return payload

    result, bed_verify = _search_with_optional_bed_fallback(
        client,
        center=center,
        check_in=check_in,
        check_out=check_out,
        radius_km=radius_km,
        adults=adults,
        currency=currency,
        bed_types=bed_types,
        fallback_without_bed_filter=fallback_without_bed_filter,
    )
    if result.status != "ok":
        lodging = _google_lodging(center, radius_km) if include_google_lodging else []
        payload = _empty_payload()
        payload.update(
            {
                "ok": False,
                "lodging": lodging,
                "area_links": links,
                "message": (result.payload or {}).get("message") or result.status,
            }
        )
        return payload

    hotels = list((result.payload or {}).get("hotels") or [])
    offers = list((result.payload or {}).get("offers") or [])
    by_id = {
        str(h.get("hotelId") or h.get("hotel_id") or h.get("id") or ""): h
        for h in hotels
        if h.get("hotelId") or h.get("hotel_id") or h.get("id")
    }

    provider_key = str(getattr(client, "key", "") or result.provider or "")
    normalize = (
        normalize_nuitee_offer_row
        if "nuitee" in provider_key.casefold()
        else normalize_amadeus_offer_row
    )

    rows: list[dict[str, Any]] = []
    for block in offers:
        offer_hotel = dict(block.get("hotel") or {})
        hid = str(offer_hotel.get("hotelId") or offer_hotel.get("id") or "")
        base = by_id.get(hid) or offer_hotel
        if normalize is normalize_nuitee_offer_row:
            row = normalize(
                base,
                block,
                check_in=check_in,
                check_out=check_out,
                center=center,
                radius_km=radius_km,
                adults=adults,
                city=city,
                bed_verify=bed_verify,
            )
        else:
            row = normalize(
                base,
                block,
                check_in=check_in,
                check_out=check_out,
                center=center,
                radius_km=radius_km,
            )
        if row:
            rows.append(row)

    ranked = rank_hotel_rows(rows)
    if bed_types:
        two_queen = [
            row
            for row in ranked
            if _is_two_queen_room(str(row.get("room_name") or ""))
        ]
        if two_queen:
            ranked = [{**row, "bed_verify": False} for row in two_queen]
            bed_verify = False
    by_price = sorted_by_price(ranked)
    lodging = _google_lodging(center, radius_km) if include_google_lodging else []
    return {
        "ok": True,
        "message": (result.payload or {}).get("message") or "ok",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "query": {
            "center": {"lat": center[0], "lon": center[1]},
            "radius_km": radius_km,
            "check_in": check_in,
            "check_out": check_out,
            "adults": adults,
            "bed_types": bed_types or [],
            "bed_verify": bed_verify,
            "currency": currency,
            "city": city,
            "provider": provider_key or "nuitee",
            "context_pins": {
                key: {"lat": pin[0], "lon": pin[1]} for key, pin in CONTEXT_PINS.items()
            },
        },
        "summary": build_summary(ranked),
        "ranked": ranked,
        "sorted_by_price": by_price,
        "hotels": ranked,
        "lodging": lodging,
        "area_links": links,
    }


def _google_lodging(
    center: tuple[float, float], radius_km: float
) -> list[dict[str, Any]]:
    raw = search_nearby_lodging(
        latitude=center[0],
        longitude=center[1],
        radius_m=radius_km * 1000.0,
    )
    return [
        row
        for row in raw
        if is_sleep_zone(
            float(row["lat"]),
            float(row["lon"]),
            center=center,
            radius_km=radius_km,
        )
    ]


def hotel_marker_specs(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Pure marker payloads for tests and Folium (no network)."""
    priced = [r for r in rows if r.get("total_price") is not None]
    prices = [float(r["total_price"]) for r in priced]
    lo = min(prices) if prices else 0.0
    hi = max(prices) if prices else 0.0
    span = hi - lo if hi > lo else 1.0
    specs: list[dict[str, Any]] = []
    for row in rows:
        try:
            lat = float(row["lat"])
            lon = float(row["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        name = str(row.get("hotel_name") or "Hotel")
        price = row.get("total_price")
        if price is None:
            color = "#7c3aed"
        else:
            t = (float(price) - lo) / span
            if t <= 0.33:
                color = "#15803d"
            elif t <= 0.66:
                color = "#d97706"
            else:
                color = "#b91c1c"
        specs.append(
            {
                "lat": lat,
                "lon": lon,
                "name": name,
                "color": color,
                "tooltip": name,
                "popup_html": _hotel_popup_html(row),
            }
        )
    return specs


def context_pin_specs() -> list[dict[str, Any]]:
    return [
        {
            "lat": lat,
            "lon": lon,
            "name": CONTEXT_PIN_LABELS.get(key, key),
            "key": key,
        }
        for key, (lat, lon) in CONTEXT_PINS.items()
    ]


def add_hotel_markers(fmap: Map, rows: Sequence[Mapping[str, Any]]) -> Map:
    """Attach hotel CircleMarkers to an existing Folium map."""
    for spec in hotel_marker_specs(rows):
        folium.CircleMarker(
            location=[spec["lat"], spec["lon"]],
            radius=8,
            color=spec["color"],
            fill=True,
            fill_color=spec["color"],
            fill_opacity=0.85,
            popup=folium.Popup(spec["popup_html"], max_width=280),
            tooltip=spec["tooltip"],
        ).add_to(fmap)
    return fmap


def build_hotel_search_map(
    rows: Sequence[Mapping[str, Any]],
    *,
    lodging: Sequence[Mapping[str, Any]] | None = None,
    center: tuple[float, float] = EDINBURGH_CENTER,
    height: str = "520px",
) -> Map:
    fmap = folium.Map(
        location=[center[0], center[1]],
        zoom_start=14,
        control_scale=True,
        tiles="OpenStreetMap",
    )
    for pin in context_pin_specs():
        folium.CircleMarker(
            location=[pin["lat"], pin["lon"]],
            radius=6,
            color="#1d4ed8",
            fill=True,
            fill_opacity=0.7,
            popup=folium.Popup(pin["name"], max_width=220),
            tooltip=pin["name"],
        ).add_to(fmap)
    add_hotel_markers(fmap, rows)
    if lodging:
        add_hotel_markers(fmap, lodging)
    pad = 0.012
    lats = [center[0]] + [float(r["lat"]) for r in rows if r.get("lat") is not None]
    lons = [center[1]] + [float(r["lon"]) for r in rows if r.get("lon") is not None]
    lats.extend(pin["lat"] for pin in context_pin_specs())
    lons.extend(pin["lon"] for pin in context_pin_specs())
    fmap.fit_bounds(
        [
            [min(lats) - pad, min(lons) - pad],
            [max(lats) + pad, max(lons) + pad],
        ]
    )
    fmap.get_root().height = height
    return fmap


def _hotel_popup_html(row: Mapping[str, Any]) -> str:
    name = escape(str(row.get("hotel_name") or "Hotel"))
    bits = [f"<b>{name}</b>"]
    price = row.get("total_price")
    currency = escape(str(row.get("currency") or "GBP"))
    if price is not None:
        nightly = row.get("nightly_rate")
        bits.append(
            f"{currency} {float(price):.0f} total"
            + (f" · {currency} {float(nightly):.0f}/night" if nightly is not None else "")
        )
    else:
        bits.append("Inn / B&amp;B (no live rate)")
    rating = row.get("rating")
    if rating is not None:
        scale = row.get("rating_scale") or 5
        bits.append(f"Rating {float(rating):.1f}/{float(scale):.0f}")
    walk = row.get("walking_km_to_waverley")
    if walk is not None:
        bits.append(f"Walk to Waverley ~{float(walk):.2f} km")
    links = []
    if row.get("booking_url"):
        links.append(f'<a href="{escape(str(row["booking_url"]))}" target="_blank">Booking</a>')
    if row.get("google_hotels_url"):
        links.append(
            f'<a href="{escape(str(row["google_hotels_url"]))}" target="_blank">Google Hotels</a>'
        )
    if row.get("airbnb_url"):
        links.append(f'<a href="{escape(str(row["airbnb_url"]))}" target="_blank">Airbnb</a>')
    if row.get("google_maps_url"):
        links.append(
            f'<a href="{escape(str(row["google_maps_url"]))}" target="_blank">Google Maps</a>'
        )
    if links:
        bits.append(" · ".join(links))
    return "<br>".join(bits)
