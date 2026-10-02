"""Health & medical — trip checklist + per-region paragraphs + safety skim."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import streamlit as st

_TRAVEL_ROOT = Path(__file__).parent.parent
if str(_TRAVEL_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRAVEL_ROOT))

from travel_atlas.destination_explorer_streamlit import ATLAS_DB_PATH, get_services
from travel_atlas.providers.state_dept import StateDeptSafetyProvider
from travel_atlas.services.preferences_service import PreferencesService
from travel_atlas.services.traveler_docs import TravelerDocsService
from travel_atlas.services.trip_context import (
    select_trip,
    select_trip_region,
    trip_regions,
)
from travel_atlas.ui_helpers import load_social_for, render_social_safety

USER_KEY = "local-default"

_CHECK_ITEMS = (
    ("passport", "Passport / GE reviewed for this leg"),
    ("entry", "Entry / visa notes skimmed"),
    ("vaccines", "Vaccines / health advisory skimmed"),
    ("embassy", "Embassy / emergency contacts noted"),
    ("safety", "Scams / street safety skimmed"),
)


def main() -> None:
    st.set_page_config(page_title="Health & medical", layout="wide")
    (
        repository,
        _pins,
        _destination_service,
        _annotation,
        _notes,
        trip_service,
    ) = get_services()
    prefs = PreferencesService(repository)
    docs = TravelerDocsService(
        prefs, StateDeptSafetyProvider(cache_db_path=_TRAVEL_ROOT / "atlas.db")
    )
    docs.ensure_defaults(USER_KEY)

    st.title("Health & medical")
    st.caption(
        "Trip-first passport, entry, vaccines, embassy — plus a per-region checklist. "
        "Educational only."
    )

    trip = select_trip(trip_service, key="health_trip_id")
    mode = st.radio(
        "Scope",
        ["This trip", "Research any destination"],
        horizontal=True,
        key="health_scope",
    )

    regions: list[str] = []
    if mode == "This trip":
        if not trip:
            return
        regions = trip_regions(trip)
        if not regions:
            st.info("Add destinations to this trip first.")
            return
        st.markdown("**Trip covers:** " + ", ".join(regions))

        st.subheader("Checklist — all regions")
        checks = st.session_state.setdefault("health_region_checks", {})
        for region in regions:
            st.markdown(f"**{region}**")
            cols = st.columns(len(_CHECK_ITEMS))
            for col, (key, label) in zip(cols, _CHECK_ITEMS):
                ck = f"{trip['id']}:{region}:{key}"
                with col:
                    checks[ck] = st.checkbox(
                        label,
                        value=bool(checks.get(ck)),
                        key=f"hc-{ck}",
                    )

        focus = select_trip_region(
            trip,
            key="health_region",
            label="Focus country / region",
        )
        if not focus:
            return
        with st.expander("All trip destinations — entry snapshot", expanded=False):
            for block in docs.entry_for_destinations(regions):
                dest = block.get("destination") or block.get("api_label")
                st.markdown(f"### {dest}")
                st.caption(f"Status: {block.get('status')}")
                if block.get("health"):
                    st.write((block["health"].get("body") or "")[:1200])
                if block.get("embassy"):
                    st.markdown("**Embassy**")
                    st.write((block["embassy"].get("body") or "")[:800])
        api_label = focus
    else:
        fallback = [
            "United Kingdom",
            "Ireland",
            "France",
            "Spain",
            "Portugal",
            "England",
            "Scotland",
            "Wales",
        ]
        api_label = st.selectbox("Destination", fallback, key="health_research_dest")

    departure = None
    if trip:
        defn = trip.get("definition") or {}
        raw = defn.get("departure_date")
        if raw:
            try:
                departure = date.fromisoformat(str(raw)[:10])
            except ValueError:
                departure = None
    departure = st.date_input("Departure (optional)", value=departure)

    passport = docs.passport_status(
        destination=api_label,
        departure=departure if isinstance(departure, date) else None,
        user_key=USER_KEY,
    )
    st.subheader("Passport & trusted traveler")
    st.write(
        f"**{passport['passport_country']}** · expires **{passport['expires']}** · "
        f"{passport['blank_pages']} blank visa pages · "
        f"Global Entry until **{passport['global_entry_expires']}** · "
        f"TSA PreCheck: {'yes' if passport['tsa_precheck'] else 'not yet (recommended)'}"
    )
    if passport["ok"] and not passport["issues"]:
        st.success("Passport profile looks travel-ready for this destination window.")
    for issue in passport["issues"]:
        st.warning(issue)

    st.subheader("If / then — US passport")
    st.caption("Personal checklist, not legal advice.")
    for item in docs.entry_conditionals(api_label):
        st.markdown(f"- {item}")

    entry = docs.entry_requirements(api_label)
    st.subheader(f"Entry requirements — {api_label}")
    st.caption(f"Status: {entry['status']}")
    if entry.get("entry"):
        st.markdown(f"**{entry['entry']['title']}**")
        st.write(entry["entry"]["body"][:4000])
    else:
        st.info("No live entry text available — check the official link below.")

    st.subheader("Vaccinations & health")
    if entry.get("health"):
        st.write(entry["health"]["body"][:4000])
    else:
        st.info("No live health advisory text cached yet.")

    st.subheader("Embassy / consulate")
    if entry.get("embassy"):
        st.write(entry["embassy"]["body"][:4000])
    else:
        st.info("No embassy block returned.")

    for name, url in (entry.get("links") or {}).items():
        st.markdown(f"- [{name}]({url})")

    st.subheader("Major cities / regions to review")
    cities = docs.major_cities(api_label)
    if cities:
        for city in cities:
            st.markdown(f"- {city}")
    else:
        st.caption("No seeded city list for this label yet.")

    st.subheader("Social safety (scams / street)")
    render_social_safety(load_social_for(api_label, ATLAS_DB_PATH))


if __name__ == "__main__":
    main()
