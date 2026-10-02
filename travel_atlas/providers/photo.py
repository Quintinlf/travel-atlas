"""Photo provider stub — manual / local imports via PhotoService."""

from __future__ import annotations

from .base import StubResult


class StubPhotoProvider:
    key = "photo-stub-v1"

    def list_candidates(self, *, trip_id: str) -> StubResult:
        return StubResult(
            provider=self.key,
            status="stub",
            payload={
                "message": "Cloud photo libraries not connected — use manual upload.",
                "trip_id": trip_id,
                "candidates": [],
            },
            links={},
        )

    def import_photo(self, *, trip_id: str, source_uri: str) -> StubResult:
        return StubResult(
            provider=self.key,
            status="stub",
            payload={
                "message": "Use PhotoService.add for local paths; cloud import comes later.",
                "trip_id": trip_id,
                "source_uri": source_uri,
            },
            links={},
        )
