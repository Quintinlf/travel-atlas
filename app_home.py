"""
Unified local UI for the travel project.

Run from the travel_code directory (parent of this folder):

    streamlit run travel/app_home.py

Or use run_local.ps1 / run_local.sh in this folder.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import streamlit as st

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from travel_atlas.env_loader import load_travel_env

load_travel_env()

# Streamlit keeps imported modules alive across reruns; reload Phase 1 models
# after schema changes (e.g. the ``region`` column) so pages never use a stale class.
import src_phase1.geo_grouping as _geo_grouping
import src_phase1.models as _phase1_models
import src_phase1.pin_repository as _phase1_pin_repository
import travel_atlas.providers.astrology as _astrology
import travel_atlas.services.astro_helper as _astro_helper
import travel_atlas.services.traveler_docs as _traveler_docs
import travel_atlas.services.trip_map as _trip_map

importlib.reload(_phase1_models)
importlib.reload(_geo_grouping)
importlib.reload(_phase1_pin_repository)
importlib.reload(_traveler_docs)
importlib.reload(_astrology)
importlib.reload(_astro_helper)
importlib.reload(_trip_map)

from travel_atlas.database import AtlasDatabase
from travel_atlas.repository import AtlasRepository
from travel_atlas.services.destination_itinerary import DestinationItineraryService
from travel_atlas.services.itinerary_service import ItineraryService
from travel_atlas.services.lifecycle_service import LifecycleService
from travel_atlas.services.mode_service import ModeService
from travel_atlas.services.pin_service import PinService
from travel_atlas.services.trip_service import TripPlanService

st.set_page_config(
    page_title="Travel Atlas",
    page_icon="✈️",
    layout="wide",
    initial_sidebar_state="expanded",
)

USER_KEY = "local-default"


def _resolve_default_path() -> str:
    """Pick default nav page from application mode (Today only if committed)."""
    try:
        database = AtlasDatabase(_ROOT / "atlas.db")
        database.migrate()
        repository = AtlasRepository(database)
        pin_service = PinService(
            _ROOT / "travel_pins.db", atlas_database_path=_ROOT / "atlas.db"
        )
        itinerary = DestinationItineraryService(
            pin_service, ItineraryService(pin_service)
        )
        trip_service = TripPlanService(repository, itinerary)
        mode = ModeService(repository, trip_service, LifecycleService(repository))
        page = mode.resolve(USER_KEY).get("default_page") or "destination-atlas"
    except Exception:
        page = "destination-atlas"
    allowed = {"today", "command-center", "destination-atlas", "trip-planner"}
    return page if page in allowed else "destination-atlas"


_default = _resolve_default_path()

# Build page specs first; set default=True on exactly one page.
_page_specs = [
    ("today", _ROOT / "travel_atlas" / "today_streamlit.py", "Today", "☀️", "today"),
    (
        "command-center",
        _ROOT / "travel_atlas" / "command_center_streamlit.py",
        "Command Center",
        "🎯",
        "command-center",
    ),
    (
        "create-trip",
        _ROOT / "travel_atlas" / "create_trip_streamlit.py",
        "Create trip",
        "➕",
        "create-trip",
    ),
    (
        "alaska-aurora",
        _ROOT / "travel_atlas" / "alaska_aurora_streamlit.py",
        "Alaska aurora",
        "🌌",
        "alaska-aurora",
    ),
    (
        "add-reservation",
        _ROOT / "travel_atlas" / "add_reservation_streamlit.py",
        "Add hotel",
        "🏨",
        "add-reservation",
    ),
    (
        "add-flight",
        _ROOT / "travel_atlas" / "add_flight_streamlit.py",
        "Add flight",
        "✈️",
        "add-flight",
    ),
    (
        "planning",
        _ROOT / "travel_atlas" / "planning_streamlit.py",
        "Planning",
        "✨",
        "planning",
    ),
    (
        "trip-planner",
        _ROOT / "travel_atlas" / "trip_planner_streamlit.py",
        "Trip Planner",
        "🗓️",
        "trip-planner",
    ),
    (
        "destination-atlas",
        _ROOT / "travel_atlas" / "destination_explorer_streamlit.py",
        "Destination Atlas",
        "🌍",
        "destination-atlas",
    ),
    (
        "culture",
        _ROOT / "travel_atlas" / "culture_streamlit.py",
        "Culture",
        "🎭",
        "culture",
    ),
    (
        "language",
        _ROOT / "travel_atlas" / "language_streamlit.py",
        "Language",
        "🗣️",
        "language",
    ),
    (
        "health",
        _ROOT / "travel_atlas" / "health_streamlit.py",
        "Health & medical",
        "🩺",
        "health",
    ),
    (
        "itinerary",
        _ROOT / "travel_atlas" / "itinerary_streamlit.py",
        "Itinerary",
        "📋",
        "itinerary",
    ),
    (
        "atlas-explorer",
        _ROOT / "travel_atlas" / "app_streamlit.py",
        "Atlas Explorer",
        "🧭",
        "atlas-explorer",
    ),
    (
        "pin-intelligence",
        _ROOT / "src_phase1" / "app_streamlit.py",
        "Pin Intelligence",
        "🗺️",
        "pin-intelligence",
    ),
    (
        "knowledge-review",
        _ROOT / "travel_atlas" / "knowledge_review_streamlit.py",
        "Knowledge Review",
        "📚",
        "knowledge-review",
    ),
]

_pages = []
for key, path, title, icon, url_path in _page_specs:
    kwargs = {
        "title": title,
        "icon": icon,
        "url_path": url_path,
    }
    if key == _default:
        kwargs["default"] = True
    _pages.append(st.Page(path, **kwargs))

pg = st.navigation(_pages)
pg.run()
