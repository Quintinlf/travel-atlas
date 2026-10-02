"""Today dashboard — What should I do today for my active committed trip?"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_TRAVEL_ROOT = Path(__file__).parent.parent
if str(_TRAVEL_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRAVEL_ROOT))

from travel_atlas.database import AtlasDatabase
from travel_atlas.knowledge_loader import load_bundled_knowledge
from travel_atlas.repository import AtlasRepository
from travel_atlas.services import (
    DestinationItineraryService,
    ItineraryService,
    KnowledgeService,
    LearningQueueService,
    LifecycleService,
    ModeService,
    PhotoService,
    PinService,
    PreferencesService,
    PrepService,
    ReservationService,
    SeasonalContextService,
    TodayService,
    TripPlanService,
)

ATLAS_DB_PATH = _TRAVEL_ROOT / "atlas.db"
PIN_DB_PATH = _TRAVEL_ROOT / "travel_pins.db"
USER_KEY = "local-default"
_CACHE_VERSION = "2026-08-05-today-v2"


def _prep_bar(pct: float) -> str:
    filled = max(0, min(10, int(round(pct / 10))))
    return "█" * filled + "░" * (10 - filled)


@st.cache_resource
def get_today_services():
    _ = _CACHE_VERSION
    database = AtlasDatabase(ATLAS_DB_PATH)
    database.migrate()
    repository = AtlasRepository(database)
    load_bundled_knowledge(repository)
    pin_service = PinService(PIN_DB_PATH, atlas_database_path=ATLAS_DB_PATH)
    itinerary = ItineraryService(pin_service)
    destination_itinerary = DestinationItineraryService(pin_service, itinerary)
    knowledge = KnowledgeService(repository)
    seasonal = SeasonalContextService(repository)
    trip_service = TripPlanService(
        repository, destination_itinerary, knowledge, seasonal
    )
    lifecycle = LifecycleService(repository)
    prep = PrepService(repository)
    learning = LearningQueueService(repository)
    reservations = ReservationService(repository)
    photos = PhotoService(repository)
    today = TodayService(
        repository, trip_service, lifecycle, prep, learning, reservations, photos
    )
    preferences = PreferencesService(repository)
    mode = ModeService(repository, trip_service, lifecycle)
    return today, preferences, trip_service, mode, reservations


def main() -> None:
    st.set_page_config(page_title="Today", layout="wide")
    today_service, preferences, trip_service, mode_service, _reservations = (
        get_today_services()
    )

    st.title("Today")
    st.caption("What should I do today for my active committed trip?")

    mode_state = mode_service.resolve(USER_KEY)
    if not mode_state["today_eligible"]:
        st.info(
            mode_state.get("mode")
            and "Today unlocks for an active committed trip "
            "(hotel or flight reserved + Active Trip focus)."
        )
        st.markdown(
            "Use **Command Center** to reserve a hotel/flight and set Active Trip focus, "
            "or browse in **Destination Atlas** (Research mode)."
        )
        if mode_state["planning_trips"]:
            st.caption(
                f"{len(mode_state['planning_trips'])} trip(s) still in planning — "
                "they do not drive Today until committed."
            )
        return

    prefs = preferences.get_preferences(USER_KEY)
    dashboard = today_service.build(interests=list(prefs.get("interests") or []))

    if not dashboard.get("has_trip"):
        st.info(dashboard.get("message") or "No active committed trip yet.")
        return

    life = dashboard["lifecycle"]
    st.subheader(dashboard.get("trip_name") or "Active Trip")
    st.markdown(f"### {dashboard['headline']}")
    st.caption(
        f"Stage: **{life['stage'].replace('_', ' ').title()}** · "
        f"Band: {life.get('prep_band')} · "
        f"Destination: {dashboard['destination_label']}"
    )

    score = float(dashboard.get("prep_score") or 0)
    st.markdown(f"**Preparation score** `{_prep_bar(score)}` {score:.0f}%")
    st.caption(f"Estimated time today: ~{dashboard.get('estimated_minutes', 0)} minutes")

    opening = dashboard.get("opening_soon") or []
    if opening:
        st.header("Reservations opening soon")
        for item in opening:
            st.markdown(f"- {item['headline']}: **{item['title']}**")

    res_cards = dashboard.get("reservations") or []
    pending = [c for c in res_cards if c["status"] in ("book_now", "available_soon")]
    if pending:
        st.header("Reservations")
        for card in pending[:5]:
            st.markdown(f"- **{card['title']}** — {card['action_label']}")

    st.header("Today's mission")
    completed = set(dashboard.get("completed_mission_keys") or [])
    for mission in dashboard.get("missions") or []:
        key = mission.get("key") or mission.get("title")
        done = key in completed
        label = mission.get("title") or key
        minutes = mission.get("minutes") or 3
        if st.checkbox(f"{label} (~{minutes}m)", value=done, key=f"m-{key}"):
            if not done and key:
                today_service.complete_mission(dashboard["trip_id"], key)
                st.rerun()

    st.header("Language")
    lesson = dashboard.get("lesson") or {}
    st.markdown(
        f"**{lesson.get('title', 'Lesson')}** · "
        f"~{lesson.get('estimated_minutes', 0)} minutes"
    )
    for item in lesson.get("items") or []:
        st.markdown(f"- {item}")

    st.header("This week")
    st.markdown(" · ".join(dashboard.get("this_week") or []))

    if dashboard.get("photo_count"):
        st.caption(f"{dashboard['photo_count']} photo(s) on this trip")


if __name__ == "__main__":
    main()
