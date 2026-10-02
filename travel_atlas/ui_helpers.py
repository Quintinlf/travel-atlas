"""Shared Streamlit helpers: pin refresh, social safety, substance thumbs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from travel_atlas.services.social_safety_service import SocialSafetyService


def render_pin_refresh_button(
    pin_service: Any,
    takeout_dir: Path,
    geocoded_csv: Path,
    *,
    cache_clear_fns: list | None = None,
) -> None:
    st.caption(
        "Pins come from Google Takeout (Saved). There is no live Saved-Places API — "
        "re-export Takeout into the folder below, then refresh."
    )
    st.code(str(takeout_dir), language=None)
    if st.button("Refresh Google pins from Takeout", key="refresh-takeout-pins"):
        stats = pin_service.sync_pipeline(
            takeout_dir, geocoded_csv, force_refresh=True
        )
        # CID fill is slow (HTTP per pin) — only on explicit refresh, not page load.
        cid_stats = pin_service.fill_missing_coordinates_from_cid(sleep_s=0.5)
        if cid_stats.get("updated"):
            backfill = pin_service.backfill_places()
            clusters = pin_service.recluster()
        else:
            backfill = {"updated": 0}
            clusters = stats.get("clusters", 0)
        for fn in cache_clear_fns or []:
            try:
                fn.clear()
            except Exception:
                pass
        st.success(
            f"Synced — inserted {stats.get('inserted', 0)}, "
            f"updated {stats.get('updated', 0)}, "
            f"coords fixed {stats.get('coordinates_updated', 0)}, "
            f"CID filled {cid_stats.get('updated', 0)}, "
            f"places labeled {backfill.get('updated', 0)}, "
            f"clusters {clusters}"
        )
        st.rerun()


def render_social_safety(block: dict[str, Any]) -> None:
    st.caption(block.get("disclaimer") or "")
    if block.get("lgbt_climate"):
        st.markdown(f"**LGBT / bi climate** — {block['lgbt_climate']}")
    if block.get("gay_scene"):
        st.markdown(f"**Gay / queer scene** — {block['gay_scene']}")
    if block.get("straight_scene"):
        st.markdown(f"**Straight / mixed scene** — {block['straight_scene']}")
    if block.get("bring_someone_back"):
        st.markdown(f"**Bringing someone back** — {block['bring_someone_back']}")
    if block.get("hookup_scams"):
        st.markdown("**Hookup-related scams**")
        for item in block["hookup_scams"]:
            st.markdown(f"- {item}")
    if block.get("common_scams"):
        st.markdown("**Common tourist scams**")
        for item in block["common_scams"]:
            st.markdown(f"- {item}")
    if block.get("street_crime"):
        st.markdown(f"**Street crime / weapons context** — {block['street_crime']}")
    if block.get("stay_safe"):
        st.markdown(f"**Stay safe** (emergency: {block.get('emergency') or '112'})")
        for item in block["stay_safe"]:
            st.markdown(f"- {item}")
    note = block.get("state_dept_note")
    if note:
        with st.expander(f"State Dept — {note.get('title') or 'advisory'}"):
            st.write(note.get("body"))


def render_substance_items(items: list[dict[str, Any]], *, key_prefix: str) -> None:
    from travel_atlas.services.substance_images import resolve_substance_image

    for idx, item in enumerate(items):
        cols = st.columns([1, 3])
        with cols[0]:
            src, caption = resolve_substance_image(item)
            if src:
                st.image(src, use_container_width=True)
                st.caption(caption)
            else:
                st.caption("No photo")
        with cols[1]:
            st.markdown(f"**{item.get('name')}** — {item.get('notes')}")
        _ = key_prefix, idx


def load_social_for(destination: str, atlas_db: Path) -> dict[str, Any]:
    from travel_atlas.providers.state_dept import StateDeptSafetyProvider

    return SocialSafetyService(
        StateDeptSafetyProvider(cache_db_path=atlas_db)
    ).for_destination(destination)
