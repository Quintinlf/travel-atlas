"""Django-neutral application services for personalized Travel Atlas features."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .annotation_service import AnnotationService
from .budget_board_service import BudgetBoardService
from .destination_itinerary import DestinationItineraryService
from .destination_service import DestinationService
from .feedback_service import FeedbackService
from .knowledge_service import KnowledgeService
from .language_service import LanguageService
from .learning_queue_service import LearningQueueService
from .lifecycle_service import LifecycleService
from .itinerary_service import ItineraryService
from .logistics_service import LogisticsService
from .mode_service import ModeService
from .notes_service import NotesService
from .photo_service import PhotoService
from .pin_service import PinService
from .planning_service import PlanningService
from .preferences_service import PreferencesService
from .prep_service import PrepService
from .region_map import region_map_image_url
from .regional_defaults import get_regional_defaults, recommendation_summary
from .reservation_service import ReservationService
from .seasonal_context_service import SeasonalContextService
from .substances_service import SubstancesService
from .today_service import TodayService
from .travel_pack_service import TravelPackService
from .traveler_docs import TravelerDocsService, expand_trip_regions
from .traveler_service import TravelerService
from .trip_service import TripPlanService

if TYPE_CHECKING:
    from travel_atlas.planning import PlanningEngine as PlanningEngine

__all__ = [
    "AnnotationService",
    "BudgetBoardService",
    "DestinationItineraryService",
    "DestinationService",
    "FeedbackService",
    "ItineraryService",
    "KnowledgeService",
    "LanguageService",
    "LearningQueueService",
    "LifecycleService",
    "LogisticsService",
    "ModeService",
    "NotesService",
    "PhotoService",
    "PinService",
    "PlanningEngine",
    "PlanningService",
    "PreferencesService",
    "PrepService",
    "get_regional_defaults",
    "recommendation_summary",
    "region_map_image_url",
    "ReservationService",
    "SeasonalContextService",
    "SubstancesService",
    "TodayService",
    "TravelPackService",
    "TravelerDocsService",
    "TravelerService",
    "expand_trip_regions",
    "TripPlanService",
]


def __getattr__(name: str):
    if name == "PlanningEngine":
        from travel_atlas.planning import PlanningEngine as _PlanningEngine

        return _PlanningEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
