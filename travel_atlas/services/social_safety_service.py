"""Per-region social scene + street-safety notes (curated seed + State Dept)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from travel_atlas.providers.state_dept import StateDeptSafetyProvider

_DATA = (
    Path(__file__).resolve().parent.parent / "data" / "regional_social_safety.json"
)


class SocialSafetyService:
    def __init__(self, safety: StateDeptSafetyProvider | None = None) -> None:
        self.safety = safety or StateDeptSafetyProvider()
        self._seed = self._load()

    def _load(self) -> dict[str, Any]:
        if not _DATA.is_file():
            return {"_disclaimer": "", "regions": {}}
        return json.loads(_DATA.read_text(encoding="utf-8"))

    def for_destination(self, destination: str) -> dict[str, Any]:
        key = destination.replace(" (UK)", "").strip()
        regions = self._seed.get("regions") or {}
        block = dict(regions.get(key) or regions.get(key.title()) or {})
        api_label = (
            "United Kingdom"
            if key in {"England", "Scotland", "Wales", "Northern Ireland"}
            else key
        )
        live = self.safety.advisories(destination=api_label)
        payload = getattr(live, "payload", None) or {}
        note = None
        for item in payload.get("items") or []:
            title = (item.get("title") or "").lower()
            if any(w in title for w in ("law", "crime", "safety", "security")):
                note = {
                    "title": item.get("title") or "State Dept",
                    "body": (item.get("body") or "")[:2500],
                }
                break

        return {
            "destination": key,
            "disclaimer": self._seed.get("_disclaimer") or "",
            "lgbt_climate": block.get("lgbt_climate"),
            "gay_scene": block.get("gay_scene"),
            "straight_scene": block.get("straight_scene"),
            "bring_someone_back": block.get("bring_someone_back"),
            "hookup_scams": list(block.get("hookup_scams") or []),
            "common_scams": list(block.get("common_scams") or []),
            "street_crime": block.get("street_crime"),
            "stay_safe": list(block.get("stay_safe") or []),
            "emergency": block.get("emergency") or "112",
            "state_dept_note": note,
            "links": getattr(live, "links", None) or {},
        }
