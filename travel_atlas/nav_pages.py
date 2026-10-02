"""Page paths for st.page_link / st.switch_page (relative to app_home.py).

Streamlit does not resolve bare url_path strings like \"create-trip\" —
use these script paths (or the st.Page objects from navigation).
"""

from __future__ import annotations

# Keys match url_path values registered in app_home.py
PAGES: dict[str, str] = {
    "today": "travel_atlas/today_streamlit.py",
    "command-center": "travel_atlas/command_center_streamlit.py",
    "create-trip": "travel_atlas/create_trip_streamlit.py",
    "alaska-aurora": "travel_atlas/alaska_aurora_streamlit.py",
    "add-reservation": "travel_atlas/add_reservation_streamlit.py",
    "add-flight": "travel_atlas/add_flight_streamlit.py",
    "planning": "travel_atlas/planning_streamlit.py",
    "trip-planner": "travel_atlas/trip_planner_streamlit.py",
    "destination-atlas": "travel_atlas/destination_explorer_streamlit.py",
    "culture": "travel_atlas/culture_streamlit.py",
    "language": "travel_atlas/language_streamlit.py",
    "health": "travel_atlas/health_streamlit.py",
    "itinerary": "travel_atlas/itinerary_streamlit.py",
    "atlas-explorer": "travel_atlas/app_streamlit.py",
    "pin-intelligence": "src_phase1/app_streamlit.py",
    "knowledge-review": "travel_atlas/knowledge_review_streamlit.py",
}


def page(key: str) -> str:
    return PAGES[key]
