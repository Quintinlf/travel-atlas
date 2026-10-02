"""Tests for the personalized PlanningEngine and schema v8 personalization fields."""

from __future__ import annotations

import sys
import uuid
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
from travel_atlas.planning.scoring import score_batch, score_signals
from travel_atlas.planning.signals import hidden_gem, interest_tag_overlap
from travel_atlas.repository import AtlasRepository
from travel_atlas.services.destination_itinerary import DestinationItineraryService
from travel_atlas.services.itinerary_service import ItineraryService
from travel_atlas.services.knowledge_service import KnowledgeService
from travel_atlas.services.pin_service import PinService
from travel_atlas.services.preferences_service import PreferencesService
from travel_atlas.services.trip_service import TripPlanService
from travel_atlas.services.types import TripDefinition, UserProfileView


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


def _make_engine(tmp_path: Path) -> tuple[PlanningEngine, PreferencesService, AtlasRepository, Path]:
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
    itinerary = DestinationItineraryService(pin_service, ItineraryService(pin_service))
    engine = PlanningEngine(
        pin_service=pin_service,
        knowledge_service=knowledge,
        preferences_service=preferences,
        itinerary_service=itinerary,
        config=default_planning_config(),
    )
    return engine, preferences, repository, pins_path


def test_preferences_json_round_trip_without_schema_change(tmp_path: Path) -> None:
    _, preferences, repository, _ = _make_engine(tmp_path)
    preferences.merge_preference_bag(
        {
            "favorite_foods": ["ramen", "omakase"],
            "museum_types": ["science", "astronomy"],
            "budget_tendency": "moderate",
            "custom_future_key": {"nested": True},
        }
    )
    profile = repository.get_profile("local-default")
    assert profile["preferences"]["favorite_foods"] == ["ramen", "omakase"]
    assert profile["preferences"]["custom_future_key"] == {"nested": True}
    preferences.merge_preference_bag({"nightlife_interest": True})
    profile = repository.get_profile("local-default")
    assert profile["preferences"]["favorite_foods"] == ["ramen", "omakase"]
    assert profile["preferences"]["nightlife_interest"] is True


def test_trip_definition_json_persists_pace_and_budget(tmp_path: Path) -> None:
    engine, _, repository, pins_path = _make_engine(tmp_path)
    _insert_pin(pins_path, name="Tokyo Station", category="train station")
    itinerary = DestinationItineraryService(
        engine.pin_service, ItineraryService(engine.pin_service)
    )
    trips = TripPlanService(repository, itinerary)
    trip = trips.create_trip(
        name="Japan slow",
        destinations=[{"kind": "country", "label": "Japan", "day_count": 4}],
        definition={"pace": "slow", "budget": 1200, "travel_style": "cultural"},
    )
    loaded = trips.get_trip(trip["id"])
    assert loaded["definition"]["pace"] == "slow"
    assert loaded["definition"]["budget"] == 1200


def test_scoring_is_deterministic(tmp_path: Path) -> None:
    weights = default_planning_config()["weights"]
    rows = [
        {"interest_tag_overlap": 0.9, "pin_affinity": 0.2, "atlas_claim_relevance": 0.1,
         "saved_pin_boost": 1.0, "pace_fit": 0.8, "budget_fit": 0.7,
         "hidden_gem": 0.4, "transport_fit": 0.5},
        {"interest_tag_overlap": 0.1, "pin_affinity": 0.1, "atlas_claim_relevance": 0.0,
         "saved_pin_boost": 0.0, "pace_fit": 0.5, "budget_fit": 0.5,
         "hidden_gem": 0.1, "transport_fit": 0.4},
    ]
    a = score_batch(rows, weights)
    b = score_batch(rows, weights)
    assert a == b
    assert a[0] > a[1]
    assert score_signals(rows[0], weights) == score_signals(rows[0], weights)


def test_interest_overlap_ranks_preferred_tags(tmp_path: Path) -> None:
    engine, preferences, _, pins_path = _make_engine(tmp_path)
    preferences.update_preferences(
        ["museum_history"],
        "balanced",
        {},
        [],
        preferences={"museum_types": ["science", "astronomy"]},
    )
    _insert_pin(
        pins_path,
        name="Tokyo National Museum",
        category="museum",
        notes="Deep notes about history exhibits and astronomy wing.\nLine two.\nLine three.",
    )
    _insert_pin(
        pins_path,
        name="Random Convenience Store",
        category="shop",
        notes=None,
        latitude=35.69,
        longitude=139.77,
    )
    report = engine.plan(
        destination_kind="country",
        destination_label="Japan",
        trip=TripDefinition(
            destination_kind="country",
            destination_label="Japan",
            day_count=2,
            pace="medium",
        ),
    )
    titles = [r.title for r in report.experiences]
    assert "Tokyo National Museum" in titles
    museum = next(r for r in report.experiences if "Museum" in r.title)
    store = next((r for r in report.experiences if "Convenience" in r.title), None)
    if store:
        assert museum.score >= store.score
    assert museum.signals["interest_tag_overlap"] > 0
    assert "museum" in museum.explanation.lower() or "interest" in museum.explanation.lower()


def test_hidden_gem_prefers_high_fit_low_popularity() -> None:
    high = hidden_gem(interest_overlap=0.9, peer_count=1, has_long_note=True)
    low = hidden_gem(interest_overlap=0.2, peer_count=20, has_long_note=False)
    assert high > low


def test_interest_tag_overlap_unit() -> None:
    profile = UserProfileView(
        user_key="u",
        interests=("museum_history",),
        travel_style="balanced",
        accommodation_preferences={},
        learning_goals=(),
        preferences={"historical_interests": ["astronomy"]},
    )
    assert interest_tag_overlap(["museum_history"], profile) > interest_tag_overlap(
        ["transport"], profile
    )


def test_plan_returns_required_sections(tmp_path: Path) -> None:
    engine, preferences, _, pins_path = _make_engine(tmp_path)
    preferences.update_preferences(["market_food", "museum_history"], "balanced", {}, [])
    _insert_pin(pins_path, name="Tsukiji Outer Market", category="food market")
    _insert_pin(
        pins_path,
        name="Science Museum",
        category="museum",
        latitude=35.70,
        longitude=139.75,
    )
    report = engine.plan(
        destination_kind="country",
        destination_label="Japan",
        trip=TripDefinition(
            destination_kind="country",
            destination_label="Japan",
            day_count=3,
            budget=900,
            pace="slow",
        ),
    )
    assert report.summary
    assert isinstance(report.experiences, tuple)
    assert isinstance(report.food, tuple)
    assert isinstance(report.museums, tuple)
    assert isinstance(report.transportation, tuple)
    assert isinstance(report.itinerary, tuple)
    assert "sample_experiences_cost" in report.budget
    assert isinstance(report.packing, tuple)
    assert len(report.packing) >= 1


def test_engine_does_not_mutate_claims(tmp_path: Path) -> None:
    engine, _, repository, pins_path = _make_engine(tmp_path)
    _insert_pin(pins_path, name="Meiji Shrine", category="shrine")
    area_id = "country-jp"
    before = repository.list_claims(area_id)
    before_ids = {c["id"] for c in before}
    engine.plan(
        destination_kind="country",
        destination_label="Japan",
        user_key="local-default",
    )
    after = repository.list_claims(area_id)
    assert {c["id"] for c in after} == before_ids
    assert len(after) == len(before)


def test_answer_question_keys(tmp_path: Path) -> None:
    engine, preferences, _, pins_path = _make_engine(tmp_path)
    preferences.update_preferences(["museum_history"], "balanced", {}, [])
    _insert_pin(pins_path, name="Edo Museum", category="history museum")
    gems = engine.answer(
        "hidden_gems",
        destination_kind="country",
        destination_label="Japan",
    )
    assert isinstance(gems, tuple)
    food = engine.answer(
        "food",
        destination_kind="country",
        destination_label="Japan",
    )
    assert isinstance(food, tuple)
    with pytest.raises(ValueError):
        engine.answer(
            "not_a_real_question",
            destination_kind="country",
            destination_label="Japan",
        )
