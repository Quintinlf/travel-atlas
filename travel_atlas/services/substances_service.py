"""Curated regional substances notes + State Dept local-laws supplement."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from travel_atlas.providers.state_dept import StateDeptSafetyProvider
from travel_atlas.services.regional_defaults import resolve_region_key

_DATA = Path(__file__).resolve().parent.parent / "data" / "regional_substances.json"


@lru_cache(maxsize=1)
def _load() -> dict[str, Any]:
    if not _DATA.is_file():
        return {}
    return json.loads(_DATA.read_text(encoding="utf-8"))


class SubstancesService:
    def __init__(self, safety: StateDeptSafetyProvider | None = None) -> None:
        self.safety = safety or StateDeptSafetyProvider()

    def for_destination(self, destination_label: str) -> dict[str, Any]:
        data = _load()
        key = resolve_region_key(destination_label) or destination_label
        region = (data.get("regions") or {}).get(key) or {}
        live = self.safety.advisories(destination=key if key != "England" else "United Kingdom")
        local_laws = None
        if isinstance(live.payload, dict):
            local_laws = next(
                (
                    item
                    for item in live.payload.get("items") or []
                    if item.get("kind") == "local_laws_and_special_circumstances"
                ),
                None,
            )
        return {
            "region": key,
            "disclaimer": data.get("_disclaimer"),
            "historical_caution": data.get("historical_caution"),
            "psychoactives": list(region.get("psychoactives") or []),
            "spirits": list(region.get("spirits") or []),
            "state_dept_local_laws": local_laws,
            "links": live.links,
            "live_status": live.status,
        }
