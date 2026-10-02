"""Load curated regional preference defaults for Planning UI."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_DATA = Path(__file__).resolve().parent.parent / "data" / "regional_preferences.json"

_LABEL_ALIASES = {
    "england (uk)": "England",
    "scotland (uk)": "Scotland",
    "wales (uk)": "Wales",
    "northern ireland (uk)": "Northern Ireland",
    "united kingdom": "England",
    "uk": "England",
    "republic of ireland": "Ireland",
}


@lru_cache(maxsize=1)
def _load() -> dict[str, Any]:
    if not _DATA.is_file():
        return {}
    return json.loads(_DATA.read_text(encoding="utf-8"))


def resolve_region_key(destination_label: str) -> str | None:
    raw = destination_label.strip()
    data = _load()
    if raw in data:
        return raw
    alias = _LABEL_ALIASES.get(raw.lower())
    if alias and alias in data:
        return alias
    title = raw.split("(")[0].strip().title()
    if title in data:
        return title
    return None


def get_regional_defaults(destination_label: str) -> dict[str, Any] | None:
    key = resolve_region_key(destination_label)
    if not key:
        return None
    return dict(_load()[key])


def recommendation_summary(destination_label: str) -> dict[str, Any] | None:
    defaults = get_regional_defaults(destination_label)
    if not defaults:
        return None
    return {
        "budget_tendency": defaults.get("budget_tendency"),
        "transportation_preferences": list(defaults.get("transportation_preferences") or []),
        "suggested_days": defaults.get("suggested_days"),
        "region_key": resolve_region_key(destination_label),
    }
