"""Personalized trip planning engine (read-only reasoning layer).

Reads atlas.db knowledge, travel_pins.db, user preferences, and trip
definitions. Never writes to any database — persistence belongs to
PreferencesService / TripPlanService.
"""

from .config import default_planning_config, load_planning_config
from .engine import PlanningEngine, profile_from_dict
from .queries import QUESTION_KEYS

__all__ = [
    "PlanningEngine",
    "QUESTION_KEYS",
    "default_planning_config",
    "load_planning_config",
    "profile_from_dict",
]
