"""Personalized Planning page — destination recommendations and itineraries."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import streamlit as st

_TRAVEL_ROOT = Path(__file__).parent.parent
if str(_TRAVEL_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRAVEL_ROOT))

from travel_atlas.database import AtlasDatabase
from travel_atlas.knowledge_loader import load_bundled_knowledge
from travel_atlas.planning import PlanningEngine
from travel_atlas.repository import AtlasRepository
from travel_atlas.services import (
    DestinationItineraryService,
    DestinationService,
    FeedbackService,
    ItineraryService,
    KnowledgeService,
    LanguageService,
    NotesService,
    PinService,
    PlanningService,
    PreferencesService,
    SeasonalContextService,
    TripPlanService,
)
from travel_atlas.services.climate_service import ClimateService
from travel_atlas.services.types import Recommendation, TripDefinition

ATLAS_DB_PATH = _TRAVEL_ROOT / "atlas.db"
PIN_DB_PATH = _TRAVEL_ROOT / "travel_pins.db"
LOCAL_SAVED_TAKEOUT_PATH = _TRAVEL_ROOT / "Takeout" / "Saved"
GEOCODED_WANT_TO_GO_PATH = LOCAL_SAVED_TAKEOUT_PATH / "Want to go_geocoded.csv"
USER_KEY = "local-default"

_CACHE_VERSION = "2026-08-04-planning-feedback-v2"

_RATING_LABELS = {
    "loved": "Loved",
    "liked": "Liked",
    "neutral": "Neutral",
    "disliked": "Didn't enjoy",
    "skip": "Skip next time",
}


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
    preferences_service = PreferencesService(repository)
    planning_links = PlanningService(preferences_service)
    trip_service = TripPlanService(
        repository, destination_itinerary, knowledge_service, seasonal_context_service
    )
    climate_service = ClimateService(ATLAS_DB_PATH)
    feedback_service = FeedbackService(repository)
    planning_engine = PlanningEngine(
        pin_service=pin_service,
        knowledge_service=knowledge_service,
        preferences_service=preferences_service,
        itinerary_service=destination_itinerary,
        planning_service=planning_links,
        climate_service=climate_service,
    )
    return (
        destination_service,
        preferences_service,
        trip_service,
        planning_engine,
        feedback_service,
    )


def _subject_for(rec: Recommendation) -> tuple[str, str]:
    if "pin_id" in rec.source_refs:
        return "pin", rec.source_refs["pin_id"]
    if "claim_id" in rec.source_refs:
        return "claim", rec.source_refs["claim_id"]
    return "title", rec.title.lower()


def _render_recommendation(
    rec: Recommendation,
    *,
    feedback: FeedbackService,
    destination_label: str,
    key_prefix: str,
) -> None:
    st.markdown(
        f"**{rec.title}** · {rec.category} · {rec.priority_tier} · score {rec.score}"
    )
    bits = [
        rec.location,
        f"~{rec.estimated_duration_hours:g}h",
        f"~${rec.estimated_cost:g}",
        f"confidence {rec.confidence:.0%}",
    ]
    if rec.joy_per_dollar is not None:
        bits.append(f"joy/$ {rec.joy_per_dollar:g}")
    st.caption(" · ".join(bits))
    st.write(rec.explanation)

    with st.expander("Why this?"):
        st.markdown(f"**Overall match: {rec.score:.0f}%**")
        for factor in rec.match_breakdown:
            mark = "✓" if factor.matched else "·"
            st.markdown(f"{mark} {factor.label} (+{factor.points:g})")

    kind, subject_id = _subject_for(rec)
    cols = st.columns(5)
    for col, (rating, label) in zip(cols, _RATING_LABELS.items()):
        if col.button(label, key=f"{key_prefix}-{rating}-{subject_id}"):
            feedback.rate(
                subject_kind=kind,
                subject_id=subject_id,
                rating=rating,
                destination_label=destination_label,
                category=rec.category,
            )
            st.success(f"Rated {label}")
            st.rerun()
    if rec.user_rating:
        st.caption(f"Your rating: {_RATING_LABELS.get(rec.user_rating, rec.user_rating)}")


def _coverage_bar(pct: float) -> str:
    filled = max(0, min(10, int(round(pct / 10))))
    return "█" * filled + "░" * (10 - filled)


def main() -> None:
    st.set_page_config(page_title="Planning", layout="wide")
    (
        destination_service,
        preferences_service,
        trip_service,
        planning_engine,
        feedback_service,
    ) = get_services()

    st.title("Planning")
    st.caption(
        "Maximize personal joy per dollar. Saved pins are the backbone — "
        "ratings teach the planner what you actually love."
    )

    destinations = destination_service.list_destinations()
    if not destinations:
        st.warning("Add saved pins or destinations first.")
        return

    labels = [item["display_name"] for item in destinations]
    selected_label = st.selectbox("Country / destination", labels)
    selected = next(item for item in destinations if item["display_name"] == selected_label)

    from travel_atlas.services.regional_defaults import (
        get_regional_defaults,
        recommendation_summary,
    )

    prefs = preferences_service.get_preferences(USER_KEY)
    regional = get_regional_defaults(selected["label"]) or get_regional_defaults(
        selected["display_name"]
    )
    rec = recommendation_summary(selected["label"]) or recommendation_summary(
        selected["display_name"]
    )
    if rec:
        st.info(
            f"Suggested for {rec.get('region_key')}: "
            f"**{rec.get('suggested_days')} days** · budget **{rec.get('budget_tendency')}** · "
            f"transport {', '.join(rec.get('transportation_preferences') or [])}"
        )

    with st.expander("Traveler preferences", expanded=False):
        bag = dict(prefs.get("preferences") or {})
        if regional and st.button("Apply regional defaults (fill empty fields only)"):
            merged = dict(bag)
            for key in (
                "favorite_foods",
                "museum_types",
                "outdoor_interests",
                "transportation_preferences",
            ):
                if not merged.get(key) and regional.get(key):
                    merged[key] = list(regional[key])
            if not merged.get("budget_tendency") and regional.get("budget_tendency"):
                merged["budget_tendency"] = regional["budget_tendency"]
            interests_seed = list(prefs.get("interests") or []) or list(
                regional.get("interests") or []
            )
            preferences_service.update_preferences(
                interests_seed,
                prefs.get("travel_style") or "balanced",
                prefs.get("accommodation_preferences") or {},
                prefs.get("learning_goals") or [],
                USER_KEY,
                merged,
            )
            st.success("Regional defaults applied to empty fields.")
            st.rerun()

        interests = st.multiselect(
            "Interests (taxonomy tags)",
            options=[
                "market_food",
                "museum_history",
                "nature_gardens",
                "temple_spirituality",
                "transport",
                "nightlife",
                "shopping",
            ],
            default=list(prefs.get("interests") or (regional or {}).get("interests") or []),
        )
        bag = dict(preferences_service.get_preferences(USER_KEY).get("preferences") or {})
        favorite_foods = st.text_input(
            "Favorite foods (comma-separated)",
            value=", ".join(
                bag.get("favorite_foods") or (regional or {}).get("favorite_foods") or []
            ),
        )
        museum_types = st.text_input(
            "Museum types (comma-separated)",
            value=", ".join(
                bag.get("museum_types") or (regional or {}).get("museum_types") or []
            ),
        )
        outdoor = st.text_input(
            "Outdoor interests (comma-separated)",
            value=", ".join(
                bag.get("outdoor_interests")
                or (regional or {}).get("outdoor_interests")
                or []
            ),
        )
        nightlife = st.checkbox("Nightlife interest", value=bool(bag.get("nightlife_interest")))
        shopping = st.checkbox("Shopping interest", value=bool(bag.get("shopping_interest")))
        budget_options = ["frugal", "moderate", "comfortable", "luxury"]
        default_budget = str(
            bag.get("budget_tendency")
            or (regional or {}).get("budget_tendency")
            or "moderate"
        )
        budget_tendency = st.selectbox(
            "Budget tendency",
            budget_options,
            index=budget_options.index(default_budget)
            if default_budget in budget_options
            else 1,
        )
        transport_prefs = st.multiselect(
            "Transportation preferences",
            ["walking", "train", "subway", "bus", "car", "flight", "tram"],
            default=list(
                bag.get("transportation_preferences")
                or (regional or {}).get("transportation_preferences")
                or []
            ),
        )
        if st.button("Save preferences"):
            preferences_service.update_preferences(
                interests,
                prefs.get("travel_style") or "balanced",
                prefs.get("accommodation_preferences") or {},
                prefs.get("learning_goals") or [],
                USER_KEY,
                {
                    "favorite_foods": [x.strip() for x in favorite_foods.split(",") if x.strip()],
                    "museum_types": [x.strip() for x in museum_types.split(",") if x.strip()],
                    "outdoor_interests": [x.strip() for x in outdoor.split(",") if x.strip()],
                    "nightlife_interest": nightlife,
                    "shopping_interest": shopping,
                    "budget_tendency": budget_tendency,
                    "transportation_preferences": transport_prefs,
                },
            )
            st.success("Preferences saved.")

    st.subheader("Trip definition")
    col1, col2, col3 = st.columns(3)
    with col1:
        suggested_days = int((rec or {}).get("suggested_days") or 3)
        day_count = st.number_input(
            "Days", min_value=1, max_value=30, value=min(30, max(1, suggested_days))
        )
        pace = st.selectbox("Pace", ["slow", "medium", "fast"], index=1)
        energy = st.selectbox("Energy", ["low", "medium", "high"], index=1)
    with col2:
        start = st.date_input("Start date (optional)", value=None)
        budget = st.number_input("Trip budget (USD, optional)", min_value=0.0, value=0.0)
    with col3:
        travel_style = st.selectbox(
            "Travel style",
            ["balanced", "cultural", "adventure", "relaxed", "foodie"],
            index=0,
        )
        lodging = st.multiselect(
            "Lodging preferences",
            ["hotel", "hostel", "apartment", "ryokan", "camping"],
        )

    trip = TripDefinition(
        destination_kind=selected["kind"],
        destination_label=selected["label"],
        day_count=int(day_count),
        start_date=start.isoformat() if isinstance(start, date) else None,
        budget=float(budget) if budget and budget > 0 else None,
        transportation_preferences=tuple(
            preferences_service.get_preferences(USER_KEY)
            .get("preferences", {})
            .get("transportation_preferences")
            or []
        ),
        lodging_preferences=tuple(lodging),
        travel_style=travel_style,
        pace=pace,
        energy=energy,
    )

    save_col, run_col = st.columns(2)
    with save_col:
        if st.button("Save as trip plan"):
            trip_service.create_trip(
                name=f"{selected['display_name']} · {day_count}d",
                destinations=[
                    {
                        "kind": selected["kind"],
                        "label": selected["label"],
                        "day_count": int(day_count),
                        "start_date": trip.start_date,
                    }
                ],
                definition={
                    "departure_date": trip.start_date,
                    "budget": trip.budget,
                    "transportation_preferences": list(trip.transportation_preferences),
                    "lodging_preferences": list(trip.lodging_preferences),
                    "travel_style": trip.travel_style,
                    "pace": trip.pace,
                    "energy": trip.energy,
                    "cities": list(trip.cities),
                },
            )
            st.success("Trip saved. Open Trip Planner to view multi-leg itineraries.")
    with run_col:
        run = st.button("Generate plan", type="primary")

    if not run and "last_plan_dest" not in st.session_state:
        st.info("Set preferences and trip constraints, then generate a plan.")
        return

    if run:
        st.session_state["last_plan_dest"] = (
            selected["kind"],
            selected["label"],
            trip,
        )

    kind, label, trip_def = st.session_state["last_plan_dest"]
    report = planning_engine.plan(
        destination_kind=kind,
        destination_label=label,
        trip=trip_def,
        user_key=USER_KEY,
    )

    st.header("Planner Summary")
    st.write(report.summary)
    st.caption(
        f"Mix: {int(100 * report.exploration_mix.get('personalized', 0.9))}% personalized / "
        f"{int(100 * report.exploration_mix.get('discovery', 0.1))}% discovery · "
        f"Energy: {report.energy}"
    )

    st.header("Interest Coverage")
    cov = report.coverage or {}
    overall = float(cov.get("overall") or 0)
    st.markdown(f"**{label}** `{_coverage_bar(overall)}` {overall:.0f}%")
    for name, pct in (cov.get("per_interest") or {}).items():
        st.markdown(f"{name}: `{_coverage_bar(float(pct))}` {float(pct):.0f}%")

    if report.pin_backbone:
        st.header("Saved Pins (backbone)")
        by_tier: dict[str, list] = {}
        for item in report.pin_backbone:
            by_tier.setdefault(item["tier"], []).append(item)
        for tier in ("must_visit", "interested", "maybe", "discovery", "not_planned"):
            items = by_tier.get(tier) or []
            if not items:
                continue
            st.markdown(f"**{tier.replace('_', ' ').title()}**")
            for item in items:
                st.markdown(f"- {item['title']} · score {item['score']}")

    st.header("Recommended Experiences")
    if "trip_picks" not in st.session_state:
        st.session_state["trip_picks"] = []
    if report.experiences:
        for index, rec in enumerate(report.experiences):
            _render_recommendation(
                rec,
                feedback=feedback_service,
                destination_label=label,
                key_prefix=f"exp-{index}",
            )
            if st.button("Add to trip", key=f"add-exp-{index}-{rec.title}"):
                picks = list(st.session_state["trip_picks"])
                if rec.title not in picks:
                    picks.append(rec.title)
                    st.session_state["trip_picks"] = picks
                st.success(f"Added {rec.title}")
    else:
        st.caption("No scored experiences yet — save pins in this destination.")

    if st.session_state["trip_picks"]:
        st.subheader("Building your itinerary")
        for title in st.session_state["trip_picks"]:
            st.markdown(f"- {title}")

    st.header("Food")
    subsystem = report.food_subsystem or {}
    if subsystem.get("by_facet"):
        with st.expander("Food subsystem"):
            for facet, titles in subsystem["by_facet"].items():
                st.markdown(f"**{facet.replace('_', ' ').title()}**")
                for t in titles:
                    st.markdown(f"- {t}")
            if subsystem.get("cook_later_prompt"):
                st.info(subsystem["cook_later_prompt"])
    if report.food:
        for index, rec in enumerate(report.food):
            _render_recommendation(
                rec,
                feedback=feedback_service,
                destination_label=label,
                key_prefix=f"food-{index}",
            )
    else:
        st.caption("No food matches yet.")

    st.header("Museums")
    if report.museums:
        for index, rec in enumerate(report.museums):
            _render_recommendation(
                rec,
                feedback=feedback_service,
                destination_label=label,
                key_prefix=f"mus-{index}",
            )
    else:
        st.caption("No museum matches yet.")

    st.header("I Didn't Know I'd Like This")
    if report.wildcards:
        for index, rec in enumerate(report.wildcards):
            _render_recommendation(
                rec,
                feedback=feedback_service,
                destination_label=label,
                key_prefix=f"wild-{index}",
            )
    else:
        st.caption("Discovery slots fill when Atlas has adjacent surprises for you.")

    st.header("Transportation")
    if report.transportation:
        for index, rec in enumerate(report.transportation):
            _render_recommendation(
                rec,
                feedback=feedback_service,
                destination_label=label,
                key_prefix=f"tr-{index}",
            )
    else:
        st.caption("No transport-tagged pins yet.")

    st.header("Suggested Itinerary")
    for day in report.itinerary:
        heading = f"Day {day.get('day')}"
        if day.get("weekday"):
            heading = f"{day['weekday']}"
            if day.get("date"):
                heading += f" — {day['date']}"
        if day.get("theme_title"):
            heading += f" · {day['theme_title']}"
        st.markdown(f"### {heading}")
        if day.get("focus"):
            st.caption("Focus: " + ", ".join(day["focus"][:5]))
        for stop in day.get("stops") or []:
            st.markdown(
                f"- **{stop.get('name')}** ({stop.get('slot')}) · score {stop.get('score', 0)}"
            )
            if stop.get("explanation"):
                st.caption(stop["explanation"])

    st.header("Budget Estimate")
    budget_info = report.budget
    st.write(
        f"Sample experiences cost: **${budget_info.get('sample_experiences_cost', 0)}** "
        f"over {budget_info.get('day_count', 0)} day(s)."
    )
    if budget_info.get("avg_joy_per_dollar") is not None:
        st.caption(f"Avg joy per dollar: {budget_info['avg_joy_per_dollar']}")
    if budget_info.get("daily_cap") is not None:
        st.caption(f"Suggested daily cap: ${budget_info['daily_cap']}")
    for item in budget_info.get("over_budget_items") or []:
        st.warning(f"Over daily cap: {item['title']} (~${item['estimated_cost']})")
    st.caption(budget_info.get("philosophy") or budget_info.get("note") or "")

    st.header("Packing Considerations")
    for item in report.packing:
        st.markdown(f"- {item}")

    st.header("Trip Journal")
    with st.form("journal_form"):
        journal_body = st.text_area(
            "What did you actually do — and how did it feel?",
            placeholder="Day notes, surprises, meals worth repeating…",
        )
        enjoyed = st.text_input("Enjoyed (comma-separated titles)")
        skipped = st.text_input("Skip next time (comma-separated)")
        submitted = st.form_submit_button("Save journal entry")
        if submitted and journal_body.strip():
            feedback_service.write_journal(
                body=journal_body.strip(),
                destination_label=label,
                entry_date=trip_def.start_date,
                enjoyed=[x.strip() for x in enjoyed.split(",") if x.strip()],
                skip=[x.strip() for x in skipped.split(",") if x.strip()],
            )
            st.success("Journal entry saved — this closes the feedback loop.")
    for entry in feedback_service.list_journal(destination_label=label)[:5]:
        with st.expander(f"Journal · {entry.get('entry_date') or entry.get('created_at')}"):
            st.write(entry.get("body"))
            if entry.get("enjoyed"):
                st.caption("Enjoyed: " + ", ".join(entry["enjoyed"]))

    if report.skip:
        with st.expander("What you can skip"):
            for index, rec in enumerate(report.skip):
                _render_recommendation(
                    rec,
                    feedback=feedback_service,
                    destination_label=label,
                    key_prefix=f"skip-{index}",
                )


if __name__ == "__main__":
    main()
