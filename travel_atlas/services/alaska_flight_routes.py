"""LAX–Fairbanks routing facts for UI and booking briefings."""

from __future__ import annotations

from typing import Any

from travel_atlas.services.alaska_bases import HOME_AIRPORT

LAX_FAI_NONSTOP = False
LAX_ANC_NONSTOP = True
ANC_FAI_NONSTOP = True

TYPICAL_HUBS = ("SEA", "PDX", "ANC", "DEN", "MSP")
TYPICAL_DURATION_HOURS = "7–8"
LAX_ANC_DURATION = "~5h25m"
ANC_FAI_DURATION = "~1h"

FLIGHT_BENCHMARK_PER_ADULT_LOW = 379
FLIGHT_BENCHMARK_PER_ADULT_HIGH = 415


def route_briefing(*, adults: int = 2) -> dict[str, Any]:
    """Shared routing context for Streamlit callouts and HTML briefings."""
    low = FLIGHT_BENCHMARK_PER_ADULT_LOW
    high = FLIGHT_BENCHMARK_PER_ADULT_HIGH
    mid = (low + high) // 2
    party = max(1, adults)
    return {
        "origin": HOME_AIRPORT,
        "destination": "FAI",
        "lax_fai_nonstop": LAX_FAI_NONSTOP,
        "lax_anc_nonstop": LAX_ANC_NONSTOP,
        "anc_fai_nonstop": ANC_FAI_NONSTOP,
        "typical_hubs": list(TYPICAL_HUBS),
        "typical_duration_hours": TYPICAL_DURATION_HOURS,
        "lax_anc_duration": LAX_ANC_DURATION,
        "anc_fai_duration": ANC_FAI_DURATION,
        "flight_benchmark_per_adult": (low, high),
        "flight_benchmark_per_adult_mid": mid,
        "flight_benchmark_party_low": low * party,
        "flight_benchmark_party_high": high * party,
        "flight_benchmark_party_mid": mid * party,
        "no_nonstop_summary": (
            f"No nonstop {HOME_AIRPORT}→Fairbanks — every option has at least one layover. "
            "This is expected."
        ),
        "hubs_summary": (
            f"Common connection cities: {', '.join(TYPICAL_HUBS)}. "
            f"Total travel time is often {TYPICAL_DURATION_HOURS} hours gate-to-gate."
        ),
        "anc_footnote": (
            f"{HOME_AIRPORT}→Anchorage is a daily nonstop ({LAX_ANC_DURATION}); "
            f"Anchorage→Fairbanks is a short nonstop hop ({ANC_FAI_DURATION}). "
            "Some LAX→FAI tickets connect through Anchorage on one itinerary."
        ),
        "no_red_eye_summary": (
            "Avoid red-eyes: book a morning or early-afternoon departure from FAI on your "
            "leave day. Prefer daytime connections in Seattle, Portland, or Anchorage — "
            "land LAX same evening, not after midnight."
        ),
    }
