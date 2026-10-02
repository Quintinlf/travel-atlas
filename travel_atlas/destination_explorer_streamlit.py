"""Streamlit entrypoint for trip-first Atlas navigation."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import streamlit as st

_TRAVEL_ROOT = Path(__file__).parent.parent
if str(_TRAVEL_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRAVEL_ROOT))

from src_phase1.geo_grouping import destination_matches, ireland_leg_caption, trip_pin_stats
from src_phase1.models import SavedLocation
from src_phase1.places_api import place_photo_url, resolve_place_media
from travel_atlas.database import AtlasDatabase
from travel_atlas.knowledge_loader import load_bundled_knowledge
from travel_atlas.repository import AtlasRepository
from travel_atlas.services import (
    AnnotationService,
    DestinationItineraryService,
    DestinationService,
    ItineraryService,
    KnowledgeService,
    LanguageService,
    NotesService,
    PinService,
    SeasonalContextService,
    TripPlanService,
)
from travel_atlas.services.activity_finder import ActivityFinder
from travel_atlas.services.region_map import region_map_image_url
from travel_atlas.services.traveler_docs import CITY_COORDS, MAJOR_CITIES
from travel_atlas.services.trip_context import select_trip, select_trip_region, trip_regions
from travel_atlas.ui_helpers import (
    load_social_for,
    render_pin_refresh_button,
    render_social_safety,
)

ATLAS_DB_PATH = _TRAVEL_ROOT / "atlas.db"
PIN_DB_PATH = _TRAVEL_ROOT / "travel_pins.db"
LOCAL_SAVED_TAKEOUT_PATH = _TRAVEL_ROOT / "Takeout" / "Saved"
GEOCODED_WANT_TO_GO_PATH = LOCAL_SAVED_TAKEOUT_PATH / "Want to go_geocoded.csv"
USER_KEY = "local-default"

PERSONAL_SECTIONS = [
    ("wellness_substances", "local_drug_laws", "Local drug laws"),
    ("wellness_substances", "pharmacy_medicine", "Pharmacy & medicine"),
    ("microbiome", "food_water_safety", "Food & water safety"),
    ("beliefs_spirituality", "religious_practices", "Religious practices"),
    ("beliefs_spirituality", "folk_beliefs", "Folk beliefs"),
]

_CACHE_VERSION = "2026-08-10-trip-atlas-v1"


@st.cache_resource
def get_services():
    _ = _CACHE_VERSION
    database = AtlasDatabase(ATLAS_DB_PATH)
    database.migrate()
    repository = AtlasRepository(database)
    load_bundled_knowledge(repository)
    pin_service = PinService(PIN_DB_PATH, atlas_database_path=ATLAS_DB_PATH)
    pin_service.sync_pipeline(LOCAL_SAVED_TAKEOUT_PATH, GEOCODED_WANT_TO_GO_PATH)
    knowledge_service = KnowledgeService(repository)
    language_service = LanguageService(repository, pin_service, knowledge_service)
    notes_service = NotesService(repository)
    itinerary_service = ItineraryService(pin_service)
    destination_itinerary = DestinationItineraryService(pin_service, itinerary_service)
    seasonal_context_service = SeasonalContextService(repository)
    destination_service = DestinationService(
        repository,
        pin_service,
        knowledge_service,
        language_service,
        notes_service,
        destination_itinerary,
        seasonal_context_service,
    )
    annotation_service = AnnotationService(repository)
    trip_service = TripPlanService(
        repository, destination_itinerary, knowledge_service, seasonal_context_service
    )
    return (
        repository,
        pin_service,
        destination_service,
        annotation_service,
        notes_service,
        trip_service,
    )


def _render_place_card(
    pin: SavedLocation,
    *,
    pin_service: PinService,
    annotation_service: AnnotationService,
    area_id: str | None,
) -> None:
    media = resolve_place_media(
        pin,
        source_hash=pin_service.source_hash(pin),
        atlas_db_path=ATLAS_DB_PATH,
    )
    photo_url = media.photo_url or (
        place_photo_url(media.photo_name) if media.photo_name else None
    )
    cols = st.columns([1, 3])
    with cols[0]:
        if photo_url:
            st.image(photo_url, use_container_width=True)
            if media.attribution:
                st.caption(media.attribution)
            if media.is_approximate():
                st.caption(":grey[Nearby view, may not be this exact place]")
            if media.file_page_url:
                st.caption(f"[File details]({media.file_page_url})")
        else:
            st.caption("No free Commons photo — open Maps or add a note")
    with cols[1]:
        st.markdown(f"**{pin.name}**")
        location = ", ".join(
            part for part in [pin.city, pin.region, pin.country] if part
        ) or "Location unknown"
        st.caption(location)
        if pin.notes:
            st.write(pin.notes)
        personal_note = annotation_service.get_pin_note(pin.id)
        if personal_note:
            st.info(personal_note)
        st.markdown(f"[Open in Google Maps]({media.maps_url})")
        with st.expander("Add your note"):
            note = st.text_area("Personal note", value=personal_note, key=f"note-{pin.id}")
            if st.button("Save note", key=f"save-note-{pin.id}"):
                annotation_service.save_pin_note(pin.id, note)
                st.success("Saved")


def _kind_for_region(region: str, trip_destinations: list[dict]) -> tuple[str, str]:
    for dest in trip_destinations:
        label = (dest.get("destination_label") or dest.get("label") or "").replace(
            " (UK)", ""
        )
        if label.lower() == region.lower():
            return (
                dest.get("destination_kind") or dest.get("kind") or "country",
                label,
            )
    if region in {"England", "Scotland", "Wales", "Northern Ireland"}:
        return "uk_nation", region
    return "country", region


def _render_destination_report(
    report: dict,
    *,
    pin_service: PinService,
    annotation_service: AnnotationService,
    notes_service: NotesService,
    selected_label: str,
) -> None:
    st.subheader(report["display_name"])
    st.caption(f"{report['pin_count']} saved places")

    tabs = st.tabs(
        [
            "Overview",
            "Places",
            "Activities",
            "Social & safety",
            "Atlas context",
            "Personal notes",
            "Itinerary",
            "Seasonal",
        ]
    )
    (
        overview_tab,
        places_tab,
        activities_tab,
        social_tab,
        atlas_tab,
        personal_tab,
        itinerary_tab,
        seasonal_tab,
    ) = tabs

    with overview_tab:
        st.metric("Saved places", report["pin_count"])
        st.metric("Cities / areas", len(report["pins_by_city"]))

    with places_tab:
        for city, pins in report["pins_by_city"].items():
            st.markdown(f"### {city}")
            for pin in pins:
                _render_place_card(
                    pin,
                    pin_service=pin_service,
                    annotation_service=annotation_service,
                    area_id=report["area_id"],
                )

    with activities_tab:
        st.caption(
            "Travel rhythm — hikes, light gym, drop-in martial arts / dance. "
            "Not a full home training load."
        )
        city = st.selectbox(
            "City focus",
            list(report["pins_by_city"].keys()) or [selected_label],
            key=f"act-city-{selected_label}",
        )
        if st.button("Find activities", key=f"find-act-{selected_label}"):
            hits = ActivityFinder().search(
                city=city, country=selected_label, limit_per_kind=3
            )
            st.session_state[f"acts-{selected_label}"] = hits
        for hit in st.session_state.get(f"acts-{selected_label}") or []:
            st.markdown(
                f"- **{hit.name}** ({hit.kind.replace('_', ' ')}) · "
                f"[Maps]({hit.maps_url}) · {hit.source}"
            )

    with social_tab:
        render_social_safety(load_social_for(selected_label, ATLAS_DB_PATH))

    with atlas_tab:
        claims = report["atlas_context"]["claims_by_category"]
        if claims:
            for category, items in claims.items():
                with st.expander(category, expanded=True):
                    for claim in items:
                        st.markdown(f"**{claim['value']['title']}**")
                        st.write(claim["value"]["body"])
        else:
            st.info("No bundled Atlas claims for this destination yet.")

    with personal_tab:
        if not report["area_id"]:
            st.info("Add bundled or planned area metadata to save personal notes here.")
        for category_key, topic_key, title in PERSONAL_SECTIONS:
            with st.expander(title):
                existing = next(
                    (
                        claim
                        for claim in report["personal_claims"]
                        if claim["category_key"] == category_key
                        and claim["topic_key"] == topic_key
                    ),
                    None,
                )
                body = st.text_area(
                    title,
                    value=existing["value"]["body"] if existing else "",
                    key=f"personal-{selected_label}-{category_key}-{topic_key}",
                )
                if st.button(
                    f"Save {title}",
                    key=f"save-{selected_label}-{category_key}-{topic_key}",
                ):
                    notes_service.save_personal_note(
                        area_id=report["area_id"],
                        category_key=category_key,
                        topic_key=topic_key,
                        title=title,
                        body=body,
                    )
                    st.success("Saved")

    with itinerary_tab:
        st.write(report["itinerary"]["message"])
        for day in report["itinerary"]["days"]:
            heading = f"Day {day['day']}" + (
                f" — {day['date']}" if day.get("date") else ""
            )
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
                        st.markdown(f"- {stop['name']}")

    with seasonal_tab:
        seasonal_context = report.get("seasonal_context")
        if not seasonal_context:
            st.info("No seasonal context available for this destination yet.")
        else:
            st.markdown("### Sky during your visit")
            for event in seasonal_context["anchor_sky_events"]:
                st.markdown(f"- **{event['title']}** — {event['description']}")
            if seasonal_context["landmark_sky_events"]:
                st.markdown("### Notable sky events during your trip")
                for event in seasonal_context["landmark_sky_events"]:
                    st.markdown(f"- **{event['title']}** — {event['description']}")
            st.markdown("### Seasonal & cultural context")
            if seasonal_context["seasonal_claims"]:
                for claim in seasonal_context["seasonal_claims"]:
                    st.markdown(f"**{claim['value']['title']}**")
                    st.write(claim["value"]["body"])
            else:
                st.info(
                    "No bundled seasonal knowledge matches this destination and date yet."
                )


def main() -> None:
    st.set_page_config(page_title="Destination Atlas", layout="wide")
    (
        repository,
        pin_service,
        destination_service,
        annotation_service,
        notes_service,
        trip_service,
    ) = get_services()

    st.title("Destination Atlas")
    st.caption("Trip overview first — places, activities, and safety by region.")

    with st.sidebar:
        render_pin_refresh_button(
            pin_service,
            LOCAL_SAVED_TAKEOUT_PATH,
            GEOCODED_WANT_TO_GO_PATH,
            cache_clear_fns=[get_services],
        )
        with st.expander("Add a planned destination"):
            planned_name = st.text_input("Country, UK nation, or US state")
            planned_kind = st.selectbox("Type", ["country", "uk_nation", "us_state"])
            if st.button("Add destination"):
                slug = planned_name.strip().lower().replace(" ", "-")
                if planned_kind == "us_state":
                    area_type = "region"
                    parent_id = "country-us"
                elif planned_kind == "uk_nation":
                    area_type = "region"
                    parent_id = "country-united-kingdom"
                else:
                    area_type = "country"
                    parent_id = None
                repository.upsert_planned_area(
                    area_id=f"{area_type}-{slug}",
                    name=planned_name.strip(),
                    area_type=area_type,
                    parent_id=parent_id,
                )
                st.success(f"Added {planned_name}")

    scope = st.radio(
        "Scope",
        ["This trip", "Research any destination"],
        horizontal=True,
        key="atlas_scope",
    )

    visit_date = st.sidebar.date_input("When are you visiting?", value=date.today())

    if scope == "This trip":
        trip = select_trip(trip_service, key="atlas_trip_id")
        if not trip:
            return
        regions = trip_regions(trip)
        all_pins = pin_service.list_pins()
        trip_pins = []
        for dest in trip.get("destinations") or []:
            kind = dest.get("destination_kind") or dest.get("kind") or "country"
            label = (dest.get("destination_label") or dest.get("label") or "").replace(
                " (UK)", ""
            )
            trip_pins.extend(
                p for p in all_pins if destination_matches(p, kind, label)
            )
        stats = trip_pin_stats(trip_pins)
        st.subheader(trip["name"])
        st.write(
            f"**Legs:** {', '.join(regions) or '—'} · "
            f"**{len(trip_pins)}** pins across the trip"
        )
        if stats.get("by_destination"):
            st.json(stats["by_destination"])
        ireland_n = (stats.get("by_destination") or {}).get("Ireland") or 0
        if ireland_n or any(
            (d.get("destination_label") or d.get("label") or "").lower() in {"ireland", "republic of ireland"}
            for d in (trip.get("destinations") or [])
        ):
            st.caption(ireland_leg_caption(ireland_n))

        st.subheader("Major cities per country / region")
        if regions:
            city_region = st.select_slider(
                "Trip leg",
                options=regions,
                value=regions[0],
                key="atlas-cities-slider",
            )
            seeded = list(MAJOR_CITIES.get(city_region, []))
            coords = [CITY_COORDS[c] for c in seeded if c in CITY_COORDS]
            overview = region_map_image_url(coords)
            if overview:
                st.image(
                    overview,
                    caption=f"Major cities — {city_region}",
                    use_container_width=True,
                )
            if seeded:
                for city in seeded:
                    st.markdown(f"- {city}")
            else:
                st.caption("No seeded city list for this leg yet.")

        region = select_trip_region(trip, key="atlas_region")
        if not region:
            return
        kind, label = _kind_for_region(region, trip.get("destinations") or [])
        report = destination_service.get_destination_report(
            destination_kind=kind,
            destination_label_value=label,
            user_key=USER_KEY,
            start_date=visit_date,
        )
        _render_destination_report(
            report,
            pin_service=pin_service,
            annotation_service=annotation_service,
            notes_service=notes_service,
            selected_label=label,
        )
        return

    destinations = destination_service.list_destinations()
    if not destinations:
        st.warning("No destinations yet. Import pins or add a planned destination.")
        return
    labels = [f"{item['display_name']} ({item['pin_count']})" for item in destinations]
    selected_index = st.selectbox(
        "Choose a destination",
        range(len(destinations)),
        format_func=lambda index: labels[index],
    )
    selected = destinations[selected_index]
    report = destination_service.get_destination_report(
        destination_kind=selected["kind"],
        destination_label_value=selected["label"],
        user_key=USER_KEY,
        start_date=visit_date,
    )
    _render_destination_report(
        report,
        pin_service=pin_service,
        annotation_service=annotation_service,
        notes_service=notes_service,
        selected_label=selected["label"],
    )


if __name__ == "__main__":
    main()
