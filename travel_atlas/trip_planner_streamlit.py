"""Multi-destination trip planner."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import streamlit as st

_TRAVEL_ROOT = Path(__file__).parent.parent
if str(_TRAVEL_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRAVEL_ROOT))

from src_phase1.geo_grouping import destination_matches, trip_pin_stats
from travel_atlas.destination_explorer_streamlit import get_services
from travel_atlas.services.region_map import region_map_image_url


def main() -> None:
    st.set_page_config(page_title="Trip Planner", layout="wide")
    (
        repository,
        pin_service,
        destination_service,
        annotation_service,
        notes_service,
        trip_service,
    ) = get_services()

    st.title("Trip Planner")
    st.caption(
        "Combine countries, UK nations (England/Scotland/Wales/NI), and US states. "
        "Republic of Ireland stays its own destination."
    )

    destinations = destination_service.list_destinations()
    if not destinations:
        st.warning("Add destinations first.")
        return

    with st.form("create_trip"):
        trip_name = st.text_input("Trip name", value="Europe 2026")
        selected_labels = st.multiselect(
            "Destinations",
            options=[item["display_name"] for item in destinations],
            default=[destinations[0]["display_name"]] if destinations else [],
        )
        day_count = st.number_input("Days per destination", min_value=1, value=2)
        trip_start_date = st.date_input("Trip start date (optional)", value=None)
        submitted = st.form_submit_button("Create trip")
        if submitted and selected_labels:
            chosen = [
                next(item for item in destinations if item["display_name"] == label)
                for label in selected_labels
            ]
            leg_destinations = []
            for index, item in enumerate(chosen):
                leg = {"kind": item["kind"], "label": item["label"], "day_count": day_count}
                if index == 0 and trip_start_date:
                    leg["start_date"] = trip_start_date.isoformat()
                leg_destinations.append(leg)
            definition = {}
            if trip_start_date:
                definition["departure_date"] = trip_start_date.isoformat()
            trip = trip_service.create_trip(
                name=trip_name,
                destinations=leg_destinations,
                definition=definition or None,
            )
            st.session_state["active_trip_id"] = trip["id"]
            st.success(f"Created trip: {trip_name}")

    trips = trip_service.list_trips()
    if not trips:
        return

    trip_id = st.selectbox(
        "Saved trips",
        [trip["id"] for trip in trips],
        format_func=lambda value: next(t["name"] for t in trips if t["id"] == value),
        index=0,
    )
    trip = trip_service.get_trip(trip_id)
    st.subheader(trip["name"])

    # Pin counts for this trip (UK split into nations; Ireland separate).
    trip_pins = []
    for destination in trip["destinations"]:
        kind = destination.get("destination_kind") or destination.get("kind")
        label = destination.get("destination_label") or destination.get("label")
        if not kind or not label:
            continue
        trip_pins.extend(
            pin
            for pin in pin_service.list_pins()
            if destination_matches(pin, kind, label)
        )
    stats = trip_pin_stats(trip_pins)
    with st.expander("Pin counts for this trip", expanded=True):
        st.caption(f"{stats['total']} pins across selected destinations")
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**Per country / UK nation**")
            for name, count in stats["by_destination"].items():
                st.markdown(f"- {name}: **{count}**")
        with col_b:
            st.markdown("**Per city**")
            for name, count in list(stats["by_city"].items())[:40]:
                st.markdown(f"- {name}: **{count}**")

    for destination in trip["destinations"]:
        seasonal_context = destination.get("seasonal_context")
        if not seasonal_context:
            continue
        with st.expander(f"Seasonal context — {destination['destination_label']}"):
            top_claim = (seasonal_context["seasonal_claims"] or seasonal_context["personal_notes"] or [None])[0]
            top_sky_event = (seasonal_context["anchor_sky_events"] or [None])[0]
            if top_claim:
                st.markdown(f"**{top_claim['value']['title']}** — {top_claim['value']['body']}")
            if top_sky_event:
                st.caption(f"{top_sky_event['title']}: {top_sky_event['description']}")
            if not top_claim and not top_sky_event:
                st.caption("No seasonal context matched for this leg's dates yet.")

    for day in trip["days"]:
        heading = f"Day {day['day']} — {day['destination_label']}"
        if day.get("date"):
            heading = f"Day {day['day']} — {day['date']} — {day['destination_label']}"
        st.markdown(f"### {heading}")
        day_coords = [
            (stop.get("latitude"), stop.get("longitude"))
            for slot in ("morning", "afternoon", "evening")
            for stop in (day.get(slot) or [])
            if stop.get("latitude") is not None and stop.get("longitude") is not None
        ]
        map_url = region_map_image_url(day_coords)
        if map_url:
            st.image(map_url, caption="Region overview", use_container_width=True)
        for slot in ("morning", "afternoon", "evening"):
            stops = day.get(slot) or []
            if stops:
                st.markdown(f"**{slot.title()}**")
                for stop in stops:
                    st.markdown(f"- {stop['name']}")


if __name__ == "__main__":
    main()
