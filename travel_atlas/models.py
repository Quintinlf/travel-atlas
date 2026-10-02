"""Domain models for the Travel Atlas knowledge foundation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class GeoArea:
    id: str
    name: str
    area_type: str
    country_code: Optional[str] = None
    parent_id: Optional[str] = None


@dataclass(frozen=True)
class KnowledgeClaim:
    id: str
    area_id: str
    category_key: str
    topic_key: str
    value: Mapping[str, Any]
    source_id: str
    confidence: str
    review_status: str = "reviewed"
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    season_start_month_day: Optional[str] = None
    season_end_month_day: Optional[str] = None
    season_label: Optional[str] = None


@dataclass(frozen=True)
class Source:
    id: str
    title: str
    publisher: str
    source_url: str
    enrichment_url: Optional[str] = None
    retrieved_at: Optional[str] = None
