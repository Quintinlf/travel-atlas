"""Travel Command Center — preparation workflow dashboard."""

from __future__ import annotations

import importlib
import sys
from datetime import date, timedelta
from pathlib import Path

import streamlit as st

_TRAVEL_ROOT = Path(__file__).parent.parent
if str(_TRAVEL_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRAVEL_ROOT))

# Streamlit can keep a stale traveler_docs / geo_grouping module across edits.
import src_phase1.geo_grouping as _geo_grouping_mod
import travel_atlas.providers.astrology as _astrology_mod
import travel_atlas.services.astro_helper as _astro_helper_mod
import travel_atlas.services.traveler_docs as _traveler_docs_mod
import travel_atlas.services.traveler_service as _traveler_service_mod
import travel_atlas.services.trip_map as _trip_map_mod

importlib.reload(_geo_grouping_mod)
importlib.reload(_traveler_docs_mod)
importlib.reload(_traveler_service_mod)
importlib.reload(_astrology_mod)
importlib.reload(_astro_helper_mod)
importlib.reload(_trip_map_mod)

TravelerDocsService = _traveler_docs_mod.TravelerDocsService
expand_trip_regions = _traveler_docs_mod.expand_trip_regions
TravelerService = _traveler_service_mod.TravelerService
chart_layers_for_traveler = _astro_helper_mod.chart_layers_for_traveler
destination_matches = _geo_grouping_mod.destination_matches
ireland_leg_caption = getattr(
    _geo_grouping_mod,
    "ireland_leg_caption",
    lambda n: (
        f"{n} pins in the Republic of Ireland. "
        "Northern Ireland is under the UK. "
        "Notes on the country-level Ireland pin are not extra venues."
    ),
)

from travel_atlas.database import AtlasDatabase
from travel_atlas.knowledge_loader import load_bundled_knowledge
from travel_atlas.planning import PlanningEngine
from travel_atlas.repository import AtlasRepository
from travel_atlas.services import (
    BudgetBoardService,
    DestinationItineraryService,
    FeedbackService,
    ItineraryService,
    KnowledgeService,
    LearningQueueService,
    LifecycleService,
    LogisticsService,
    ModeService,
    PhotoService,
    PinService,
    PlanningService,
    PreferencesService,
    PrepService,
    ReservationService,
    SeasonalContextService,
    TodayService,
    TripPlanService,
)
from travel_atlas.providers.state_dept import StateDeptSafetyProvider
from travel_atlas.services.checklist_templates import LIFECYCLE_STAGES
from travel_atlas.services.types import TripDefinition
from travel_atlas.nav_pages import page
from travel_atlas.services.trip_context import preferred_trip_index
from travel_atlas.ui_helpers import render_pin_refresh_button

ATLAS_DB_PATH = _TRAVEL_ROOT / "atlas.db"
PIN_DB_PATH = _TRAVEL_ROOT / "travel_pins.db"
LOCAL_SAVED_TAKEOUT_PATH = _TRAVEL_ROOT / "Takeout" / "Saved"
GEOCODED_WANT_TO_GO_PATH = LOCAL_SAVED_TAKEOUT_PATH / "Want to go_geocoded.csv"
USER_KEY = "local-default"
_CACHE_VERSION = "2026-08-16-command-center-scotland-opener"

def _bar(pct: float) -> str:
    filled = max(0, min(10, int(round(pct / 10))))
    return "█" * filled + "░" * (10 - filled)


@st.cache_resource
def get_cc_services():
    _ = _CACHE_VERSION
    database = AtlasDatabase(ATLAS_DB_PATH)
    database.migrate()
    repository = AtlasRepository(database)
    load_bundled_knowledge(repository)
    pin_service = PinService(PIN_DB_PATH, atlas_database_path=ATLAS_DB_PATH)
    pin_service.sync_pipeline(LOCAL_SAVED_TAKEOUT_PATH, GEOCODED_WANT_TO_GO_PATH)
    knowledge = KnowledgeService(repository)
    itinerary = ItineraryService(pin_service)
    destination_itinerary = DestinationItineraryService(pin_service, itinerary)
    seasonal = SeasonalContextService(repository)
    preferences = PreferencesService(repository)
    planning_links = PlanningService(preferences)
    trip_service = TripPlanService(
        repository, destination_itinerary, knowledge, seasonal
    )
    lifecycle = LifecycleService(repository)
    prep = PrepService(repository)
    learning = LearningQueueService(repository)
    reservations = ReservationService(repository)
    photos = PhotoService(repository)
    logistics = LogisticsService()
    budget = BudgetBoardService(repository)
    today = TodayService(
        repository, trip_service, lifecycle, prep, learning, reservations, photos
    )
    mode = ModeService(repository, trip_service, lifecycle)
    feedback = FeedbackService(repository)
    engine = PlanningEngine(
        pin_service=pin_service,
        knowledge_service=knowledge,
        preferences_service=preferences,
        itinerary_service=destination_itinerary,
        planning_service=planning_links,
    )
    return {
        "repository": repository,
        "pin_service": pin_service,
        "trip_service": trip_service,
        "lifecycle": lifecycle,
        "prep": prep,
        "learning": learning,
        "reservations": reservations,
        "photos": photos,
        "logistics": logistics,
        "budget": budget,
        "today": today,
        "mode": mode,
        "feedback": feedback,
        "engine": engine,
        "preferences": preferences,
        "traveler_docs": TravelerDocsService(
            preferences, StateDeptSafetyProvider(cache_db_path=ATLAS_DB_PATH)
        ),
        "travelers": TravelerService(repository),
    }


def main() -> None:
    st.set_page_config(page_title="Command Center", layout="wide")
    s = get_cc_services()

    st.title("Command Center")
    st.caption(
        "Idea → Planning → Committed → Preparation → Traveling → Completed → Remembered. "
        "Commitment = first hotel or flight reserved. Offline-first providers."
    )

    with st.sidebar:
        render_pin_refresh_button(
            s["pin_service"],
            LOCAL_SAVED_TAKEOUT_PATH,
            GEOCODED_WANT_TO_GO_PATH,
            cache_clear_fns=[get_cc_services],
        )

    mode_state = s["mode"].resolve(USER_KEY)
    mode = st.selectbox(
        "Application mode",
        list(mode_state["modes"]),
        index=list(mode_state["modes"]).index(mode_state["mode"]),
        format_func=lambda m: m.replace("_", " ").title(),
    )
    if mode != mode_state["mode"]:
        s["mode"].set_mode(mode, USER_KEY)
        st.rerun()

    trips = s["trip_service"].list_trips(kind="trip")
    trip_id = None
    if trips:
        session_id = st.session_state.get("cc_selected_trip_id") or st.session_state.get(
            "active_trip_id"
        )
        ids = [t["id"] for t in trips]
        default_index = preferred_trip_index(trips, session_trip_id=session_id)
        trip_id = st.selectbox(
            "Trip",
            ids,
            index=default_index,
            format_func=lambda tid: next(
                (
                    f"{t['name']}"
                    + (" ★" if t.get("active_focus") else "")
                    + (" · committed" if t.get("committed_at") else "")
                    for t in trips
                    if t["id"] == tid
                ),
                tid,
            ),
        )
        st.session_state["cc_selected_trip_id"] = trip_id

    st.page_link(
        page("create-trip"),
        label="Create trip with departure date",
        icon="🗓️",
        help="Opens a dedicated page, then returns here with the new trip selected.",
    )
    st.page_link(
        page("alaska-aurora"),
        label="Alaska aurora (LAX, stay put)",
        icon="🌌",
        help="Fairbanks aurora planner — September space weather + hotels, then create a 3–4 day trip.",
    )

    if not trip_id:
        st.info("Create a trip to open the Command Center.")
        return
    from travel_atlas.services.alaska_aurora import (
        already_applied as alaska_already_applied,
        apply_alaska_aurora,
        book_first_items as alaska_book_first_items,
        should_apply as alaska_should_apply,
    )
    from travel_atlas.services.scotland_opener import (
        DAY1_CAPTION,
        apply_scotland_opener,
        book_first_items,
        is_scotland_leg,
        should_apply,
    )

    preview = s["trip_service"].get_trip(trip_id)
    if should_apply(preview):
        apply_scotland_opener(
            s["trip_service"],
            s["reservations"],
            trip_id=trip_id,
            prep_service=s["prep"],
        )
    if alaska_should_apply(preview):
        apply_alaska_aurora(
            s["trip_service"],
            s["reservations"],
            trip_id=trip_id,
            prep_service=s["prep"],
        )
    trip = s["trip_service"].get_trip(trip_id)
    if trip.get("parent_trip_id"):
        try:
            parent = s["trip_service"].get_trip(trip["parent_trip_id"])
            st.caption(f"Region: **{parent['name']}**")
        except ValueError:
            pass
    if trip.get("children"):
        st.caption(
            "Child trips: "
            + ", ".join(c["name"] for c in trip["children"])
        )

    kind, label = s["lifecycle"].primary_destination(trip)
    prefs = s["preferences"].get_preferences(USER_KEY)
    progress = s["prep"].progress(trip["id"], "90")
    journal = s["repository"].list_journal_entries(USER_KEY, destination_label=label)
    ratings = s["repository"].list_recommendation_ratings(USER_KEY, destination_label=label)
    photo_count = s["photos"].count_for_trip(trip["id"])
    life = s["lifecycle"].resolve(
        trip,
        journal_count=len(journal),
        rating_count=len(ratings),
        checklist_total=progress["total"],
        checklist_done=progress["done"],
        has_itinerary_stops=bool(trip.get("days")),
        photo_count=photo_count,
        is_committed=bool(trip.get("committed_at")),
    )
    progress = s["prep"].progress(trip["id"], life["prep_band"])
    life["prep_score"] = progress["prep_score"]

    # Lifecycle strip
    st.header("Lifecycle")
    cols = st.columns(len(LIFECYCLE_STAGES))
    for col, stage in zip(cols, LIFECYCLE_STAGES):
        mark = "●" if stage == life["stage"] else "○"
        col.markdown(f"**{mark} {stage.replace('_', ' ').title()}**")

    days = life.get("days_until")
    st.subheader(
        f"{days} days" if days is not None else "No departure date"
    )
    st.caption(
        f"Preparation ({life['prep_band']}-day band) · "
        f"{'Committed' if life.get('is_committed') else 'Not yet committed'}"
    )
    st.markdown(
        f"Prep score `{_bar(progress['prep_score'])}` {progress['prep_score']:.0f}%"
    )

    if trip.get("committed_at"):
        if st.button("Set as Active Trip (Today focus)"):
            s["trip_service"].set_active_focus(trip["id"])
            s["mode"].set_focused_trip(trip["id"], USER_KEY)
            s["mode"].set_mode("active_trip", USER_KEY)
            st.success("Active Trip focus set.")
            st.rerun()
    else:
        st.info("Reserve a hotel or flight below to commit this trip.")

    st.header("Book first")
    if alaska_already_applied(trip):
        st.caption(
            "LAX round-trip to FAI, one Fairbanks hotel, airport car. "
            "Aurora nights in town or Chena — saving as book_now does not commit "
            "the trip. Mark reserved when you actually pay."
        )
        first_items = alaska_book_first_items(s["reservations"].list_for_trip(trip["id"]))
    else:
        st.caption(
            "Inbound EDI flight, then car, then Dundee and Glasgow hotels. "
            "Saving as book_now does not commit the trip — Mark reserved when you actually pay."
        )
        first_items = book_first_items(s["reservations"].list_for_trip(trip["id"]))
    for item in first_items:
        cols = st.columns([3, 1])
        status = item.get("status") or "book_now"
        cols[0].markdown(f"**{item['title']}** · {item['kind']} · {status}")
        if item.get("notes"):
            cols[0].caption(item["notes"])
        if item.get("booking_url"):
            cols[1].link_button("Open to book", item["booking_url"])

    from travel_atlas.services.trip_context import WEST_EUROPE_NAME_HINT

    if WEST_EUROPE_NAME_HINT in str(trip.get("name") or "").casefold():
        from travel_atlas.services.west_europe_briefing import (
            briefing_filename,
            build_west_europe_briefing_html,
        )

        st.header("Trip briefing")
        st.caption(
            "Print-ready HTML for the 45-day West Europe route (11 legs, AstroClick-style "
            "ACG maps, Scotland hotels). Open in the browser → Print → Save as PDF."
        )
        primary = s["travelers"].ensure_primary(USER_KEY)
        companion = s["travelers"].ensure_companion(USER_KEY)
        we_html = build_west_europe_briefing_html(
            pins=s["pin_service"].list_pins(),
            primary_traveler=primary,
            companion_traveler=companion,
        )
        st.download_button(
            "Generate West Europe briefing (HTML)",
            data=we_html.encode("utf-8"),
            file_name=briefing_filename(),
            mime="text/html",
            key="cc-we-briefing-html",
        )

    st.header("Reservations")
    cards = s["reservations"].cards_for_trip(trip["id"])
    for card in cards:
        cols = st.columns([3, 1, 1, 1])
        cols[0].markdown(f"**{card['title']}** ({card['kind']})")
        cols[1].caption(card["action_label"])
        if card.get("can_notify") and cols[2].button("Notify me", key=f"n-{card['id']}"):
            s["reservations"].schedule_notify(card["id"])
            st.rerun()
        if card["status"] != "reserved" and cols[3].button(
            "Mark reserved", key=f"r-{card['id']}"
        ):
            s["reservations"].mark_reserved(card["id"])
            st.rerun()
        if card.get("booking_url"):
            st.caption(card["booking_url"])

    with st.expander("Add reservation (quick / non-hotel)"):
        r_kind = st.selectbox(
            "Kind",
            ["flight", "museum", "train", "restaurant", "event", "tour", "other"],
        )
        r_title = st.text_input("Title", value="Flight")
        r_status = st.selectbox(
            "Status",
            [
                "not_available",
                "available_soon",
                "book_now",
                "reserved",
                "completed",
                "cancelled",
            ],
            index=2,
        )
        r_opens = st.text_input("Opens on (YYYY-MM-DD, optional)", value="")
        if st.button("Add reservation"):
            s["reservations"].create(
                trip["id"],
                kind=r_kind,
                title=r_title,
                status=r_status,
                opens_on=r_opens.strip() or None,
            )
            st.rerun()

    st.page_link(
        page("add-reservation"),
        label="Add hotel reservation (compare + simulate)",
        icon="🏨",
        help="Dedicated page with photos, deep-link price compare, auto hotel titles.",
    )
    st.page_link(
        page("add-flight"),
        label="Add flight (compare + simulate)",
        icon="✈️",
        help="Dedicated page with Google Flights / Kayak deep-links.",
    )

    opening = s["reservations"].opening_soon(trip["id"])
    if opening:
        st.subheader("Opening soon")
        for item in opening:
            st.markdown(f"- {item['headline']}: **{item['title']}**")

    st.header("This Week")
    st.markdown(" · ".join(s["prep"].this_week_topics(life["prep_band"])))

    # Wired passport / entry / cities for ALL trip destinations (not Gabon).
    # Rebuild docs from the reloaded class — cache_resource can keep a stale
    # TravelerDocsService instance across code edits (missing entry_conditionals).
    docs_svc = TravelerDocsService(
        s["preferences"],
        getattr(
            s.get("traveler_docs"),
            "safety",
            StateDeptSafetyProvider(cache_db_path=ATLAS_DB_PATH),
        ),
    )
    s["traveler_docs"] = docs_svc
    traveler_svc = TravelerService(s["repository"])
    s["travelers"] = traveler_svc
    primary_traveler = traveler_svc.ensure_primary(USER_KEY)
    companion_traveler = traveler_svc.ensure_companion(USER_KEY)
    docs_svc.ensure_defaults(USER_KEY)
    departure = None
    try:
        dep_raw = (trip.get("definition") or {}).get("departure_date")
        if dep_raw:
            departure = date.fromisoformat(str(dep_raw)[:10])
    except ValueError:
        departure = None

    dest_labels = [
        (d.get("destination_label") or d.get("label") or "").strip()
        for d in trip.get("destinations") or []
        if (d.get("destination_label") or d.get("label"))
    ]
    regions = expand_trip_regions(dest_labels) or dest_labels or [label or "United Kingdom"]

    # Sync traveler_documents display from primary traveler row.
    traveler_docs = traveler_svc.as_documents(primary_traveler)
    bag = dict(prefs.get("preferences") or {})
    bag["traveler_documents"] = {
        **dict(bag.get("traveler_documents") or {}),
        **{k: v for k, v in traveler_docs.items() if v is not None},
    }
    s["preferences"].merge_preference_bag(bag, USER_KEY)

    passport = docs_svc.passport_status(
        destination=regions[0] if regions else "United Kingdom",
        departure=departure,
        user_key=USER_KEY,
    )
    companion_docs = traveler_svc.as_documents(companion_traveler)
    companion_passport = docs_svc.passport_status(
        destination=regions[0] if regions else "United Kingdom",
        departure=departure,
        documents=companion_docs,
    )
    entries = docs_svc.entry_for_destinations(regions)

    st.header("Travelers")
    st.caption(
        f"Primary: **{primary_traveler.get('display_name')}** · "
        f"Companion: **{companion_traveler.get('display_name')}**"
    )

    def _render_traveler_docs(person: dict, docs: dict, passport_info: dict) -> None:
        blank = docs.get("visa_pages_blank")
        blank_txt = f"{blank} blank pages" if blank is not None else "blank pages not recorded"
        st.write(
            f"Passport **{docs.get('passport_country') or '—'}** · "
            f"expires **{docs.get('passport_expires') or '—'}** · {blank_txt}"
        )
        ge = docs.get("global_entry_expires")
        st.write(
            f"Global Entry **{ge or 'not recorded'}** · "
            f"TSA PreCheck: "
            + (
                "included via Global Entry"
                if docs.get("tsa_precheck_via_global_entry")
                else ("held" if docs.get("tsa_precheck") else "not held / not recorded")
            )
        )
        birth = docs.get("birth_date") or "—"
        st.write(
            f"Natal: **{person.get('display_name')}** · {birth} "
            f"{docs.get('birth_time') or '—'} "
            f"{docs.get('birth_timezone') or '—'} · "
            f"{docs.get('birth_place') or '—'}"
        )
        for issue in passport_info.get("issues") or []:
            st.warning(f"{person.get('display_name')}: {issue}")

    with st.expander(
        f"{primary_traveler.get('display_name')} — documents & natal", expanded=False
    ):
        _render_traveler_docs(primary_traveler, traveler_docs, passport)
    with st.expander(
        f"{companion_traveler.get('display_name')} — documents & natal", expanded=False
    ):
        _render_traveler_docs(companion_traveler, companion_docs, companion_passport)

    st.header("Travel documents & entry")
    st.write(
        f"**{primary_traveler.get('display_name')}** · "
        f"Passport **{passport['passport_country']}** · expires **{passport['expires']}** · "
        f"{passport['blank_pages']} blank pages · Global Entry **{passport['global_entry_expires']}** · "
        f"TSA PreCheck: "
        + (
            "included via Global Entry"
            if passport.get("tsa_precheck_via_global_entry")
            else ("held" if passport["tsa_precheck"] else "get this (recommended)")
        )
    )
    for issue in passport["issues"]:
        st.warning(issue)
    st.caption(
        f"**{companion_traveler.get('display_name')}** · "
        f"passport expires **{companion_docs.get('passport_expires')}** "
        f"({companion_docs.get('passport_country')})"
    )

    st.subheader("If / then — US passport")
    st.caption("Personal checklist, not legal advice. Confirm on the State Dept text below.")
    seen_cond: set[str] = set()
    for block in entries:
        dest = block.get("destination") or block.get("api_label") or ""
        for item in docs_svc.entry_conditionals(str(dest)):
            if item in seen_cond:
                continue
            seen_cond.add(item)
            st.markdown(f"- {item}")

    for block in entries:
        dest = block.get("destination") or block.get("api_label")
        with st.expander(f"{dest} — entry / health / embassy", expanded=(dest == regions[0])):
            geo = block.get("geopoliticalarea")
            if geo:
                st.caption(f"State Dept area: {geo}")
                locator = docs_svc.locator_map_for_area(str(geo))
                if locator and "Gabon" in str(geo):
                    st.warning("Wrong country tag was used historically — showing locator map.")
                    st.image(locator, caption=f"Where is {geo}?", use_container_width=True)
            if block.get("entry"):
                st.markdown("**Entry / visa**")
                st.write(block["entry"]["body"][:2500])
            if block.get("health"):
                st.markdown("**Health & vaccinations**")
                st.write(block["health"]["body"][:2500])
            if block.get("embassy"):
                st.markdown("**Embassy / consulate**")
                st.write(block["embassy"]["body"][:2500])
            for name, url in (block.get("links") or {}).items():
                st.markdown(f"- [{name}]({url})")
            st.page_link(
                page("destination-atlas"),
                label=f"Open Destination Atlas overview ({dest})",
            )

    st.header("Major cities per country / region")
    st.caption(
        "Seeded major cities for each trip leg — also on Destination Atlas trip overview."
    )
    region_pick = st.select_slider(
        "Place",
        options=regions,
        value=regions[0],
    )
    cities = docs_svc.major_cities(region_pick)
    map_url = docs_svc.cities_map_url(region_pick)
    if map_url:
        st.image(map_url, caption=f"Major cities — {region_pick}", use_container_width=True)
    if cities:
        for city in cities:
            st.markdown(f"- {city}")
    else:
        st.caption("No seeded city list for this destination yet.")

    st.header("Astrocartography & trip map")
    st.caption(
        "Grey pins, red lodging zones. Bold planetary glyphs are angular ACG lines; "
        "smaller glyphs are aspects (not dashed). Map stays on the trip region — no wrapping world."
    )
    from travel_atlas.services.lodging_advisor import suggest_lodging_locations

    build_trip_map = _trip_map_mod.build_trip_map
    render_map_layer_toggles = _trip_map_mod.render_map_layer_toggles
    render_streamlit_map = _trip_map_mod.render_streamlit_map
    render_pins_by_region = _trip_map_mod.render_pins_by_region

    primary = traveler_svc.ensure_primary(USER_KEY)
    companion = traveler_svc.ensure_companion(USER_KEY)
    acg_who = st.radio(
        "Natal for map / ranking",
        options=["Traveler One", "Traveler Two", "Both"],
        horizontal=True,
        key="cc-acg-traveler",
        help="Both overlays Companion in a cooler second color; ranking still uses Traveler One.",
    )
    companion_acg: list = []
    companion_aspects: list = []
    if acg_who == "Traveler One":
        chart_person = primary
        acg_lines, aspect_lines, acg_msg = chart_layers_for_traveler(primary)
    elif acg_who == "Companion":
        chart_person = companion
        acg_lines, aspect_lines, acg_msg = chart_layers_for_traveler(companion)
    else:
        chart_person = primary
        acg_lines, aspect_lines, acg_msg = chart_layers_for_traveler(primary)
        companion_acg, companion_aspects, companion_msg = chart_layers_for_traveler(companion)
        if companion_msg != "ok":
            st.info(f"Companion ACG: {companion_msg}")
    st.caption(
        f"Natal used: {chart_person.get('display_name')} · "
        f"{chart_person.get('birth_date')} {chart_person.get('birth_time')} "
        f"{chart_person.get('birth_timezone')} · {chart_person.get('birth_place')}"
        + (
            f" · overlay: {companion.get('display_name')}"
            if acg_who == "Both"
            else ""
        )
    )
    if acg_msg != "ok":
        st.info(acg_msg)
    else:
        chiron_n = sum(
            1
            for line in acg_lines
            if str(line.get("body") or "").casefold().startswith("chiron")
        )
        st.success(
            f"{len(acg_lines)} angular + {len(aspect_lines)} aspect line segments ready"
            + (f" · ⚷ Chiron included ({chiron_n} angular)" if chiron_n else " · ⚷ Chiron missing")
            + (
                f" · +{len(companion_acg)} companion angular"
                if companion_acg
                else ""
            )
            + ". Turn on Astrocartography below if the lines are hidden."
        )
        from travel_atlas.services.astro_helper import rank_trip_route

        ranked = rank_trip_route(
            chart_person if acg_who != "Both" else primary,
            trip.get("destinations") or [],
            angular=acg_lines,
            aspects=aspect_lines,
        )
        if ranked.get("legs"):
            st.subheader("Suggested leg order (natal ACG)")
            st.caption(
                "Higher score = closer to supportive Sun/Moon/Venus/Jupiter lines. "
                "Not a street itinerary — pin grouping into events comes later."
            )
            st.markdown(
                " → ".join(f"**{leg['label']}** ({leg['score']})" for leg in ranked["legs"])
            )
            for city in (ranked.get("cities") or [])[:6]:
                hits = ", ".join(city.get("hits") or []) or "no close lines"
                st.caption(f"{city['city']} ({city['leg']}): {city['score']} — {hits}")

    all_pins = s["pin_service"].list_pins()
    trip_pins = []
    for dest in trip.get("destinations") or []:
        kind = dest.get("destination_kind") or dest.get("kind") or "country"
        label = (dest.get("destination_label") or dest.get("label") or "").replace(
            " (UK)", ""
        )
        trip_pins.extend(p for p in all_pins if destination_matches(p, kind, label))
    ireland_n = sum(
        1
        for p in trip_pins
        if destination_matches(p, "country", "Ireland")
    )
    st.caption(ireland_leg_caption(ireland_n))
    lodging = suggest_lodging_locations(
        trip_pins, trip.get("destinations") or [], limit=6
    )
    flags = render_map_layer_toggles(
        key_prefix="cc-map",
        acg_available=(acg_msg == "ok"),
    )
    render_streamlit_map(
        build_trip_map(
            trip_pins,
            lodging,
            acg_lines=acg_lines,
            aspect_lines=aspect_lines,
            companion_acg_lines=companion_acg or None,
            companion_aspect_lines=companion_aspects or None,
            **flags,
        ),
        key="cc-trip-overview-map-v1",
    )
    if any(is_scotland_leg(d) for d in trip.get("destinations") or []):
        st.info(DAY1_CAPTION)
    render_pins_by_region(trip_pins, key_prefix="cc-pins")

    st.header("Checklist")
    for item in progress["items"]:
        done = bool(item.get("completed_at"))
        auto_hint = ""
        if item["key"] == "passport" and passport["ok"]:
            auto_hint = " · profile OK (GE includes PreCheck)"
        if item["key"] == "visa":
            auto_hint = " · see per-country entry panels above"
        if item["key"] == "cities":
            auto_hint = " · use cities slider above"
        if item["key"] == "language_basics":
            auto_hint = " · open language apps below"
        cols = st.columns([4, 1])
        with cols[0]:
            if st.checkbox(
                f"[{item['band']}] {item['title']}{auto_hint}",
                value=done,
                key=f"chk-{item['key']}",
            ):
                if not done:
                    s["prep"].toggle(trip["id"], item["key"], True)
                    st.rerun()
            elif done:
                s["prep"].toggle(trip["id"], item["key"], False)
                st.rerun()
        with cols[1]:
            if item["key"] in {"cities", "overview", "visa"} and regions:
                st.page_link(page("destination-atlas"), label="Atlas")
            if item["key"] in {"language_basics", "language_review"}:
                st.page_link(page("language"), label="Language")

    st.header("Learning Queue")
    lesson = s["learning"].today_lesson(
        destination_label=label,
        prep_band=life["prep_band"],
        interests=list(prefs.get("interests") or []),
    )
    st.markdown(
        f"**{lesson['title']}** · ~{lesson['estimated_minutes']} minutes"
    )
    for item in lesson.get("items") or []:
        st.markdown(f"- {item}")
    with st.expander("Phrases"):
        for phrase in lesson.get("phrases") or []:
            if isinstance(phrase, dict):
                st.markdown(
                    f"- {phrase.get('phrase')} — {phrase.get('translation')}"
                )
    st.markdown("**Open language tutors**")
    c_lang1, c_lang2 = st.columns(2)
    with c_lang1:
        st.page_link(page("language"), label="Atlas Language (offline phrases)")
    with c_lang2:
        st.link_button(
            "LinguaGraph (localhost:3000)",
            "http://localhost:3000/",
            help="Start with language_learning/run_language.ps1 first.",
        )
    st.caption(
        "West Europe pack: Scottish Gaelic · Irish Gaelic · Welsh · French · Spanish · Portuguese "
        "— see travel_atlas/data/west_europe_language_pack.json"
    )

    st.header("Photos")
    st.caption(f"{photo_count} photo(s) linked to this trip")
    with st.expander("Add photo (manual / local)"):
        caption = st.text_input("Caption", key="photo-caption")
        local_path = st.text_input("Local path or URI", key="photo-path")
        day_num = st.number_input("Day number", min_value=0, value=0, key="photo-day")
        if st.button("Save photo metadata"):
            s["photos"].add(
                trip["id"],
                caption=caption,
                local_path=local_path or None,
                day_number=int(day_num) or None,
            )
            st.rerun()
    for photo in s["photos"].list_for_trip(trip["id"])[:8]:
        st.markdown(
            f"- {photo.get('caption') or '(no caption)'} · "
            f"{photo.get('local_path') or photo.get('source_uri') or 'no path'}"
        )

    # Planner + logistics
    st.header("Recommendations + Logistics")
    definition = trip.get("definition") or {}
    trip_def = TripDefinition(
        destination_kind=kind,
        destination_label=label,
        day_count=sum(int(d.get("day_count") or 1) for d in trip.get("destinations") or [])
        or 3,
        start_date=life.get("departure_date"),
        end_date=life.get("return_date"),
        budget=float(definition["budget"]) if definition.get("budget") else None,
        pace=str(definition.get("pace") or "medium"),
        energy=str(definition.get("energy") or "medium"),
    )
    report = s["engine"].plan(
        destination_kind=kind,
        destination_label=label,
        trip=trip_def,
        user_key=USER_KEY,
    )
    st.write(report.summary)
    pins = [
        p
        for p in s["pin_service"].list_pins()
        if (p.country or "").lower() == label.lower()
        or label.lower() in (p.country or "").lower()
    ]
    for rec in report.experiences[:6]:
        card = s["logistics"].enrich(rec, pins=pins)
        st.markdown(f"**{rec.title}** · score {rec.score}")
        st.caption(rec.explanation)
        with st.expander("Logistics card"):
            st.markdown(f"- Opening hours: {card['opening_hours']}")
            st.markdown(f"- Expected cost: ${card['expected_cost']}")
            st.markdown(f"- Walking time: {card['walking_minutes']} min")
            st.markdown(f"- Metro: {card['metro_stop']}")
            st.markdown(f"- Taxi estimate: ${card['taxi_estimate']}")
            st.markdown(
                f"- Reservation needed: {'Yes' if card['needs_reservation'] else 'No'}"
            )
            st.markdown(f"- Typical visit: {card['typical_visit_hours']}h")
            if card["nearby_food"]:
                st.markdown("- Nearby food: " + ", ".join(card["nearby_food"]))
            if card["nearby_grocery"]:
                st.markdown("- Nearby grocery: " + ", ".join(card["nearby_grocery"]))
            st.markdown(f"- How to get there: {card['how_to_get_there']}")
            st.caption(f"Provider status: {card['provider_status']}")

    # Budget board
    st.header("Budget Board")
    s["budget"].seed_from_plan(
        trip["id"],
        trip_budget=trip_def.budget,
        recommendations=report.experiences,
        day_count=trip_def.day_count,
    )
    board = s["budget"].board(trip["id"])
    st.markdown(
        f"Estimated total **${board['estimated_total']}** · "
        f"Remaining **${board['remaining']}**"
    )
    for row in board["categories"]:
        st.markdown(
            f"**{row['label']}** — estimated ${row['estimated']:.0f} · "
            f"confidence {row['confidence']:.0f}%"
        )
        if row["actual"] is not None:
            st.caption(f"Actual ${row['actual']:.0f}")

    if report.experiences and trip_def.budget:
        top = report.experiences[0]
        blurb = s["budget"].value_blurb(
            added_cost=top.estimated_cost,
            trip_budget=trip_def.budget,
            coverage_gain_pct=min(14.0, top.score / 7),
        )
        st.info(blurb)

    st.header("Journal")
    entries = s["feedback"].list_journal(destination_label=label)[:3]
    if entries:
        for entry in entries:
            st.markdown(f"- {entry.get('body', '')[:120]}")
    else:
        st.caption("No journal entries yet — write them from the Planning page.")


if __name__ == "__main__":
    main()
