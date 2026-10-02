"""Checklist templates keyed by preparation band (days until departure)."""

from __future__ import annotations

from typing import TypedDict


class ChecklistTemplate(TypedDict):
    key: str
    band: str
    title: str
    category: str
    due_offset_days: int | None
    sort_index: int


# Bands: show items whose band is active or earlier (cumulative prep).
CHECKLIST_TEMPLATES: list[ChecklistTemplate] = [
    # 90-day band
    {"key": "passport", "band": "90", "title": "Check passport validity", "category": "docs", "due_offset_days": 90, "sort_index": 10},
    {"key": "book_flight_edi", "band": "90", "title": "Book inbound flight to Edinburgh (EDI)", "category": "reservations", "due_offset_days": 90, "sort_index": 12},
    {"key": "book_car_edi", "band": "90", "title": "Book EDI rental car (Day 1 pickup / Day 2 drop)", "category": "reservations", "due_offset_days": 88, "sort_index": 14},
    {"key": "book_hotel_dundee", "band": "90", "title": "Book Dundee hotel (1 night)", "category": "reservations", "due_offset_days": 85, "sort_index": 16},
    {"key": "book_hotel_glasgow", "band": "90", "title": "Book Glasgow hotel (2 nights)", "category": "reservations", "due_offset_days": 85, "sort_index": 18},
    {"key": "visa", "band": "90", "title": "Confirm visa / entry requirements", "category": "docs", "due_offset_days": 90, "sort_index": 20},
    {"key": "overview", "band": "90", "title": "Read destination overview", "category": "learn", "due_offset_days": 90, "sort_index": 30},
    {"key": "language_basics", "band": "90", "title": "Learn 5 basic phrases", "category": "language", "due_offset_days": 90, "sort_index": 40},
    {"key": "cities", "band": "90", "title": "Review major cities / regions", "category": "learn", "due_offset_days": 85, "sort_index": 50},
    # 60-day
    {"key": "neighborhoods", "band": "60", "title": "Explore key neighborhoods", "category": "learn", "due_offset_days": 60, "sort_index": 60},
    {"key": "transit_systems", "band": "60", "title": "Study local transit systems", "category": "transit", "due_offset_days": 60, "sort_index": 70},
    {"key": "food_culture", "band": "60", "title": "Learn food culture basics", "category": "food", "due_offset_days": 55, "sort_index": 80},
    {"key": "save_restaurant", "band": "60", "title": "Save one restaurant or market", "category": "food", "due_offset_days": 50, "sort_index": 90},
    {"key": "budget_refine", "band": "60", "title": "Refine trip budget categories", "category": "budget", "due_offset_days": 50, "sort_index": 100},
    {"key": "packing_draft", "band": "60", "title": "Draft packing list", "category": "packing", "due_offset_days": 45, "sort_index": 110},
    # 30-day
    {"key": "itinerary_refine", "band": "30", "title": "Refine daily itinerary", "category": "plan", "due_offset_days": 30, "sort_index": 120},
    {"key": "museum_reserve", "band": "30", "title": "Reserve museum / major attraction", "category": "reservations", "due_offset_days": 28, "sort_index": 130},
    {"key": "restaurant_choices", "band": "30", "title": "Choose priority restaurants", "category": "food", "due_offset_days": 25, "sort_index": 140},
    {"key": "weather_check", "band": "30", "title": "Review seasonal weather expectations", "category": "weather", "due_offset_days": 25, "sort_index": 150},
    {"key": "currency", "band": "30", "title": "Prepare currency / payment plan", "category": "money", "due_offset_days": 20, "sort_index": 160},
    {"key": "safety", "band": "30", "title": "Read safety reminders", "category": "safety", "due_offset_days": 20, "sort_index": 170},
    # 7-day
    {"key": "offline_maps", "band": "7", "title": "Download offline maps", "category": "transit", "due_offset_days": 7, "sort_index": 180},
    {"key": "emergency_contacts", "band": "7", "title": "Save emergency contacts", "category": "safety", "due_offset_days": 7, "sort_index": 190},
    {"key": "flight_confirm", "band": "7", "title": "Confirm flights", "category": "reservations", "due_offset_days": 5, "sort_index": 200},
    {"key": "hotel_confirm", "band": "7", "title": "Confirm hotels", "category": "reservations", "due_offset_days": 5, "sort_index": 210},
    {"key": "packing_verify", "band": "7", "title": "Verify packing list", "category": "packing", "due_offset_days": 3, "sort_index": 220},
    {"key": "language_review", "band": "7", "title": "Final language review", "category": "language", "due_offset_days": 2, "sort_index": 230},
]

WEEK_FOCUS_BY_BAND: dict[str, list[str]] = {
    "90": ["Language", "Geography", "History", "Trip checklist", "Passport"],
    "60": ["Neighborhoods", "Transit", "Cuisine", "Packing", "Budget"],
    "30": ["Itinerary", "Reservations", "Weather", "Currency", "Safety"],
    "7": ["Offline maps", "Confirmations", "Packing", "Language review", "Emergency"],
    "travel": ["Today's plan", "Energy", "Weather", "Nearby food"],
    "any": ["Language", "Neighborhoods", "Transit", "Cuisine"],
}

LIFECYCLE_STAGES = (
    "idea",
    "planning",
    "committed",
    "preparation",
    "traveling",
    "completed",
    "remembered",
)

# Legacy stage names from Phase 3A → foundation stages.
LEGACY_STAGE_MAP = {
    "dream": "idea",
    "plan": "planning",
    "prepare": "preparation",
    "travel": "traveling",
    "reflect": "completed",
    "learn": "completed",
    "completed": "completed",
}
