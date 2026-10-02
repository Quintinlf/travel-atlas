"""Confidence-aware trip budget board."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from travel_atlas.repository import AtlasRepository
from travel_atlas.services.types import Recommendation

BUDGET_CATEGORIES = (
    "hotels",
    "transportation",
    "food",
    "museums",
    "shopping",
    "experiences",
    "emergency_buffer",
)

_CATEGORY_FROM_REC = {
    "market_food": "food",
    "museum_history": "museums",
    "shopping": "shopping",
    "transport": "transportation",
    "accommodation": "hotels",
    "nature_gardens": "experiences",
    "temple_spirituality": "experiences",
    "nightlife": "experiences",
    "general_travel": "experiences",
}


class BudgetBoardService:
    def __init__(self, repository: AtlasRepository) -> None:
        self.repository = repository

    def seed_from_plan(
        self,
        trip_id: str,
        *,
        trip_budget: float | None,
        recommendations: Sequence[Recommendation] = (),
        day_count: int = 3,
    ) -> list[dict[str, Any]]:
        existing = self.repository.list_budget_lines(trip_id)
        if existing:
            return existing

        totals: dict[str, float] = {c: 0.0 for c in BUDGET_CATEGORIES}
        for rec in recommendations:
            cat = _CATEGORY_FROM_REC.get(rec.category, "experiences")
            totals[cat] = totals.get(cat, 0.0) + float(rec.estimated_cost)

        # Soft defaults when no recs yet.
        if trip_budget and trip_budget > 0:
            defaults = {
                "hotels": 0.35,
                "transportation": 0.15,
                "food": 0.25,
                "museums": 0.08,
                "shopping": 0.07,
                "experiences": 0.05,
                "emergency_buffer": 0.05,
            }
            for cat, share in defaults.items():
                if totals[cat] <= 0:
                    totals[cat] = round(trip_budget * share, 2)
        else:
            totals["food"] = max(totals["food"], 40.0 * day_count)
            totals["hotels"] = max(totals["hotels"], 80.0 * day_count)
            totals["emergency_buffer"] = max(totals["emergency_buffer"], 50.0)

        lines = []
        for cat in BUDGET_CATEGORIES:
            lines.append(
                self.repository.upsert_budget_line(
                    trip_id=trip_id,
                    category=cat,
                    label=cat.replace("_", " ").title(),
                    estimated_amount=round(totals.get(cat, 0.0), 2),
                    confidence=40.0,
                    source="heuristic",
                )
            )
        return lines

    def board(self, trip_id: str) -> dict[str, Any]:
        lines = self.repository.list_budget_lines(trip_id)
        estimated = sum(float(line["estimated_amount"] or 0) for line in lines)
        actual = sum(
            float(line["actual_amount"])
            for line in lines
            if line.get("actual_amount") is not None
        )
        remaining = estimated - actual if actual else estimated
        by_cat = []
        for line in lines:
            by_cat.append(
                {
                    "category": line["category"],
                    "label": line["label"],
                    "estimated": float(line["estimated_amount"] or 0),
                    "actual": (
                        float(line["actual_amount"])
                        if line.get("actual_amount") is not None
                        else None
                    ),
                    "confidence": float(line["confidence"] or 40),
                    "source": line.get("source") or "heuristic",
                }
            )
        return {
            "categories": by_cat,
            "estimated_total": round(estimated, 2),
            "actual_total": round(actual, 2) if actual else None,
            "remaining": round(remaining, 2),
        }

    def set_actual(
        self, trip_id: str, category: str, label: str, actual_amount: float
    ) -> dict[str, Any]:
        lines = self.repository.list_budget_lines(trip_id)
        match = next(
            (
                line
                for line in lines
                if line["category"] == category and line["label"] == label
            ),
            None,
        )
        estimated = float(match["estimated_amount"]) if match else actual_amount
        return self.repository.upsert_budget_line(
            trip_id=trip_id,
            category=category,
            label=label,
            estimated_amount=estimated,
            actual_amount=actual_amount,
            confidence=95.0,
            source="actual",
        )

    def set_user_estimate(
        self, trip_id: str, category: str, label: str, estimated_amount: float
    ) -> dict[str, Any]:
        return self.repository.upsert_budget_line(
            trip_id=trip_id,
            category=category,
            label=label,
            estimated_amount=estimated_amount,
            confidence=70.0,
            source="user_estimate",
        )

    @staticmethod
    def value_blurb(
        *,
        added_cost: float,
        trip_budget: float | None,
        coverage_gain_pct: float,
    ) -> str:
        if trip_budget and trip_budget > 0:
            cost_pct = 100.0 * added_cost / trip_budget
            return (
                f"This experience increases trip cost by approximately {cost_pct:.0f}% "
                f"while improving your interest coverage by {coverage_gain_pct:.0f}%."
            )
        return (
            f"This experience costs about ${added_cost:.0f} and may improve "
            f"interest coverage by ~{coverage_gain_pct:.0f}%."
        )
