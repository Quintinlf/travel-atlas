"""Safety advisories — live State Dept when reachable, stub otherwise."""

from __future__ import annotations

from pathlib import Path

from .base import StubResult
from .state_dept import StateDeptSafetyProvider


class StubSafetyProvider:
    key = "safety-stub-v1"

    def __init__(self, cache_db_path: Path | None = None) -> None:
        self._live = StateDeptSafetyProvider(cache_db_path=cache_db_path)

    def advisories(self, *, destination: str) -> StubResult:
        live = self._live.advisories(destination=destination)
        if live.status == "live":
            return live
        return StubResult(
            provider=self.key,
            status=live.status if live.status != "live" else "stub",
            payload={
                "message": (live.payload or {}).get("message")
                or "Live safety advisories unavailable; showing stub.",
                "destination": destination,
                "items": (live.payload or {}).get("items") or [],
            },
            links=live.links or {},
        )
