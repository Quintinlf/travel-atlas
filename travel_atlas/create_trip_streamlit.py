"""Dedicated page: create a trip with departure dates, then return to Command Center."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import streamlit as st

_TRAVEL_ROOT = Path(__file__).parent.parent
if str(_TRAVEL_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRAVEL_ROOT))

from travel_atlas.command_center_streamlit import get_cc_services
from travel_atlas.nav_pages import page

USER_KEY = "local-default"

DEFAULT_DESTINATIONS = [
    ("uk_nation", "Scotland"),
    ("uk_nation", "England"),
    ("country", "Ireland"),
    ("country", "France"),
    ("country", "Spain"),
    ("country", "Portugal"),
]


def main() -> None:
    st.set_page_config(page_title="Create trip", layout="wide")
    s = get_cc_services()

    st.title("Create trip with departure")
    st.caption(
        "Fill this out, then you'll return to Command Center with the new trip selected."
    )
    if st.button("← Back to Command Center"):
        st.switch_page(page("command-center"))

    with st.form("create_trip_page"):
        name = st.text_input("Trip name", value="West Europe trip")
        departure = st.date_input(
            "Departure", value=date.today() + timedelta(days=90)
        )
        return_date = st.date_input(
            "Return (optional)", value=date.today() + timedelta(days=104)
        )
        budget = st.number_input("Trip budget (USD)", min_value=0.0, value=3000.0)
        st.markdown("**Destinations (legs)**")
        selected = []
        for kind, label in DEFAULT_DESTINATIONS:
            days = st.number_input(
                f"Days in {label}",
                min_value=0,
                max_value=30,
                value=(
                    3
                    if label == "Scotland"
                    else 2
                    if label in {"England", "France", "Spain"}
                    else 1
                ),
                key=f"days-{label}",
            )
            if days > 0:
                selected.append({"kind": kind, "label": label, "day_count": int(days)})
        submitted = st.form_submit_button("Create trip and open Command Center")
        if submitted:
            if not name.strip() or not selected:
                st.error("Need a name and at least one destination with days > 0.")
            else:
                selected[0]["start_date"] = departure.isoformat()
                definition = {
                    "departure_date": departure.isoformat(),
                    "return_date": return_date.isoformat() if return_date else None,
                    "budget": float(budget) if budget else None,
                    "pace": "medium",
                    "energy": "medium",
                }
                created = s["trip_service"].create_trip(
                    name=name.strip(),
                    destinations=selected,
                    definition=definition,
                )
                s["trip_service"].set_active_focus(created["id"])
                s["mode"].set_focused_trip(created["id"], USER_KEY)
                st.session_state["active_trip_id"] = created["id"]
                st.session_state["cc_selected_trip_id"] = created["id"]
                st.success(f"Created {created['name']}")
                st.switch_page(page("command-center"))


if __name__ == "__main__":
    main()
