"""Itinerary — planned trips only."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_TRAVEL_ROOT = Path(__file__).parent.parent
if str(_TRAVEL_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRAVEL_ROOT))

from travel_atlas.destination_explorer_streamlit import get_services
from travel_atlas.nav_pages import page
from travel_atlas.services.region_map import region_map_image_url
from travel_atlas.services.trip_context import select_trip


def main() -> None:
    st.set_page_config(page_title="Itinerary", layout="wide")
    (
        _repository,
        _pin_service,
        _destination_service,
        _annotation,
        _notes,
        trip_service,
    ) = get_services()

    st.title("Itinerary")
    st.caption("Day outlines for a planned trip only — with a region map per day.")

    trip = select_trip(trip_service, key="itinerary_trip_id")
    if not trip:
        st.page_link(page("create-trip"), label="Create a trip first")
        return

    days = trip.get("days") or []
    st.subheader(trip["name"])
    if not days:
        st.info(
            "This trip has no day outline yet. Build days in Trip Planner / Planning, "
            "then reopen Itinerary."
        )
        return

    for day in days:
        heading = f"Day {day['day']}"
        if day.get("date"):
            heading += f" — {day['date']}"
        if day.get("destination_label"):
            heading += f" — {day['destination_label']}"
        st.markdown(f"### {heading}")
        coords = [
            (stop.get("latitude"), stop.get("longitude"))
            for slot in ("morning", "afternoon", "evening")
            for stop in (day.get(slot) or [])
        ]
        map_url = region_map_image_url(coords)
        if map_url:
            st.image(map_url, caption="Region overview", use_container_width=True)
        for slot in ("morning", "afternoon", "evening"):
            stops = day.get(slot) or []
            if stops:
                st.markdown(f"**{slot.title()}**")
                for stop in stops:
                    st.markdown(f"- {stop.get('name')}")


if __name__ == "__main__":
    main()
