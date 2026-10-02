"""Contracts for future dynamic Atlas data refreshers.

Adapters intentionally return data only. Persisting and scheduling refreshes
belongs to a later orchestration layer, keeping offline bundled knowledge
independent of network availability.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping, Protocol, runtime_checkable


@dataclass(frozen=True)
class DynamicSnapshot:
    adapter_key: str
    area_id: str
    payload: Mapping[str, Any]
    source_url: str
    retrieved_at: datetime
    expires_at: datetime | None = None


@runtime_checkable
class DynamicKnowledgeAdapter(Protocol):
    """Interface for weather, event, price, schedule, and advisory providers."""

    key: str

    def fetch(self, area_id: str) -> DynamicSnapshot:
        """Retrieve one current snapshot for an Atlas geographic area."""


@dataclass(frozen=True)
class SkyEvent:
    key: str
    kind: str
    title: str
    description: str
    occurs_on: date
    detail: Mapping[str, Any]


@dataclass(frozen=True)
class SkySnapshot:
    adapter_key: str
    latitude: float
    longitude: float
    date: date
    events: tuple[SkyEvent, ...]
    generated_at: datetime


@runtime_checkable
class AstronomyAdapter(Protocol):
    """Interface for local-or-remote sky-event providers.

    Unlike DynamicKnowledgeAdapter (area_id keyed, cached snapshot), a sky
    computation is a pure function of (latitude, longitude, date) and needs no
    Atlas area to already exist. A future MCP-server-backed adapter implements
    this same Protocol by making a network call instead of computing locally;
    SeasonalContextService depends only on this Protocol, never on the
    concrete class, so swapping in an MCP client later is a one-line
    constructor change and requires no change to calling code.

    Contract:
    - `key` uniquely identifies the implementation (e.g. "astral-local-v1",
      "mcp-astronomy-v1") and is carried on any persisted snapshot for provenance.
    - `fetch` MUST be deterministic for a given (latitude, longitude, on_date).
    - `fetch` MUST NOT raise for any valid latitude/longitude/date; on partial
      failure (e.g. polar day/night making sunrise/sunset undefined) it omits
      the affected SkyEvent rather than raising.
    - `SkyEvent.detail` MUST be JSON-serializable plain data only
      (str/int/float/bool/None/list/dict) so snapshots can be cached in
      dynamic_snapshot without adapter-specific deserialization.
    - Coordinates are WGS84 decimal degrees; `on_date` is a naive calendar
      date. Concrete adapters own their own timezone handling; the local
      adapter computes in UTC (documented precision trade-off — adequate for
      day-length/moon-phase/solstice narrative purposes, not a timezone-exact
      almanac).
    """

    key: str

    def fetch(self, *, latitude: float, longitude: float, on_date: date) -> SkySnapshot:
        """Compute/retrieve sky events relevant to a single calendar date."""
