"""Culture segment — trip-first, substances with photos, social safety."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_TRAVEL_ROOT = Path(__file__).parent.parent
if str(_TRAVEL_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRAVEL_ROOT))

from travel_atlas.destination_explorer_streamlit import ATLAS_DB_PATH, get_services
from travel_atlas.providers.state_dept import StateDeptSafetyProvider
from travel_atlas.services.substances_service import SubstancesService
from travel_atlas.services.trip_context import select_trip, select_trip_region
from travel_atlas.ui_helpers import (
    load_social_for,
    render_social_safety,
    render_substance_items,
)


def _match_destination(destinations: list[dict], region: str) -> dict | None:
    region_l = region.lower()
    for item in destinations:
        label = (item.get("label") or "").replace(" (UK)", "")
        display = item.get("display_name") or label
        if label.lower() == region_l or display.lower() == region_l:
            return item
        if region_l in display.lower() or region_l in label.lower():
            return item
    return None


def main() -> None:
    st.set_page_config(page_title="Culture", layout="wide")
    (
        _repository,
        _pin_service,
        destination_service,
        _annotation,
        notes_service,
        trip_service,
    ) = get_services()

    st.title("Culture")
    st.caption(
        "Trip-first culture, spirits/plants, and social safety notes. Not legal advice."
    )

    trip = select_trip(trip_service, key="culture_trip_id")
    destinations = destination_service.list_destinations()

    mode = st.radio(
        "Scope",
        ["This trip", "Research any destination"],
        horizontal=True,
        key="culture_scope",
    )

    selected = None
    region_label = None
    if mode == "This trip":
        if not trip:
            return
        region_label = select_trip_region(trip, key="culture_region")
        if not region_label:
            return
        selected = _match_destination(destinations, region_label) or {
            "kind": "country",
            "label": region_label,
            "display_name": region_label,
        }
    else:
        if not destinations:
            st.warning("No atlas destinations yet — use a trip leg instead.")
            return
        labels = [item["display_name"] for item in destinations]
        pick = st.selectbox("Destination", labels, key="culture_research_dest")
        selected = next(item for item in destinations if item["display_name"] == pick)
        region_label = selected["label"]

    report = destination_service.get_destination_report(
        destination_kind=selected["kind"],
        destination_label_value=selected["label"],
        user_key="local-default",
    )
    claims = report["atlas_context"]["claims_by_category"]
    culture_claims = {
        key: value
        for key, value in claims.items()
        if key.lower() in {"culture", "food", "customs", "etiquette"}
        or "cultur" in key.lower()
        or "food" in key.lower()
    }
    st.subheader(f"Atlas culture claims — {region_label}")
    if culture_claims:
        for category, items in culture_claims.items():
            with st.expander(category, expanded=True):
                for claim in items:
                    st.markdown(f"**{claim['value']['title']}**")
                    st.write(claim["value"]["body"])
    else:
        st.info("No bundled culture claims for this destination yet.")

    substances = SubstancesService(
        StateDeptSafetyProvider(cache_db_path=_TRAVEL_ROOT / "atlas.db")
    ).for_destination(selected["label"])
    st.subheader("Regional spirits & traditional plants")
    st.caption(substances.get("disclaimer") or "")
    if substances.get("psychoactives"):
        st.markdown("**Historic / legal psychoactives (research notes)**")
        render_substance_items(
            substances["psychoactives"], key_prefix=f"psy-{region_label}"
        )
    if substances.get("spirits"):
        st.markdown("**Regional spirits**")
        render_substance_items(substances["spirits"], key_prefix=f"spi-{region_label}")
    if substances.get("state_dept_local_laws"):
        with st.expander("State Dept — local laws (live)"):
            st.write(substances["state_dept_local_laws"].get("body"))
    if substances.get("historical_caution"):
        st.warning(substances["historical_caution"])

    st.subheader("Social scene & staying safe")
    render_social_safety(load_social_for(region_label or selected["label"], ATLAS_DB_PATH))

    area_id = report.get("area_id")
    if area_id:
        st.subheader("Your culture notes")
        existing = next(
            (
                claim
                for claim in report.get("personal_claims") or []
                if claim.get("topic_key") == "local_drug_laws"
            ),
            None,
        )
        body = st.text_area(
            "Personal notes",
            value=existing["value"]["body"] if existing else "",
            key="culture-personal",
        )
        if st.button("Save personal note"):
            notes_service.save_personal_note(
                area_id=area_id,
                category_key="wellness_substances",
                topic_key="local_drug_laws",
                title="Local drug laws",
                body=body,
            )
            st.success("Saved")


if __name__ == "__main__":
    main()
