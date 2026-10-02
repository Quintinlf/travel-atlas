"""Feedback loop, learned weights, themes, coverage, and pin backbone."""

from __future__ import annotations

import sys
import uuid
from datetime import date
from pathlib import Path

import pytest

_TRAVEL = Path(__file__).parent.parent
if str(_TRAVEL) not in sys.path:
    sys.path.insert(0, str(_TRAVEL))

from src_phase1.models import SavedLocation
from src_phase1.pin_repository import PinRepository
from travel_atlas.database import SCHEMA_VERSION, AtlasDatabase
from travel_atlas.knowledge_loader import load_bundled_knowledge
from travel_atlas.planning import PlanningEngine, default_planning_config
from travel_atlas.planning.learning import RATING_SCORES, apply_rating_to_weights
from travel_atlas.planning.themes import theme_for_date, themes_for_trip
from travel_atlas.repository import AtlasRepository
from travel_atlas.services.destination_itinerary import DestinationItineraryService
from travel_atlas.services.feedback_service import FeedbackService
from travel_atlas.services.itinerary_service import ItineraryService
from travel_atlas.services.knowledge_service import KnowledgeService
from travel_atlas.services.pin_service import PinService
from travel_atlas.services.preferences_service import PreferencesService
from travel_atlas.services.types import TripDefinition


def _insert_pin(path: Path, **kwargs: object) -> SavedLocation:
    pin = SavedLocation(
        id=str(kwargs.get("id", uuid.uuid4())),
        name=str(kwargs.get("name", "Place")),
        latitude=float(kwargs.get("latitude", 35.68)),
        longitude=float(kwargs.get("longitude", 139.76)),
        city=kwargs.get("city", "Tokyo"),  # type: ignore[arg-type]
        country=kwargs.get("country", "Japan"),  # type: ignore[arg-type]
        list_name="Want To Go",
        notes=kwargs.get("notes"),  # type: ignore[arg-type]
        category=kwargs.get("category"),  # type: ignore[arg-type]
        source_type="test",
        source_file="test.json",
        raw_json="{}",
        user_priority=int(kwargs["user_priority"]) if "user_priority" in kwargs else 5,
    )
    PinRepository(path).insert_pin(pin)
    return pin


def _make(tmp_path: Path):
    atlas_path = tmp_path / "atlas.db"
    pins_path = tmp_path / "pins.db"
    database = AtlasDatabase(atlas_path)
    database.migrate()
    assert database.connect().execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    repository = AtlasRepository(database)
    load_bundled_knowledge(repository)
    pin_service = PinService(pins_path)
    knowledge = KnowledgeService(repository)
    preferences = PreferencesService(repository)
    feedback = FeedbackService(repository)
    itinerary = DestinationItineraryService(pin_service, ItineraryService(pin_service))
    engine = PlanningEngine(
        pin_service=pin_service,
        knowledge_service=knowledge,
        preferences_service=preferences,
        itinerary_service=itinerary,
        config=default_planning_config(),
    )
    return engine, preferences, feedback, repository, pins_path


def test_schema_version_includes_feedback_tables(tmp_path: Path) -> None:
    _, _, _, repository, _ = _make(tmp_path)
    with repository.database.connect() as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "recommendation_rating" in tables
    assert "trip_journal_entry" in tables
    assert "planning_weight_state" in tables


def test_rating_updates_category_weights(tmp_path: Path) -> None:
    _, _, feedback, repository, pins_path = _make(tmp_path)
    pin = _insert_pin(pins_path, name="Tokyo National Museum", category="museum")
    before = repository.get_planning_weight_multipliers("local-default")
    assert before.get("museum_history", 1.0) == 1.0
    feedback.rate(
        subject_kind="pin",
        subject_id=pin.id,
        rating="loved",
        category="museum_history",
        destination_label="Japan",
    )
    after = repository.get_planning_weight_multipliers("local-default")
    assert after["museum_history"] > 1.0
    feedback.rate(
        subject_kind="pin",
        subject_id=pin.id,
        rating="skip",
        category="museum_history",
    )
    later = repository.get_planning_weight_multipliers("local-default")
    assert later["museum_history"] < after["museum_history"]


def test_journal_round_trip(tmp_path: Path) -> None:
    _, _, feedback, _, _ = _make(tmp_path)
    entry = feedback.write_journal(
        body="Ate incredible ramen and loved the science museum.",
        destination_label="Japan",
        entry_date="2026-08-01",
        enjoyed=["ramen", "science museum"],
        skip=["crowded souvenir street"],
    )
    assert entry["body"].startswith("Ate incredible")
    listed = feedback.list_journal(destination_label="Japan")
    assert len(listed) == 1
    assert "ramen" in listed[0]["enjoyed"]


def test_saved_pins_outrank_generic_claims(tmp_path: Path) -> None:
    engine, preferences, _, _, pins_path = _make(tmp_path)
    preferences.update_preferences(["museum_history"], "balanced", {}, [])
    _insert_pin(
        pins_path,
        name="Tokyo National Museum",
        category="museum",
        notes="Long note about astronomy exhibits.\nSecond line.\nThird.",
        user_priority=9,
    )
    report = engine.plan(
        destination_kind="country",
        destination_label="Japan",
        trip=TripDefinition(
            destination_kind="country",
            destination_label="Japan",
            day_count=3,
            start_date="2026-08-03",  # Monday
            pace="medium",
            energy="medium",
        ),
    )
    assert report.pin_backbone
    assert report.pin_backbone[0]["title"] == "Tokyo National Museum"
    assert report.experiences[0].title == "Tokyo National Museum"
    assert report.experiences[0].priority_tier == "must_visit"
    assert report.experiences[0].match_breakdown


def test_weekly_themes_and_coverage(tmp_path: Path) -> None:
    engine, preferences, _, _, pins_path = _make(tmp_path)
    preferences.update_preferences(
        ["museum_history", "market_food", "nature_gardens"],
        "balanced",
        {},
        [],
        preferences={"favorite_foods": ["ramen"], "museum_types": ["astronomy"]},
    )
    _insert_pin(pins_path, name="Tsukiji Outer Market", category="food market")
    _insert_pin(
        pins_path,
        name="Science Museum",
        category="museum",
        latitude=35.70,
        longitude=139.75,
        user_priority=8,
    )
    _insert_pin(
        pins_path,
        name="Shinjuku Gyoen",
        category="park garden",
        latitude=35.685,
        longitude=139.71,
    )
    report = engine.plan(
        destination_kind="country",
        destination_label="Japan",
        trip=TripDefinition(
            destination_kind="country",
            destination_label="Japan",
            day_count=3,
            start_date="2026-08-03",
            energy="medium",
        ),
    )
    assert report.themes
    assert report.themes[0]["theme_key"] == "body_nourishment"  # Monday
    assert report.coverage["overall"] > 0
    assert "Food" in report.coverage["per_interest"] or "Museums" in report.coverage["per_interest"]
    assert report.food_subsystem.get("facets")
    assert any(day.get("theme_title") for day in report.itinerary)


def test_skip_rating_hides_from_active_experiences(tmp_path: Path) -> None:
    engine, preferences, feedback, _, pins_path = _make(tmp_path)
    preferences.update_preferences(["museum_history"], "balanced", {}, [])
    pin = _insert_pin(pins_path, name="Skip This Museum", category="museum")
    _insert_pin(
        pins_path,
        name="Keep This Museum",
        category="history museum",
        latitude=35.70,
        longitude=139.75,
    )
    feedback.rate(
        subject_kind="pin",
        subject_id=pin.id,
        rating="skip",
        category="museum_history",
        destination_label="Japan",
    )
    report = engine.plan(
        destination_kind="country",
        destination_label="Japan",
    )
    titles = [r.title for r in report.experiences]
    assert "Skip This Museum" not in titles
    assert any(r.title == "Skip This Museum" for r in report.skip)


def test_theme_for_saturday_is_major_day() -> None:
    # 2026-08-08 is a Saturday
    theme = theme_for_date(date(2026, 8, 8))
    assert theme.key == "organized_saturday"
    trip_themes = themes_for_trip(date(2026, 8, 3), 7)
    assert trip_themes[5]["theme_key"] == "organized_saturday"


def test_rating_scores_defined() -> None:
    assert RATING_SCORES["loved"] == 1.0
    assert RATING_SCORES["skip"] == -1.0


def test_existing_planning_smoke(tmp_path: Path) -> None:
    engine, preferences, _, _, pins_path = _make(tmp_path)
    preferences.update_preferences(["market_food"], "balanced", {}, [])
    _insert_pin(pins_path, name="Market Stall", category="food market")
    report = engine.plan(destination_kind="country", destination_label="Japan")
    assert report.summary
    assert report.exploration_mix["personalized"] == 0.9
    gems = engine.answer(
        "coverage",
        destination_kind="country",
        destination_label="Japan",
    )
    assert "overall" in gems
