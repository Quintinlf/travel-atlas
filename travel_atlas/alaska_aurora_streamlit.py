"""Fairbanks aurora planner — September space weather + hotels, then create a trip.

Home is Los Angeles (LAX). Stay put in Fairbanks for 3–4 aurora nights.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import streamlit as st

_TRAVEL_ROOT = Path(__file__).parent.parent
if str(_TRAVEL_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRAVEL_ROOT))

from travel_atlas.command_center_streamlit import get_cc_services
from travel_atlas.env_loader import load_travel_env
from travel_atlas.nav_pages import page
from travel_atlas.services.alaska_aurora import OPENER_VERSION
from travel_atlas.services.alaska_bases import (
    DEFAULT_BASE_KEY,
    FAIRBANKS_BASE,
    HOME_AIRPORT,
    HOME_CITY,
)
from travel_atlas.services.alaska_briefing import (
    briefing_filename,
    build_alaska_briefing_html,
)
from travel_atlas.services.alaska_flight_routes import route_briefing
from travel_atlas.services.fairbanks_trip_budget import build_trip_budget
from travel_atlas.services.fairbanks_guide import fairbanks_guide
from travel_atlas.services.aurora_service import AuroraService
from travel_atlas.services.aurora_weather import build_aurora_weather_report
from travel_atlas.services.flight_search import search_roundtrip_fares
from travel_atlas.services.hotel_search import search_hotels_by_geocode

load_travel_env()

PLAN_YEAR = 2026
PLAN_MONTH = 9
FALLBACK_START = date(2026, 9, 26)
FALLBACK_END = date(2026, 9, 30)
DEFAULT_TRAVELERS = 2
QUEEN_BED_TYPES = ["queen"]


def _hotel_table(hotel_result: dict) -> None:
    if not hotel_result.get("ok"):
        st.caption(hotel_result.get("message") or "Live rates unavailable — use the links.")
    query = hotel_result.get("query") or {}
    adults = int(query.get("adults") or DEFAULT_TRAVELERS)
    bed_types = query.get("bed_types") or []
    if bed_types:
        st.caption(
            f"Quoted for **{adults} adults**, one room, bed filter: "
            f"{', '.join(str(b) for b in bed_types)}."
        )
    elif query.get("bed_verify"):
        st.caption(
            f"Quoted for **{adults} adults** — verify 2-queen room on the booking site."
        )
    hotels = list(hotel_result.get("sorted_by_price") or hotel_result.get("hotels") or [])
    if hotels:
        st.dataframe(
            [
                {
                    "hotel": row.get("hotel_name"),
                    "room": row.get("room_name") or "—",
                    "total": row.get("total_price"),
                    "nightly": row.get("nightly_rate"),
                    "rating": row.get("rating"),
                    "verify_beds": "yes" if row.get("bed_verify") else "",
                    "photo": "yes" if row.get("photo_url") else "",
                    "book": row.get("booking_url") or "",
                }
                for row in hotels
            ],
            hide_index=True,
            use_container_width=True,
            column_config={
                "book": st.column_config.LinkColumn("Book", display_text="Booking.com"),
            },
        )
    area_links = hotel_result.get("area_links") or {}
    if area_links:
        cols = st.columns(min(len(area_links), 4))
        for col, (name, url) in zip(cols, area_links.items()):
            col.link_button(name.replace("_", " ").title(), url, use_container_width=True)


def _flight_section(*, airport: str, start: date, end: date, adults: int) -> dict:
    st.subheader(f"Flights {HOME_AIRPORT}↔{airport}")
    routes = route_briefing(adults=adults)
    st.info(
        f"**{routes['no_nonstop_summary']}** {routes['hubs_summary']}"
    )
    with st.expander("LAX→Anchorage is nonstop; ANC→FAI is a short hop"):
        st.caption(routes["anc_footnote"])
    st.caption(f"**Flights:** {routes['no_red_eye_summary']}")
    with st.spinner("Pulling Aviasales fares…"):
        flight_result = search_roundtrip_fares(
            origin=HOME_AIRPORT,
            destination=airport,
            depart=start,
            return_on=end,
            currency="usd",
            limit=10,
            adults=adults,
        )
    source = flight_result.get("fare_source")
    if source:
        st.caption(f"Fare source: `{source}` (prices are per adult in economy).")
    message = flight_result.get("message") or ""
    if message and not flight_result.get("fares"):
        st.info(message)
    elif not flight_result.get("ok"):
        st.caption(message or "Live fares unavailable — use the links.")
    fares = list(flight_result.get("fares") or [])
    if fares:
        st.dataframe(
            [
                {
                    "per_adult": row.get("price_per_adult") or row.get("price"),
                    "total_party": row.get("total_for_party"),
                    "currency": row.get("currency"),
                    "airline": row.get("airline"),
                    "depart": row.get("departure_at"),
                    "return": row.get("return_at"),
                    "stops": row.get("transfers"),
                    "source": row.get("source"),
                }
                for row in fares
            ],
            hide_index=True,
            use_container_width=True,
        )
    links = flight_result.get("links") or {}
    cols = st.columns(min(max(len(links), 1), 3))
    labels = {
        "aviasales": f"Aviasales ({adults} pax)",
        "google_flights": f"Google Flights {HOME_AIRPORT}→{airport}",
        "kayak": f"Kayak ({adults} adults)",
    }
    for col, (key, url) in zip(cols, links.items()):
        col.link_button(
            labels.get(key, key.replace("_", " ").title()),
            url,
            use_container_width=True,
        )
    return flight_result


def main() -> None:
    st.set_page_config(page_title="Fairbanks aurora", layout="wide")
    s = get_cc_services()
    base = FAIRBANKS_BASE
    st.title("Fairbanks aurora — stay put")
    st.caption(
        f"Home is **{HOME_CITY} ({HOME_AIRPORT})**. Fly **{HOME_AIRPORT}→FAI**, "
        "stay in Fairbanks for 3–4 nights. Scores use dark hours + NOAA Kp space "
        "weather + September equinox bonus — **not** cloud cover. "
        "Hotels via Nuitee (2 adults, queen beds); flights via Aviasales."
    )
    if st.button("← Back to Command Center"):
        st.switch_page(page("command-center"))

    travelers = st.number_input(
        "Travelers (adults)",
        min_value=1,
        max_value=6,
        value=DEFAULT_TRAVELERS,
        help="Flight totals multiply per-adult cached fares by this count.",
    )

    use_noaa = st.checkbox("Pull NOAA Kp hint (network)", value=True)
    aurora = AuroraService()

    with st.spinner("Scoring September aurora nights…"):
        month_nights = aurora.score_month(
            base, PLAN_YEAR, PLAN_MONTH, allow_network=use_noaa
        )
        recommended = AuroraService.best_stay_window(month_nights)

    default_start = recommended["arrive"] if recommended else FALLBACK_START
    default_end = recommended["leave"] if recommended else FALLBACK_END

    st.subheader(f"September {PLAN_YEAR} — night scores (Fairbanks)")
    month_table = [
        {
            "date": n.on_date.isoformat(),
            "night_hours": n.night_hours,
            "noaa_kp": n.noaa_kp,
            "combined": n.combined,
            "visible_enough": n.visible_enough,
        }
        for n in month_nights
    ]
    st.dataframe(month_table, hide_index=True, use_container_width=True)
    if recommended:
        st.info(
            f"**Recommended stay:** arrive **{recommended['arrive'].isoformat()}**, "
            f"leave **{recommended['leave'].isoformat()}** "
            f"({recommended['length']} nights, mean score "
            f"`{recommended['mean_aurora_score']}`). "
            f"Best single night: **{recommended['best_night']['date']}** "
            f"(score `{recommended['best_night']['combined']}`)."
        )
        st.caption(base.darker_skies_note)
    else:
        st.caption("Could not rank a window — pick dates manually below.")

    if use_noaa:
        st.caption(
            "NOAA Kp covers roughly the next 27 days from today. Later September "
            "nights still rank on darkness and equinox timing without live Kp."
        )

    c1, c2 = st.columns(2)
    with c1:
        start = st.date_input("Arrive", value=default_start)
    with c2:
        end = st.date_input("Leave", value=default_end)

    if end <= start:
        st.error("Leave date must be after arrive.")
        return
    day_count = (end - start).days
    if day_count < 3 or day_count > 4:
        st.warning("This trip is meant to be 3–4 nights. Scoring still runs.")

    stay_nights = aurora.score_window(base, start, end)
    mean = round(sum(n.combined for n in stay_nights) / max(len(stay_nights), 1), 1)
    st.subheader("Your stay — night by night")
    st.caption(f"Mean aurora score for this window: `{mean}`")
    st.dataframe([n.as_dict() for n in stay_nights], hide_index=True, use_container_width=True)

    use_cloud = st.checkbox("Pull cloud-cover forecast (Open-Meteo)", value=True)
    weather_report = build_aurora_weather_report(
        arrive=start,
        leave=end,
        allow_network=use_cloud,
    )
    st.subheader("Aurora viewing strategy")
    st.caption(weather_report["strategy_summary"])
    if weather_report.get("historical"):
        hist = weather_report["historical"]
        st.caption(
            f"Historical September: mean cloud ~{hist.get('mean_cloud_cover_pct')}%, "
            f"~{hist.get('clear_night_pct')}% clear nights."
        )
    st.dataframe(weather_report["nights"], hide_index=True, use_container_width=True)

    airport = base.airport
    flight_result = _flight_section(
        airport=airport, start=start, end=end, adults=int(travelers)
    )

    st.subheader("Hotels in Fairbanks")
    hotel_result = search_hotels_by_geocode(
        latitude=base.latitude,
        longitude=base.longitude,
        check_in=start.isoformat(),
        check_out=end.isoformat(),
        radius_km=20.0,
        adults=int(travelers),
        bed_types=QUEEN_BED_TYPES,
        currency="USD",
        city=base.hotel_query,
        include_google_lodging=True,
    )
    _hotel_table(hotel_result)

    st.subheader("Chena Hot Springs lodges (optional darker skies)")
    st.caption("Same trip — optional evening outing, not a second hotel booking.")
    chena_result = search_hotels_by_geocode(
        latitude=65.0519,
        longitude=-146.0478,
        check_in=start.isoformat(),
        check_out=end.isoformat(),
        radius_km=15.0,
        adults=int(travelers),
        bed_types=QUEEN_BED_TYPES,
        currency="USD",
        city="Chena Hot Springs, Alaska",
        include_google_lodging=True,
    )
    _hotel_table(chena_result)

    guide = fairbanks_guide(arrive=start, leave=end)
    with st.expander("Things to do, eat & see (included in briefing PDF)", expanded=False):
        st.markdown(f"**{guide['hot_springs']['tag']}** — {guide['hot_springs']['name']}")
        st.caption(guide["hot_springs"]["summary"])
        st.markdown(f"**Market:** {guide['markets']['note']}")
        st.markdown("**Places to eat:**")
        for row in guide["places_to_eat"][:4]:
            st.caption(f"- {row['name']} ({row['style']})")
        st.markdown("**Sample schedule:**")
        for day in guide["suggested_days"]:
            st.caption(f"**{day['label']}** — {day['plan']}")

    st.subheader("Trip briefing for booking")
    st.caption(
        "Generate a styled HTML packet for sharing or printing (Chrome/Edge → Print → "
        "Save as PDF). Core plan assumes **no rental car**; car and Chena are optional add-ons."
    )
    opt_car = st.checkbox("Include rental car in budget", value=False)
    opt_chena = st.checkbox("Include Chena day pass in budget", value=False)
    opt_chena_shuttle = st.checkbox(
        "Include Chena shuttle (no car)", value=False, disabled=opt_car
    )
    opt_aurora_tour = st.checkbox("Include guided aurora tour in budget", value=False)
    briefing_html = build_alaska_briefing_html(
        arrive=start,
        leave=end,
        travelers=int(travelers),
        flight_result=flight_result,
        hotel_result=hotel_result,
        stay_nights=stay_nights,
        allow_live_fetch=False,
    )
    st.download_button(
        "Generate briefing (HTML)",
        data=briefing_html.encode("utf-8"),
        file_name=briefing_filename(arrive=start),
        mime="text/html",
    )
    hotel_rows = list(hotel_result.get("sorted_by_price") or hotel_result.get("hotels") or [])
    hotel_total = float(hotel_rows[0]["total_price"]) if hotel_rows else None
    routes = route_briefing(adults=int(travelers))
    low, high = routes["flight_benchmark_per_adult"]
    budget = build_trip_budget(
        arrive=start,
        leave=end,
        travelers=int(travelers),
        hotel_total=hotel_total,
        flight_party_low=float(low * int(travelers)),
        flight_party_high=float(high * int(travelers)),
        include_car_rental=opt_car,
        include_chena=opt_chena,
        include_chena_shuttle=opt_chena_shuttle,
        include_aurora_tour=opt_aurora_tour,
        aurora_tour_maps_url=str(weather_report.get("tour_maps_url") or ""),
    )
    st.caption(
        f"Core trip (no car/Chena): **${budget['core_total_mid']:,.0f}** "
        f"(${budget['core_total_low']:,.0f}–${budget['core_total_high']:,.0f}). "
        f"With selected add-ons: **${budget['grand_total_mid']:,.0f}**."
    )

    st.subheader("Create this trip")
    name = st.text_input("Trip name", value="Alaska Northern Lights")
    budget = st.number_input("Budget (USD, optional)", min_value=0.0, value=3500.0)
    if st.button("Create stay-put trip and open Command Center", type="primary"):
        trip = s["trip_service"].create_trip(
            name=name.strip() or "Alaska Northern Lights",
            destinations=[
                {
                    "kind": "us_state",
                    "label": "Alaska",
                    "day_count": day_count,
                    "start_date": start.isoformat(),
                }
            ],
            definition={
                "departure_date": start.isoformat(),
                "return_date": end.isoformat(),
                "budget": float(budget) if budget else None,
                "pace": "slow",
                "energy": "low",
                "alaska_aurora": OPENER_VERSION,
                "aurora_base": DEFAULT_BASE_KEY,
                "aurora_airport": airport,
                "home_city": HOME_CITY,
                "home_airport": HOME_AIRPORT,
                "travelers": int(travelers),
            },
        )
        from travel_atlas.services.alaska_aurora import apply_alaska_aurora

        apply_alaska_aurora(
            s["trip_service"],
            s["reservations"],
            trip_id=trip["id"],
            prep_service=s["prep"],
        )
        st.session_state["cc_selected_trip_id"] = trip["id"]
        st.session_state["active_trip_id"] = trip["id"]
        st.switch_page(page("command-center"))


if __name__ == "__main__":
    main()
