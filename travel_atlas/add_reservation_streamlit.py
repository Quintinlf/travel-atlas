"""Dedicated hotel reservation page — prefs, location picks, deep-link compare."""

from __future__ import annotations

import importlib
import sys
from datetime import date, timedelta
from pathlib import Path

import streamlit as st

_TRAVEL_ROOT = Path(__file__).parent.parent
if str(_TRAVEL_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRAVEL_ROOT))

import travel_atlas.services.astro_helper as _astro_helper_mod
import travel_atlas.services.trip_map as _trip_map_mod

importlib.reload(_astro_helper_mod)
importlib.reload(_trip_map_mod)

from src_phase1.geo_grouping import destination_matches
from travel_atlas.command_center_streamlit import get_cc_services
from travel_atlas.nav_pages import page
from travel_atlas.providers.booking import StubBookingProvider
from travel_atlas.services.hotel_compare import EDINBURGH_CENTER, MAP_RADIUS_KM
from travel_atlas.services.hotel_photo import resolve_hotel_photo
from travel_atlas.services.alaska_aurora import is_alaska_aurora_trip
from travel_atlas.services.hotel_search import (
    build_hotel_search_map,
    search_hotels_by_geocode,
)
from travel_atlas.services.lodging_advisor import (
    advise_lodging_type,
    nights_between,
    property_name_from_url,
    suggest_lodging_locations,
)
from travel_atlas.services.traveler_docs import CITY_COORDS
from travel_atlas.services.trip_context import select_trip, trip_regions

chart_layers_for_traveler = _astro_helper_mod.chart_layers_for_traveler
build_trip_map = _trip_map_mod.build_trip_map
render_map_layer_toggles = _trip_map_mod.render_map_layer_toggles
render_streamlit_map = _trip_map_mod.render_streamlit_map
render_pins_by_region = _trip_map_mod.render_pins_by_region
default_city_index = _trip_map_mod.default_city_index

USER_KEY = "local-default"


def _next_hotel_number(reservations: list[dict]) -> int:
    hotels = [r for r in reservations if r.get("kind") == "hotel"]
    return len(hotels) + 1


def _country_for_city(city: str) -> str:
    if city in {"England", "Scotland", "Wales", "Northern Ireland"}:
        return "United Kingdom"
    if city in {"Ireland", "France", "Spain", "Portugal"}:
        return city
    return city


def _render_edinburgh_hotels(
    *,
    check_in: date,
    check_out: date,
    lodging_kind: str,
) -> dict:
    st.header("Live hotels in this map area")
    st.caption(
        "Blue = your Edinburgh pins (Calton Hill, Hume, Museum, Arthur's Seat). "
        "Green/orange/red = Amadeus hotels from cheapest to dearest. "
        "Purple = inns/B&Bs from Google Places when a Maps key is set. "
        "Click a hotel marker to fill the name below."
    )
    if check_out <= check_in:
        st.warning("Check-out must be after check-in.")
        return {}
    cache_key = (
        "edinburgh",
        check_in.isoformat(),
        check_out.isoformat(),
        round(EDINBURGH_CENTER[0], 4),
        round(EDINBURGH_CENTER[1], 4),
        MAP_RADIUS_KM,
    )
    refresh = st.button("Refresh hotel search", key="edinburgh-hotel-refresh")
    if refresh or st.session_state.get("hotel_search_key") != cache_key:
        with st.spinner("Searching hotels near Old Town / New Town / Southside…"):
            st.session_state["hotel_search_result"] = search_hotels_by_geocode(
                latitude=EDINBURGH_CENTER[0],
                longitude=EDINBURGH_CENTER[1],
                check_in=check_in.isoformat(),
                check_out=check_out.isoformat(),
                radius_km=MAP_RADIUS_KM,
                city="Edinburgh",
            )
        st.session_state["hotel_search_key"] = cache_key
    result = dict(st.session_state.get("hotel_search_result") or {})
    hotels = list(result.get("sorted_by_price") or result.get("hotels") or [])
    lodging = list(result.get("lodging") or [])
    fmap = build_hotel_search_map(hotels, lodging=lodging, center=EDINBURGH_CENTER)
    clicked = render_streamlit_map(
        fmap,
        key="edinburgh-hotels-map-v1",
        height=520,
        caption=(
            "Cheapest hotels are green. Click a marker, then open Booking / Google Hotels / Airbnb."
        ),
        return_clicks=True,
    )
    tooltip = (clicked or {}).get("last_object_clicked_tooltip") if clicked else None
    by_name = {str(row.get("hotel_name") or ""): row for row in hotels + lodging}
    if tooltip and tooltip in by_name:
        picked = by_name[tooltip]
        st.session_state["hotel_property_name"] = tooltip
        st.session_state["hotel_booking_url"] = str(
            picked.get("booking_url")
            or picked.get("google_hotels_url")
            or picked.get("google_maps_url")
            or ""
        )
        nightly = picked.get("nightly_rate") or picked.get("total_price")
        if nightly:
            st.session_state["hotel_estimated_cost"] = float(nightly)

    summary = result.get("summary") or {}
    lowest = summary.get("lowest_rate") or {}
    if not result.get("ok"):
        st.warning(result.get("message") or "Hotel search unavailable.")
    elif lowest:
        st.success(
            f"Cheapest live quote: **{lowest.get('hotel_name')}** — "
            f"{lowest.get('total_price')} {lowest.get('currency')} "
            f"({lowest.get('distance_km_to_center')} km from Waverley)."
        )
    ranked = list(result.get("ranked") or [])
    if ranked:
        best = ranked[0]
        st.caption(
            f"Best cheap+close (rated first): {best.get('hotel_name')} · "
            f"{best.get('total_price')} {best.get('currency')}"
        )
    if hotels:
        st.dataframe(
            [
                {
                    "hotel": row.get("hotel_name"),
                    "total": row.get("total_price"),
                    "nightly": row.get("nightly_rate"),
                    "currency": row.get("currency"),
                    "km_center": row.get("distance_km_to_center"),
                    "walk_waverley": row.get("walking_km_to_waverley"),
                    "rating": row.get("rating"),
                }
                for row in hotels
            ],
            hide_index=True,
            use_container_width=True,
        )
    if lodging and lodging_kind in {"apartment", "either"}:
        st.caption(f"{len(lodging)} nearby inns / B&Bs from Google Places (no live rate).")
    return result


def _render_alaska_hotels(
    *,
    city: str,
    latitude: float,
    longitude: float,
    check_in: date,
    check_out: date,
) -> dict:
    st.header("Live hotels near this stay")
    st.caption("Stay-put search around the one Alaska base. Edinburgh map is not used.")
    if check_out <= check_in:
        st.warning("Check-out must be after check-in.")
        return {}
    cache_key = (
        "alaska",
        city,
        check_in.isoformat(),
        check_out.isoformat(),
        round(latitude, 4),
        round(longitude, 4),
    )
    refresh = st.button("Refresh hotel search", key="alaska-hotel-refresh")
    if refresh or st.session_state.get("hotel_search_key") != cache_key:
        with st.spinner(f"Searching hotels near {city}…"):
            st.session_state["hotel_search_result"] = search_hotels_by_geocode(
                latitude=latitude,
                longitude=longitude,
                check_in=check_in.isoformat(),
                check_out=check_out.isoformat(),
                radius_km=20.0,
                currency="USD",
                city=city,
            )
        st.session_state["hotel_search_key"] = cache_key
    result = dict(st.session_state.get("hotel_search_result") or {})
    hotels = list(result.get("sorted_by_price") or result.get("hotels") or [])
    if hotels:
        st.dataframe(
            [
                {
                    "hotel": row.get("hotel_name"),
                    "total": row.get("total_price"),
                    "nightly": row.get("nightly_rate"),
                    "currency": row.get("currency"),
                }
                for row in hotels
            ],
            hide_index=True,
            use_container_width=True,
        )
        lowest = (result.get("summary") or {}).get("lowest_rate") or {}
        if lowest:
            st.session_state["hotel_property_name"] = str(lowest.get("hotel_name") or "")
            if lowest.get("total_price"):
                st.session_state["hotel_estimated_cost"] = float(lowest["total_price"])
    if not result.get("ok"):
        st.caption(result.get("message") or "Live hotel search unavailable.")
    return result


def main() -> None:
    st.set_page_config(page_title="Add hotel reservation", layout="wide")
    s = get_cc_services()
    st.title("Add lodging")
    st.caption(
        "Answer a few preference questions, see live hotels on the map for Edinburgh, "
        "then compare Booking / Expedia / Hotels.com / Airbnb / Google Hotels. "
        "Atlas never takes payment — you can simulate reserved."
    )
    if st.button("← Back to Command Center"):
        st.switch_page(page("command-center"))

    trip = select_trip(s["trip_service"], key="hotel_trip_id")
    if not trip:
        return

    alaska = is_alaska_aurora_trip(trip)
    definition = trip.get("definition") or {}
    default_in = date.today() + timedelta(days=90)
    default_out = date.today() + timedelta(days=93)
    if alaska:
        try:
            if definition.get("departure_date"):
                default_in = date.fromisoformat(str(definition["departure_date"])[:10])
            if definition.get("return_date"):
                default_out = date.fromisoformat(str(definition["return_date"])[:10])
        except ValueError:
            pass

    existing = s["reservations"].list_for_trip(trip["id"])
    hotel_n = _next_hotel_number(existing)
    auto_title = f"{trip['name']} hotel #{hotel_n}"

    # Trip pins + lodging clusters + astro lines
    all_pins = s["pin_service"].list_pins()
    trip_pins = []
    for dest in trip.get("destinations") or []:
        kind = dest.get("destination_kind") or dest.get("kind") or "country"
        label = (dest.get("destination_label") or dest.get("label") or "").replace(
            " (UK)", ""
        )
        trip_pins.extend(p for p in all_pins if destination_matches(p, kind, label))
    picks_preview = suggest_lodging_locations(
        trip_pins, trip.get("destinations") or [], limit=6
    )
    primary = s["travelers"].ensure_primary(USER_KEY)
    companion = s["travelers"].ensure_companion(USER_KEY)
    acg_who = st.radio(
        "Natal for map",
        options=["Traveler One", "Traveler Two", "Both"],
        horizontal=True,
        key="hotel-acg-traveler",
    )
    companion_acg: list = []
    companion_aspects: list = []
    if acg_who == "Companion":
        acg_lines, aspect_lines, acg_msg = chart_layers_for_traveler(companion)
        natal_label = companion.get("display_name")
    elif acg_who == "Both":
        acg_lines, aspect_lines, acg_msg = chart_layers_for_traveler(primary)
        companion_acg, companion_aspects, companion_msg = chart_layers_for_traveler(companion)
        natal_label = f"{primary.get('display_name')} + {companion.get('display_name')}"
        if companion_msg != "ok":
            st.caption(f"Companion ACG: {companion_msg}")
    else:
        acg_lines, aspect_lines, acg_msg = chart_layers_for_traveler(primary)
        natal_label = primary.get("display_name")
    st.header("Map — lodging zones, pins, astro layers")
    st.caption(
        "Red = suggested sleep areas from your pin clusters. Grey = trip pins. "
        "Bold planetary glyphs = angular lines; smaller glyphs = aspects. "
        f"Natal: {natal_label}."
    )
    if acg_msg != "ok":
        st.caption(f"Astro: {acg_msg}")
    flags = render_map_layer_toggles(
        key_prefix="hotel-map",
        acg_available=(acg_msg == "ok"),
    )
    fmap = build_trip_map(
        trip_pins,
        picks_preview,
        acg_lines=acg_lines,
        aspect_lines=aspect_lines,
        companion_acg_lines=companion_acg or None,
        companion_aspect_lines=companion_aspects or None,
        **flags,
    )
    render_streamlit_map(fmap, key="hotel-trip-overview-map-v1")
    render_pins_by_region(trip_pins, key_prefix="hotel-pins")
    st.caption(
        "Apartment vs hotel also affects bringing someone back — check guest rules on the listing."
    )

    st.header("1. What are you looking for?")
    c1, c2 = st.columns(2)
    with c1:
        check_in = st.date_input("Check-in", value=default_in)
        check_out = st.date_input("Check-out", value=default_out)
        needs_kitchen = st.checkbox("Need a kitchen / self-catering", value=False)
        traveling_with_others = st.checkbox("Traveling with others (share space)", value=False)
    with c2:
        want_daily_cleaning = st.checkbox("Want daily cleaning / front desk", value=True)
        early_flex = st.checkbox("Might change nights last-minute", value=False)
        prefer_local = st.checkbox("Prefer a residential neighborhood vibe", value=False)
        requires_bidet = st.checkbox(
            "Require a bidet (hard filter)",
            value=True,
            help="Traveler One: listings without a bidet / washlet are out.",
        )
        budget_band = st.selectbox(
            "Budget band (per night, rough)",
            ["flexible", "budget", "mid", "upscale"],
        )

    nights = nights_between(check_in, check_out)
    advice = advise_lodging_type(
        nights=nights,
        needs_kitchen=needs_kitchen,
        traveling_with_others=traveling_with_others,
        want_daily_cleaning=want_daily_cleaning,
        early_checkout_flexibility=early_flex,
        prefer_local_neighborhood=prefer_local,
        requires_bidet=requires_bidet,
    )
    profile = s["preferences"].get_preferences(USER_KEY)
    acc = dict(profile.get("accommodation_preferences") or {})
    acc["requires_bidet"] = requires_bidet
    s["preferences"].update_preferences(
        list(profile.get("interests") or []),
        str(profile.get("travel_style") or "balanced"),
        acc,
        list(profile.get("learning_goals") or []),
        USER_KEY,
        profile.get("preferences"),
    )
    st.subheader("Hotel vs apartment")
    st.info(f"**{advice.summary}** ({nights} night(s) · budget: {budget_band})")
    for reason in advice.reasons:
        st.markdown(f"- {reason}")
    lodging_kind = st.radio(
        "Search as",
        ["hotel", "apartment", "either"],
        index=["hotel", "apartment", "either"].index(advice.recommendation),
        horizontal=True,
        help="Drives which compare links are emphasized; you can still open all sites.",
    )

    st.header("2. Where should you sleep? (from your itinerary pins)")
    picks = suggest_lodging_locations(
        s["pin_service"].list_pins(),
        trip.get("destinations") or [],
        limit=6,
    )
    regions = trip_regions(trip) or ["London"]
    suggested_cities = [p.city for p in picks if p.city]
    city_options = list(dict.fromkeys(suggested_cities + regions))
    if alaska:
        city_options = ["Fairbanks", "Chena Hot Springs"]
    elif "west europe" in str(trip.get("name") or "").casefold():
        if "Edinburgh" not in city_options:
            city_options = ["Edinburgh", *city_options]

    if picks:
        for pick in picks:
            samples = ", ".join(pick.sample_pins) if pick.sample_pins else "—"
            st.markdown(
                f"- **{pick.city}** ({pick.pin_count} pins) — {pick.rationale} "
                f"_e.g. {samples}_"
            )
    else:
        st.caption(
            "No saved pins matched this trip’s destinations yet — pick a region leg below."
        )

    city = st.selectbox(
        "City / region for this stay",
        city_options,
        index=default_city_index(city_options) if city_options else 0,
        key="hotel-city-v2",
        help="Ranked by pin clusters when available, then trip legs. West Europe opens on Edinburgh.",
    )
    country = _country_for_city(city)
    lat, lon = CITY_COORDS.get(city, (0.0, 0.0))
    if city.strip().casefold() == "edinburgh":
        lat, lon = EDINBURGH_CENTER

    hotel_search = None
    if city.strip().casefold() == "edinburgh":
        hotel_search = _render_edinburgh_hotels(
            check_in=check_in,
            check_out=check_out,
            lodging_kind=lodging_kind,
        )
    elif alaska and lat and lon:
        hotel_search = _render_alaska_hotels(
            city=city,
            latitude=lat,
            longitude=lon,
            check_in=check_in,
            check_out=check_out,
        )

    st.header("3. Compare sites & photo")
    st.subheader(auto_title)
    st.caption(f"{city}, {country} · order #{hotel_n} · lean: {lodging_kind}")

    hotels_from_search = bool(
        (hotel_search or {}).get("sorted_by_price") or (hotel_search or {}).get("hotels")
    )
    compare = StubBookingProvider().search(
        destination=f"{city}, {country}" + (" bidet" if requires_bidet else ""),
        kind="hotel",
        check_in=check_in.isoformat(),
        check_out=check_out.isoformat(),
        extras="bidet" if requires_bidet else "",
    )
    area_links = dict((hotel_search or {}).get("area_links") or {}) or dict(compare.links)
    st.info(
        (hotel_search or {}).get("message")
        or compare.payload.get("message")
    )
    st.caption(
        compare.payload.get("sort_hint")
        if not hotels_from_search
        else "Table above is cheapest first. Site buttons search the same map bbox."
    )

    # Emphasize Airbnb when apartment; hotels sites otherwise
    link_items = list(area_links.items())
    if lodging_kind == "apartment":
        link_items.sort(key=lambda kv: 0 if kv[0] == "airbnb" else 1)
    elif lodging_kind == "hotel":
        link_items.sort(key=lambda kv: 0 if kv[0] == "airbnb" else 1, reverse=True)

    cols = st.columns(len(link_items) or 1)
    for col, (name, url) in zip(cols, link_items):
        with col:
            st.link_button(name.replace("_", " ").title(), url, use_container_width=True)

    booking_url = st.text_input(
        "Paste the listing URL you chose (optional)",
        key="hotel_booking_url",
        placeholder="https://www.booking.com/hotel/...",
    )
    if not st.session_state.get("hotel_property_name"):
        parsed = property_name_from_url(booking_url or "")
        if parsed:
            st.session_state["hotel_property_name"] = parsed
    property_name = st.text_input(
        "Property / hotel name (for photo match)",
        key="hotel_property_name",
        help="Photos: Google Places if API key set → name-matched Commons → placeholder. "
        "Never a random city hotel image. Click a map marker to fill this.",
    )

    photo = resolve_hotel_photo(
        property_name=property_name or None,
        city=city,
        country=country,
        lat=lat,
        lon=lon,
    )
    if photo:
        st.image(photo.url, caption=f"{photo.attribution} · {photo.source}", use_container_width=True)
    else:
        st.caption(
            "No listing photo yet — add a property name (or paste a deep link that includes "
            "the name). Site partner photo APIs can plug in later once your accounts are live."
        )

    if "hotel_estimated_cost" not in st.session_state:
        st.session_state["hotel_estimated_cost"] = 0.0
    estimated = st.number_input(
        "Estimated cost (USD, optional)", min_value=0.0, key="hotel_estimated_cost"
    )
    notes = st.text_area(
        "Notes",
        value=(
            f"{lodging_kind} · {city}, {country} · {check_in} → {check_out} · "
            f"advice: {advice.summary}"
        ),
    )

    c_save, c_sim = st.columns(2)
    with c_save:
        if st.button("Save as book_now (not reserved yet)", use_container_width=True):
            s["reservations"].create(
                trip["id"],
                kind="hotel",
                title=auto_title if lodging_kind != "apartment" else auto_title.replace(
                    "hotel", "stay"
                ),
                status="book_now",
                place_ref=city,
                starts_at=check_in.isoformat(),
                ends_at=check_out.isoformat(),
                booking_url=booking_url or None,
                notes=notes,
                cost=float(estimated) if estimated else None,
                itinerary_day=hotel_n,
            )
            st.session_state["cc_selected_trip_id"] = trip["id"]
            st.success("Saved")
            st.switch_page(page("command-center"))
    with c_sim:
        if st.button("Simulate reserved (no payment)", type="primary", use_container_width=True):
            s["reservations"].create(
                trip["id"],
                kind="hotel",
                title=auto_title,
                status="reserved",
                place_ref=city,
                starts_at=check_in.isoformat(),
                ends_at=check_out.isoformat(),
                booking_url=booking_url or None,
                notes=notes + " · simulated booking",
                cost=float(estimated) if estimated else None,
                itinerary_day=hotel_n,
            )
            st.session_state["cc_selected_trip_id"] = trip["id"]
            st.success("Simulated reservation saved — trip may now be committed.")
            st.switch_page(page("command-center"))


if __name__ == "__main__":
    main()
