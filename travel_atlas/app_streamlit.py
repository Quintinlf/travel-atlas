"""Streamlit entrypoint for the personalized, offline-first Travel Atlas."""

from __future__ import annotations

import html
import sys
from datetime import date
from pathlib import Path

import folium
import streamlit as st
from streamlit_folium import st_folium

_TRAVEL_ROOT = Path(__file__).parent.parent
if str(_TRAVEL_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRAVEL_ROOT))

from src_phase1.geo_grouping import WEST_EUROPE_FIT_BOUNDS, top_level_destination, world_map_view
from src_phase1.map_media import pin_popup_image_html
from travel_atlas.database import AtlasDatabase
from travel_atlas.knowledge_loader import load_bundled_knowledge
from travel_atlas.repository import AtlasRepository
from travel_atlas.services import (
    ItineraryService,
    KnowledgeService,
    LanguageService,
    NotesService,
    PinService,
    PlanningService,
    PreferencesService,
    SeasonalContextService,
)

ATLAS_DB_PATH = _TRAVEL_ROOT / "atlas.db"
PIN_DB_PATH = _TRAVEL_ROOT / "travel_pins.db"
LOCAL_SAVED_TAKEOUT_PATH = _TRAVEL_ROOT / "Takeout" / "Saved"
GEOCODED_WANT_TO_GO_PATH = LOCAL_SAVED_TAKEOUT_PATH / "Want to go_geocoded.csv"
USER_KEY = "local-default"

_HEALTH_CHECKLIST = [
    "Confirm travel insurance covers medical care and evacuation for your itinerary.",
    "Carry a current medication list and keep prescriptions in original packaging.",
    "Check drinking-water guidance for the destination and pack a backup purification option if unsure.",
    "Save local emergency numbers and your embassy/consulate contact before you travel.",
    "Verify current vaccine and entry health requirements with a clinician and official sources.",
]


_CACHE_VERSION = "2026-07-26-seasonal-v1"


@st.cache_resource
def get_services() -> tuple[
    AtlasRepository,
    PinService,
    KnowledgeService,
    LanguageService,
    PreferencesService,
    ItineraryService,
    PlanningService,
    NotesService,
    SeasonalContextService,
]:
    _ = _CACHE_VERSION
    database = AtlasDatabase(ATLAS_DB_PATH)
    database.migrate()
    repository = AtlasRepository(database)
    load_bundled_knowledge(repository)
    pin_service = PinService(PIN_DB_PATH, atlas_database_path=ATLAS_DB_PATH)
    pin_service.sync_pipeline(LOCAL_SAVED_TAKEOUT_PATH, GEOCODED_WANT_TO_GO_PATH)
    knowledge_service = KnowledgeService(repository)
    language_service = LanguageService(repository, pin_service, knowledge_service)
    preferences_service = PreferencesService(repository)
    itinerary_service = ItineraryService(pin_service)
    planning_service = PlanningService(preferences_service)
    notes_service = NotesService(repository)
    seasonal_context_service = SeasonalContextService(repository)
    return (
        repository,
        pin_service,
        knowledge_service,
        language_service,
        preferences_service,
        itinerary_service,
        planning_service,
        notes_service,
        seasonal_context_service,
    )


def _render_claim(claim: dict) -> None:
    value = claim["value"]
    st.markdown(f"**{value['title']}**")
    st.write(value["body"])
    st.caption(
        f"Confidence: {claim['confidence'].title()} · "
        f"Source retrieved: {claim['retrieved_at'] or 'not recorded'}"
    )
    st.markdown(f"[{claim['source_title']} — {claim['publisher']}]({claim['source_url']})")


def _render_map(pins: list, knowledge_service: KnowledgeService) -> str | None:
    geo_pins = [pin for pin in pins if pin.latitude != 0 or pin.longitude != 0]
    if not geo_pins:
        st.info("Your imported pins have no coordinates to display on a map yet.")
        return None
    show_all = st.checkbox(
        "Show all pins worldwide",
        value=False,
        key="atlas-explorer-show-all-pins",
        help="Default camera is West Europe. Turn this on to include Kazakhstan, Japan, and other regions.",
    )
    coords = [(pin.latitude, pin.longitude) for pin in geo_pins]
    latitude, longitude, zoom, plot_coords = world_map_view(coords, show_all=show_all)
    plot_set = set(plot_coords)
    plot_pins = (
        geo_pins
        if show_all
        else [pin for pin in geo_pins if (pin.latitude, pin.longitude) in plot_set]
    )
    travel_map = folium.Map(
        location=[latitude, longitude], zoom_start=zoom, tiles="CartoDB positron"
    )
    if not show_all:
        travel_map.fit_bounds(list(WEST_EUROPE_FIT_BOUNDS))
    for pin in plot_pins[:10_000]:
        resolution = knowledge_service.resolve_pin(pin)
        status = "Atlas knowledge" if resolution.area_id else "Generic / uncovered"
        location = ", ".join(item for item in [pin.city, pin.country] if item)
        if not location and resolution.area_name:
            location = f"Detected: {resolution.area_name}"
        if not location:
            location = "Location not detected"
        popup = (
            f"<b>{html.escape(pin.name)}</b><br>"
            f"{html.escape(location)}<br>"
            f"Context: {html.escape(status)}<br>"
            f"Resolution: {html.escape(resolution.method)}"
            + pin_popup_image_html(pin)
        )
        folium.CircleMarker(
            location=[pin.latitude, pin.longitude],
            radius=5,
            color="#1565C0" if resolution.area_id else "#78909C",
            fill=True,
            fill_color="#1565C0" if resolution.area_id else "#78909C",
            fill_opacity=0.8,
            popup=folium.Popup(popup, max_width=280),
            tooltip=f"{pin.name}||{pin.id}",
        ).add_to(travel_map)
    clicked = st_folium(travel_map, height=520, use_container_width=True)
    tooltip = clicked.get("last_object_clicked_tooltip") if clicked else None
    if tooltip and "||" in tooltip:
        return tooltip.split("||", 1)[1]
    return tooltip


def _render_preferences(service: PreferencesService) -> None:
    preferences = service.get_preferences(USER_KEY)
    with st.sidebar.expander("Personalize learning", expanded=False):
        interests = st.multiselect(
            "Interests",
            ["market_food", "temple_spirituality", "museum_history", "nature_gardens"],
            default=preferences["interests"],
        )
        style = st.selectbox(
            "Travel style",
            ["balanced", "slow", "packed", "food_first"],
            index=["balanced", "slow", "packed", "food_first"].index(preferences["travel_style"]),
        )
        goals = st.multiselect(
            "Learning goals",
            ["practical phrases", "culture", "history", "food"],
            default=preferences["learning_goals"],
        )
        if st.button("Save preferences"):
            service.update_preferences(
                interests, style, {"wifi": False, "kitchen": False}, goals, USER_KEY
            )
            st.success("Saved locally in atlas.db.")


def _render_culture_tab(context: dict, lesson) -> None:
    culture_claims = {
        category: claims
        for category, claims in context["claims_by_category"].items()
        if category.lower() not in {"health & safety", "health"}
    }
    if culture_claims:
        for category, claims in culture_claims.items():
            with st.expander(category, expanded=True):
                for claim in claims:
                    _render_claim(claim)
    else:
        st.info(
            "This destination is not yet covered by the bundled Atlas corpus. "
            "Generic context is used without making location-specific claims."
        )
    st.markdown("**Related concepts:** " + ", ".join(lesson.explanation["related_concepts"]))


def _render_language_tab(lesson, nearby: list) -> None:
    st.write(lesson.context_text)
    for phrase in lesson.phrases:
        st.markdown(f"- **{phrase['phrase']}** — {phrase['translation']}")
    st.caption(f"Lesson source: {lesson.lesson_source}")
    if nearby:
        st.markdown("### Nearby saved places")
        st.write(", ".join(other.name for other in nearby))


def _render_health_tab(context: dict, planning_service: PlanningService, pin, resolution) -> None:
    health_claims = []
    for category, claims in context["claims_by_category"].items():
        if "health" in category.lower():
            health_claims.extend(claims)
    if health_claims:
        st.markdown("### Atlas health context")
        for claim in health_claims:
            _render_claim(claim)
    else:
        st.info(
            "No destination-specific Atlas health claims yet. "
            "Use the offline checklist and official links below."
        )
    st.markdown("### Offline travel-health checklist")
    for item in _HEALTH_CHECKLIST:
        st.markdown(f"- {item}")
    links = planning_service.health_reference_links(pin, resolution)
    st.markdown("### Official reference links (require internet)")
    st.markdown(f"- [CDC traveller destinations]({links['cdc']})")
    st.markdown(f"- [CDC destination search for {links['country']}]({links['cdc_search']})")
    st.markdown(f"- [WHO travel and health]({links['who']})")
    st.markdown(f"- [WHO search for {links['country']}]({links['who_search']})")
    st.caption(
        "Educational only — not medical advice. Verify current official and clinician guidance."
    )


def _render_itinerary_tab(day_plan: dict) -> None:
    st.write(day_plan["message"])
    for slot in ("morning", "afternoon", "evening"):
        stops = day_plan[slot]
        st.markdown(f"### {slot.title()}")
        if not stops:
            st.caption("No nearby saved place assigned to this slot yet.")
            continue
        for stop in stops:
            distance = stop["distance_km_from_anchor"]
            place = ", ".join(item for item in [stop["city"], stop["country"]] if item) or "location unknown"
            suffix = f" · {distance} km" if distance else " · anchor"
            st.markdown(f"- **{stop['name']}** — {place}{suffix}")
    if day_plan["optional"]:
        st.markdown("### Optional extras")
        st.write(", ".join(stop["name"] for stop in day_plan["optional"]))


def _render_sky_event(event: dict) -> None:
    st.markdown(f"- **{event['title']}** — {event['description']}")


def _render_seasonal_tab(
    seasonal_context_service: SeasonalContextService,
    notes_service: NotesService,
    pin,
    resolution,
) -> None:
    picked_date = st.date_input(
        "Visit date", value=st.session_state.get("seasonal_context_date", date.today()),
        key="seasonal_context_date",
    )
    context = seasonal_context_service.get_seasonal_context(
        area_id=resolution.area_id,
        start_date=picked_date,
        latitude=pin.latitude,
        longitude=pin.longitude,
    )

    st.markdown("### Sky on this date")
    if context["anchor_sky_events"]:
        for event in context["anchor_sky_events"]:
            _render_sky_event(event)
    else:
        st.caption("No coordinates available to compute sky events for this place.")

    if context["landmark_sky_events"]:
        st.markdown("### Notable sky events during your visit")
        for event in context["landmark_sky_events"]:
            _render_sky_event(event)

    st.markdown("### Seasonal & cultural context")
    if context["seasonal_claims"]:
        for claim in context["seasonal_claims"]:
            _render_claim(claim)
    else:
        st.info("No bundled seasonal knowledge matches this destination and date yet.")

    st.markdown("### Your seasonal notes")
    if context["personal_notes"]:
        for claim in context["personal_notes"]:
            st.markdown(f"**{claim['value']['title']}**")
            st.write(claim["value"]["body"])
    else:
        st.caption("No personal seasonal notes saved for this destination and date yet.")

    if resolution.area_id:
        with st.expander("Add a seasonal note for this date"):
            title = st.text_input("Title", key="seasonal-note-title")
            body = st.text_area("Note", key="seasonal-note-body")
            window_start = st.text_input(
                "Season starts (MM-DD)", value=picked_date.strftime("%m-%d"), key="seasonal-note-start"
            )
            window_end = st.text_input(
                "Season ends (MM-DD)", value=picked_date.strftime("%m-%d"), key="seasonal-note-end"
            )
            if st.button("Save seasonal note", key="save-seasonal-note"):
                notes_service.save_personal_note(
                    area_id=resolution.area_id,
                    category_key="history",
                    topic_key="seasonal_traditions",
                    title=title,
                    body=body,
                    season_start_month_day=window_start,
                    season_end_month_day=window_end,
                    season_label=title,
                )
                st.success("Saved locally in atlas.db.")


def _render_flights_hotels_tab(
    planning_service: PlanningService, pin, resolution, user_key: str
) -> None:
    links = planning_service.planning_links(pin, resolution)
    prefs = planning_service.accommodation_context(user_key)
    st.markdown(f"**Destination:** {links['destination']}")
    st.markdown("### Flights & stays (external search links)")
    st.markdown(f"- [Google Flights]({links['google_flights']})")
    st.markdown(f"- [Booking.com]({links['booking']})")
    st.markdown(f"- [Airbnb]({links['airbnb']})")
    st.caption("Links open in your browser. Nothing is booked or fetched by Travel Atlas.")
    st.markdown("### Your accommodation preferences")
    st.write(f"Travel style: **{prefs['travel_style']}**")
    accommodation = prefs["accommodation_preferences"] or {}
    if accommodation:
        for key, value in accommodation.items():
            st.markdown(f"- {key}: {value}")
    else:
        st.caption("No accommodation preferences saved yet — set them in the sidebar.")
    if prefs["interests"]:
        st.markdown("Interests: " + ", ".join(prefs["interests"]))


def main() -> None:
    st.set_page_config(page_title="Travel Atlas Explorer", page_icon="Atlas", layout="wide")
    try:
        (
            repository,
            pin_service,
            knowledge_service,
            language_service,
            preferences_service,
            itinerary_service,
            planning_service,
            notes_service,
            seasonal_context_service,
        ) = get_services()
    except RuntimeError as error:
        st.title("Travel Atlas Explorer")
        st.error(str(error))
        st.code("git lfs pull", language="bash")
        st.caption(
            "This restores the existing local database only; it does not upload or alter "
            "your Google Takeout data. If you do not have Git LFS access, re-import your "
            "Takeout archive using the Phase 1 dashboard."
        )
        return
    _render_preferences(preferences_service)
    pins = pin_service.list_pins()
    st.title("Travel Atlas Explorer")
    st.caption("Your saved places become a personal cultural and language-learning guide.")
    if pin_service.last_bootstrap and pin_service.last_bootstrap["inserted"]:
        st.success(
            f"Imported {pin_service.last_bootstrap['inserted']} saved places from "
            "your local Google Takeout Saved lists."
        )
    if pin_service.last_enrichment and pin_service.last_enrichment["updated"]:
        st.success(
            f"Applied coordinates to {pin_service.last_enrichment['updated']} saved places "
            f"from {GEOCODED_WANT_TO_GO_PATH.name} "
            f"({pin_service.last_enrichment['clusters']} geographic clusters)."
        )
    if pin_service.last_sync and pin_service.last_sync.get("places_backfilled"):
        st.success(
            f"Synced pipeline: backfilled {pin_service.last_sync['places_backfilled']} places "
            f"and rebuilt {pin_service.last_sync['clusters']} clusters."
        )
    if not pins:
        st.warning("No imported pins yet. Import Google Takeout data in the Phase 1 dashboard first.")
        return

    destination_keys = {top_level_destination(pin) for pin in pins}
    destinations_with_coverage = {
        top_level_destination(pin)
        for pin in pins
        if knowledge_service.resolve_pin(pin).area_id
    }
    no_coords_count = sum(1 for pin in pins if pin.latitude == 0 and pin.longitude == 0)
    clusters = pin_service.list_clusters()
    metric_one, metric_two, metric_three, metric_four = st.columns(4)
    metric_one.metric("Imported saved places", len(pins))
    metric_two.metric("Destinations", len(destination_keys))
    metric_three.metric("Destinations with Atlas coverage", len(destinations_with_coverage))
    metric_four.metric("Pins without coordinates", no_coords_count)
    if no_coords_count:
        st.caption(
            f"{no_coords_count} of your saved places have no coordinates because Google's "
            "Saved-list CSV export usually stores only a title and URL. They do not appear "
            "on the map, but they are fully available in the Place understanding tab, and "
            "many still resolve to a destination by name."
        )
    with st.sidebar.expander("Your personalized lesson queue", expanded=False):
        queued_lessons = language_service.personalized_lesson_queue(USER_KEY, limit=5)
        for queued_lesson in queued_lessons:
            st.markdown(f"**{queued_lesson.title}**")
            st.caption(queued_lesson.lesson_source)

    map_tab, place_tab, atlas_tab = st.tabs(
        ["Where are my places?", "Place understanding", "Atlas coverage"]
    )
    with map_tab:
        mappable = len(pins) - no_coords_count
        st.caption(
            f"Showing {mappable} of {len(pins)} saved places (the rest have no coordinates). "
            "Blue pins have bundled Atlas context. Gray pins still receive generic offline travel preparation. "
            "Select a pin, then open Place understanding for culture, language, health, itinerary, and stays."
        )
        clicked_id = _render_map(pins, knowledge_service)
        if clicked_id in {pin.id for pin in pins}:
            st.session_state["selected_pin_id"] = clicked_id

    selected_id = st.session_state.get("selected_pin_id", pins[0].id)
    with place_tab:
        selected_id = st.selectbox(
            "Choose a saved place",
            [pin.id for pin in pins],
            index=next((index for index, pin in enumerate(pins) if pin.id == selected_id), 0),
            format_func=lambda pin_id: next(
                f"{pin.name} — {pin.city or pin.country or 'location unknown'}"
                for pin in pins
                if pin.id == pin_id
            ),
        )
        st.session_state["selected_pin_id"] = selected_id
        pin = pin_service.get_pin_details(selected_id)
        if not pin:
            st.error("The selected pin could not be loaded.")
            return
        context = knowledge_service.get_context_for_pin(pin)
        classification = language_service.classify_pin(pin)
        lesson = language_service.generate_language_lesson([pin.id], USER_KEY)[0]
        resolution = context["resolution"]
        status = "Atlas knowledge" if resolution.area_id else "Generic offline travel knowledge"
        nearby = pin_service.nearby_pins(pin)
        day_plan = itinerary_service.suggest_day_plan(pin)
        st.subheader(pin.name)
        st.caption(f"{pin.city or 'Unknown city'}, {pin.country or 'Unknown country'} · {status}")

        st.info(
            "Culture, Language, Health & medical, and Itinerary now live as separate "
            "sidebar pages — open those segments directly instead of these pin tabs."
        )
        stays_tab, seasonal_tab = st.tabs(
            ["Flights & hotels", "Why this moment matters"]
        )
        with stays_tab:
            _render_flights_hotels_tab(planning_service, pin, resolution, USER_KEY)
        with seasonal_tab:
            _render_seasonal_tab(seasonal_context_service, notes_service, pin, resolution)

        with st.expander("Developer context", expanded=False):
            st.json(
                {
                    "pin": pin.name,
                    "resolved": resolution.area_name,
                    "resolution_method": resolution.method,
                    "resolution_confidence": resolution.confidence,
                    "classification": classification["tags"],
                    "evidence": classification["evidence"],
                    "knowledge_coverage": {
                        item["category_name"]: item["score"] for item in context["coverage"]
                    },
                    "lesson_source": lesson.lesson_source,
                    "day_plan_source": day_plan["source"],
                }
            )

    with atlas_tab:
        for area in repository.list_top_level_coverage():
            st.progress(
                area["overall_score"],
                text=f"{area['name']}: {area['overall_score']:.0%} configured coverage",
            )
            for child in area["children"]:
                child_score = (
                    sum(item["score"] for item in child["coverage"]) / len(child["coverage"])
                    if child["coverage"]
                    else 0.0
                )
                st.caption(f"{child['name']} ({child['area_type']}): {child_score:.0%}")
        st.caption(
            "Coverage is computed from reviewed, sourced claims. "
            "Child cities roll up under their parent country."
        )
    st.info(
        "Health entries are educational only. Verify current official and clinician guidance "
        "for your own itinerary."
    )


if __name__ == "__main__":
    main()
