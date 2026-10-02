"""Shared trip → country/region helpers for Culture / Language / Health / lodging."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import streamlit as st

from travel_atlas.services.traveler_docs import expand_trip_regions

WEST_EUROPE_NAME_HINT = "west europe"


def preferred_trip(
    trips: Sequence[Mapping[str, Any]],
    *,
    session_trip_id: str | None = None,
) -> dict[str, Any] | None:
    """Pick the trip to open: explicit session id, else West Europe, else first."""
    if not trips:
        return None
    by_id = {str(t.get("id")): dict(t) for t in trips if t.get("id")}
    if session_trip_id and str(session_trip_id) in by_id:
        return by_id[str(session_trip_id)]
    for trip in trips:
        name = str(trip.get("name") or "").casefold()
        if WEST_EUROPE_NAME_HINT in name:
            return dict(trip)
    return dict(trips[0])


def preferred_trip_index(
    trips: Sequence[Mapping[str, Any]],
    *,
    session_trip_id: str | None = None,
) -> int:
    chosen = preferred_trip(trips, session_trip_id=session_trip_id)
    if not chosen:
        return 0
    chosen_id = str(chosen.get("id") or "")
    for index, trip in enumerate(trips):
        if str(trip.get("id") or "") == chosen_id:
            return index
    return 0


def trip_destination_labels(trip: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    for dest in trip.get("destinations") or []:
        raw = (dest.get("destination_label") or dest.get("label") or "").strip()
        if not raw:
            continue
        labels.append(raw.replace(" (UK)", ""))
    return labels


def trip_regions(trip: dict[str, Any]) -> list[str]:
    labels = trip_destination_labels(trip)
    expanded = expand_trip_regions(labels) if labels else []
    return expanded or labels


def select_trip(
    trip_service: Any,
    *,
    key: str = "shared_trip_id",
    kind: str = "trip",
) -> dict[str, Any] | None:
    """Trip-first selector; syncs with Command Center session keys."""
    trips = trip_service.list_trips(kind=kind)
    if not trips:
        st.warning("Create a trip first (Command Center → Create trip).")
        return None
    session_id = st.session_state.get("cc_selected_trip_id") or st.session_state.get(
        "active_trip_id"
    )
    ids = [t["id"] for t in trips]
    index = preferred_trip_index(trips, session_trip_id=session_id)
    trip_id = st.selectbox(
        "Trip",
        ids,
        index=index,
        key=key,
        format_func=lambda tid: next(t["name"] for t in trips if t["id"] == tid),
    )
    st.session_state["cc_selected_trip_id"] = trip_id
    st.session_state["active_trip_id"] = trip_id
    return trip_service.get_trip(trip_id)


def select_trip_region(
    trip: dict[str, Any],
    *,
    key: str = "shared_region",
    label: str = "Country / region on this trip",
) -> str | None:
    regions = trip_regions(trip)
    if not regions:
        st.info("This trip has no destinations yet.")
        return None
    return st.selectbox(label, regions, key=key)
