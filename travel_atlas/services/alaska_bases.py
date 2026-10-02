"""Stay-put Alaska aurora base — Fairbanks only. Home airport is Los Angeles (LAX)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

HOME_CITY = "Los Angeles"
HOME_AIRPORT = "LAX"
DEFAULT_BASE_KEY = "fairbanks"
OPENER_VERSION = "stayput_v1"

# Legacy trip definitions may still reference these keys — all resolve to Fairbanks.
_LEGACY_BASE_KEYS = frozenset({"healy", "anchorage", "talkeetna", "coldfoot"})


@dataclass(frozen=True)
class AlaskaAuroraBase:
    key: str
    label: str
    airport: str
    latitude: float
    longitude: float
    typical_kp_visible: float
    cost_band: str
    darker_skies_note: str
    notes: str
    hotel_query: str
    drive_hours_from_airport: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


FAIRBANKS_BASE = AlaskaAuroraBase(
    key="fairbanks",
    label="Fairbanks",
    airport="FAI",
    latitude=64.8378,
    longitude=-147.7164,
    typical_kp_visible=2.0,
    cost_band="mid",
    darker_skies_note=(
        "Stay in town or drive ~1h to Chena Hot Springs for darker skies — "
        "same hotel, one night outing."
    ),
    notes=(
        "Best realistic aurora odds for a 3–4 day LAX trip. Fly LAX→FAI, "
        "stay put in Fairbanks or Chena for every night."
    ),
    hotel_query="Fairbanks, Alaska",
    drive_hours_from_airport=0.3,
)

ALASKA_AURORA_BASES: tuple[AlaskaAuroraBase, ...] = (FAIRBANKS_BASE,)

_BY_KEY = {base.key: base for base in ALASKA_AURORA_BASES}


def get_base(key: str) -> AlaskaAuroraBase:
    normalized = (key or DEFAULT_BASE_KEY).strip().casefold()
    if normalized in _BY_KEY:
        return _BY_KEY[normalized]
    if normalized in _LEGACY_BASE_KEYS:
        return FAIRBANKS_BASE
    raise ValueError(f"Unknown Alaska aurora base: {key}")


def list_base_keys() -> list[str]:
    return [base.key for base in ALASKA_AURORA_BASES]
