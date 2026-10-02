"""Preparation checklist and This Week focus topics."""

from __future__ import annotations

from typing import Any, Mapping

from travel_atlas.repository import AtlasRepository

from .checklist_templates import CHECKLIST_TEMPLATES, WEEK_FOCUS_BY_BAND


_BAND_ORDER = ("90", "60", "30", "7", "travel", "any")


def _bands_visible(active_band: str) -> set[str]:
    """Cumulative: at 30 days you still see 90 and 60 items."""
    if active_band == "any":
        return {"90", "any"}
    if active_band == "travel":
        return set(_BAND_ORDER)
    try:
        idx = _BAND_ORDER.index(active_band)
    except ValueError:
        return {"90", "any"}
    return set(_BAND_ORDER[: idx + 1]) | {"any"}


class PrepService:
    def __init__(self, repository: AtlasRepository) -> None:
        self.repository = repository

    def seed_checklist(self, trip_id: str) -> list[dict[str, Any]]:
        existing = {item["key"] for item in self.repository.list_checklist_items(trip_id)}
        for template in CHECKLIST_TEMPLATES:
            if template["key"] in existing:
                continue
            self.repository.upsert_checklist_item(
                trip_id=trip_id,
                key=template["key"],
                band=template["band"],
                title=template["title"],
                category=template["category"],
                due_offset_days=template.get("due_offset_days"),
                sort_index=template["sort_index"],
            )
        return self.repository.list_checklist_items(trip_id)

    def checklist_for_band(
        self, trip_id: str, prep_band: str
    ) -> list[dict[str, Any]]:
        self.seed_checklist(trip_id)
        visible = _bands_visible(prep_band)
        items = self.repository.list_checklist_items(trip_id)
        return [item for item in items if item["band"] in visible]

    def toggle(self, trip_id: str, key: str, completed: bool) -> dict[str, Any] | None:
        return self.repository.set_checklist_completed(trip_id, key, completed)

    def progress(self, trip_id: str, prep_band: str) -> dict[str, Any]:
        items = self.checklist_for_band(trip_id, prep_band)
        done = sum(1 for item in items if item.get("completed_at"))
        total = len(items)
        return {
            "done": done,
            "total": total,
            "prep_score": round(100.0 * done / total, 1) if total else 0.0,
            "items": items,
        }

    def this_week_topics(self, prep_band: str) -> list[str]:
        return list(WEEK_FOCUS_BY_BAND.get(prep_band) or WEEK_FOCUS_BY_BAND["any"])

    def open_missions(
        self, trip_id: str, prep_band: str, *, limit: int = 5
    ) -> list[dict[str, Any]]:
        items = self.checklist_for_band(trip_id, prep_band)
        open_items = [item for item in items if not item.get("completed_at")]
        missions = []
        for item in open_items[:limit]:
            missions.append(
                {
                    "key": item["key"],
                    "title": item["title"],
                    "category": item["category"],
                    "minutes": 4 if item["category"] == "language" else 3,
                }
            )
        return missions
