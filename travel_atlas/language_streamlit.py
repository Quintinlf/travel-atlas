"""Language segment — trip-first phrase packs (no pin lessons)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st

_TRAVEL_ROOT = Path(__file__).parent.parent
if str(_TRAVEL_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRAVEL_ROOT))

from travel_atlas.destination_explorer_streamlit import get_services
from travel_atlas.services.trip_context import select_trip, select_trip_region, trip_regions

PACK_PATH = _TRAVEL_ROOT / "travel_atlas" / "data" / "west_europe_language_pack.json"

# Map trip regions → pack language ids
REGION_TO_LANG_IDS: dict[str, list[str]] = {
    "Scotland": ["gd"],
    "Ireland": ["ga"],
    "Wales": ["cy"],
    "England": [],  # English — pack has no EN starter
    "Northern Ireland": ["ga"],
    "France": ["fr"],
    "Spain": ["es"],
    "Portugal": ["pt"],
    "United Kingdom": ["gd", "cy"],
}


def main() -> None:
    st.set_page_config(page_title="Language", layout="wide")
    (_repo, _pins, _dest, _ann, _notes, trip_service) = get_services()

    st.title("Language")
    st.caption(
        "Trip-scoped starter phrases for your destinations. "
        "Open LinguaGraph for the full tutor UI."
    )
    st.link_button("Open LinguaGraph (localhost:3000)", "http://localhost:3000/")

    trip = select_trip(trip_service, key="language_trip_id")
    if not trip:
        return

    regions = trip_regions(trip)
    st.markdown(
        "**Trip legs:** " + (", ".join(regions) if regions else "(none)")
    )
    region = select_trip_region(
        trip,
        key="language_region",
        label="Country / region to practice",
    )
    if not region:
        return

    if not PACK_PATH.is_file():
        st.warning("Language pack file missing.")
        return

    pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
    langs = pack.get("languages") or []
    by_id = {item["id"]: item for item in langs}

    # Prefer languages matching this region; else all pack languages for the trip
    want_ids = REGION_TO_LANG_IDS.get(region, [])
    trip_ids: list[str] = []
    for r in regions:
        trip_ids.extend(REGION_TO_LANG_IDS.get(r, []))
    trip_ids = list(dict.fromkeys(trip_ids))

    candidates = [by_id[i] for i in want_ids if i in by_id]
    if not candidates:
        candidates = [by_id[i] for i in trip_ids if i in by_id]
    if not candidates:
        candidates = langs

    if region in {"England"} and not want_ids:
        st.info(
            "England is English-primary in this pack — pick another trip region "
            "for Gaelic/Welsh/French/Spanish/Portuguese starters, or open LinguaGraph."
        )

    names = [f"{item['name']} ({item['region']})" for item in candidates]
    pick = st.selectbox("Language", names, key="language_pick")
    selected = candidates[names.index(pick)]
    st.subheader(selected["name"])
    for phrase in selected.get("phrases") or []:
        st.markdown(f"- **{phrase['phrase']}** — {phrase['translation']}")

    with st.expander("All languages on this trip"):
        for lang_id in trip_ids:
            item = by_id.get(lang_id)
            if not item:
                continue
            st.markdown(f"**{item['name']}** ({item['region']})")
            for phrase in (item.get("phrases") or [])[:3]:
                st.markdown(f"- {phrase['phrase']} — {phrase['translation']}")


if __name__ == "__main__":
    main()
