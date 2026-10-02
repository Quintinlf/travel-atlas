"""Dedicated flight reservation page — deep-link compare + simulate booking."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote_plus

import streamlit as st

_TRAVEL_ROOT = Path(__file__).parent.parent
if str(_TRAVEL_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRAVEL_ROOT))

from travel_atlas.command_center_streamlit import get_cc_services
from travel_atlas.nav_pages import page
from travel_atlas.providers.booking import StubBookingProvider
from travel_atlas.services.alaska_aurora import is_alaska_aurora_trip
from travel_atlas.services.alaska_bases import HOME_CITY
from travel_atlas.services.trip_context import select_trip, trip_regions

USER_KEY = "local-default"


def _next_flight_number(reservations: list[dict]) -> int:
    flights = [r for r in reservations if r.get("kind") == "flight"]
    return len(flights) + 1


def main() -> None:
    st.set_page_config(page_title="Add flight", layout="wide")
    s = get_cc_services()
    st.title("Add flight")
    st.caption(
        "Compare Google Flights / Kayak (sort by price). "
        "Atlas never takes payment — you can simulate reserved."
    )
    if st.button("← Back to Command Center"):
        st.switch_page(page("command-center"))

    trip = select_trip(s["trip_service"], key="flight_trip_id")
    if not trip:
        return

    existing = s["reservations"].list_for_trip(trip["id"])
    flight_n = _next_flight_number(existing)
    auto_title = f"{trip['name']} flight #{flight_n}"

    alaska = is_alaska_aurora_trip(trip)
    definition = trip.get("definition") or {}
    regions = trip_regions(trip) or ["Edinburgh (EDI)"]
    if alaska:
        regions = ["FAI"]
    elif "Edinburgh (EDI)" not in regions:
        regions = ["Edinburgh (EDI)", *regions]
    origin = st.text_input(
        "Origin (airport city / code)",
        value=HOME_CITY if alaska else "Seattle",
    )
    destination = st.selectbox(
        "Destination city / region (trip leg)",
        regions,
        index=0,
        key="flight_dest",
    )
    dest_query = "EDI" if "edinburgh" in destination.casefold() else destination
    default_depart = date.today() + timedelta(days=90)
    default_return = date.today() + timedelta(days=104)
    if alaska:
        try:
            if definition.get("departure_date"):
                default_depart = date.fromisoformat(str(definition["departure_date"])[:10])
            if definition.get("return_date"):
                default_return = date.fromisoformat(str(definition["return_date"])[:10])
        except ValueError:
            pass
    depart = st.date_input("Depart", value=default_depart)
    one_way = st.checkbox(
        "One-way / open-jaw (no return on this booking)",
        value=not alaska,
        help=(
            "Alaska stay-put is a round-trip from Los Angeles."
            if alaska
            else "West Europe opener lands at EDI. Book the homebound flight from Lisbon/Porto later."
        ),
    )
    ret = None
    if not one_way:
        ret = st.date_input("Return (optional)", value=default_return)
    pax = st.number_input("Passengers", min_value=1, max_value=8, value=1)

    st.subheader(auto_title)
    st.caption(f"{origin} → {dest_query} · order #{flight_n} · {pax} pax")

    compare = StubBookingProvider().search(
        destination=dest_query,
        kind="flight",
        check_in=depart.isoformat(),
        check_out=ret.isoformat() if ret else None,
    )
    q = quote_plus(f"Flights from {origin} to {dest_query}")
    links = dict(compare.links or {})
    links["google_flights"] = f"https://www.google.com/travel/flights?q={q}"
    kayak_path = f"{quote_plus(origin)}-{quote_plus(dest_query)}/{depart.isoformat()}"
    if ret:
        kayak_path += f"/{ret.isoformat()}"
    links.setdefault("kayak", f"https://www.kayak.com/flights/{kayak_path}")

    st.info(
        (compare.payload or {}).get("message")
        or "Open a site, sort by price, paste the booking URL below."
    )
    cols = st.columns(len(links) or 1)
    for col, (name, url) in zip(cols, links.items()):
        with col:
            st.link_button(name.replace("_", " ").title(), url, use_container_width=True)

    booking_url = st.text_input(
        "Paste the booking URL you chose (optional)",
        value="",
        placeholder="https://www.google.com/travel/flights/...",
    )
    estimated = st.number_input("Estimated cost (USD, optional)", min_value=0.0, value=0.0)
    notes = st.text_area(
        "Notes",
        value=(
            f"{origin} → {dest_query} · {depart}"
            + (f" → {ret}" if ret else " · one-way / open-jaw")
            + f" · {pax} pax"
        ),
    )

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Save as book_now (not reserved yet)", use_container_width=True):
            s["reservations"].create(
                trip["id"],
                kind="flight",
                title=auto_title,
                status="book_now",
                place_ref=destination,
                starts_at=depart.isoformat(),
                ends_at=ret.isoformat() if ret else None,
                booking_url=booking_url or None,
                notes=notes,
                cost=float(estimated) if estimated else None,
                itinerary_day=flight_n,
            )
            st.session_state["cc_selected_trip_id"] = trip["id"]
            st.success("Saved")
            st.switch_page(page("command-center"))
    with c2:
        if st.button(
            "Simulate reserved (no payment)", type="primary", use_container_width=True
        ):
            s["reservations"].create(
                trip["id"],
                kind="flight",
                title=auto_title,
                status="reserved",
                place_ref=destination,
                starts_at=depart.isoformat(),
                ends_at=ret.isoformat() if ret else None,
                booking_url=booking_url or None,
                notes=notes + " · simulated booking",
                cost=float(estimated) if estimated else None,
                itinerary_day=flight_n,
            )
            st.session_state["cc_selected_trip_id"] = trip["id"]
            st.success("Simulated reservation saved — trip may now be committed.")
            st.switch_page(page("command-center"))


if __name__ == "__main__":
    main()
