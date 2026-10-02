"""Turn the coverage ruleset into a finite, ordered worklist.

``coverage_rule`` already declares what a complete area looks like, and
``AtlasRepository.missing_topics`` already computes the shortfall. This module turns
that per-area answer into a run plan: every (area, topic) pair that still needs a claim,
prioritised so a short run spends its budget where it matters most.

Priority is pin count. The point of the Atlas is to know about the places actually
saved, so a country with 44 pins gets drafted before one with a single airport stopover.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from ..repository import AtlasRepository
from .sources import TOPIC_SOURCES


@dataclass(frozen=True)
class Gap:
    """One missing (area, topic) pair, with everything the extractor needs."""

    area_id: str
    area_name: str
    area_type: str
    country_code: str | None
    category_key: str
    category_name: str
    topic_key: str
    topic_name: str
    topic_description: str
    pin_count: int = 0

    def __str__(self) -> str:
        return f"{self.area_name} / {self.topic_name}"


def pin_counts(pin_db_path: Path) -> dict[str, int]:
    """Pins per country name and per city name, for prioritising the worklist."""
    pin_db_path = Path(pin_db_path)
    if not pin_db_path.exists():
        return {}
    conn = sqlite3.connect(f"file:{pin_db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        counts: dict[str, int] = {}
        for row in conn.execute(
            "SELECT country AS name, COUNT(*) AS n FROM saved_locations "
            "WHERE country IS NOT NULL AND country <> '' GROUP BY country"
        ):
            counts[row["name"].strip().lower()] = row["n"]
        for row in conn.execute(
            "SELECT city AS name, COUNT(*) AS n FROM saved_locations "
            "WHERE city IS NOT NULL AND city <> '' GROUP BY city"
        ):
            key = row["name"].strip().lower()
            counts[key] = max(counts.get(key, 0), row["n"])
        return counts
    finally:
        conn.close()


def build_worklist(
    repository: AtlasRepository,
    *,
    pin_db_path: Path | None = None,
    area_ids: Iterable[str] | None = None,
    area_types: Iterable[str] = ("country", "city"),
    limit: int | None = None,
) -> list[Gap]:
    """Every gap worth attempting, most-pinned area first.

    Topics with no entry in :data:`TOPIC_SOURCES` are skipped — there is no corpus to
    ground them in, and drafting one anyway would produce exactly the unsourced
    assertion this pipeline exists to avoid.
    """
    counts = pin_counts(pin_db_path) if pin_db_path else {}
    wanted_types = set(area_types)

    if area_ids is not None:
        areas = [a for a in (repository.get_area(i) for i in area_ids) if a]
    else:
        areas = [a for a in repository.list_areas() if a["area_type"] in wanted_types]

    gaps: list[Gap] = []
    for area in areas:
        if area["area_type"] not in wanted_types:
            continue
        pins = counts.get(area["name"].strip().lower(), 0)
        for missing in repository.missing_topics(area["id"]):
            if missing["topic_key"] not in TOPIC_SOURCES:
                continue
            gaps.append(
                Gap(
                    area_id=missing["area_id"],
                    area_name=missing["area_name"],
                    area_type=missing["area_type"],
                    country_code=missing["country_code"],
                    category_key=missing["category_key"],
                    category_name=missing["category_name"],
                    topic_key=missing["topic_key"],
                    topic_name=missing["topic_name"],
                    topic_description=missing["topic_description"],
                    pin_count=pins,
                )
            )

    # Countries before their cities at equal pin counts: a city claim reads better when
    # the country context around it already exists.
    gaps.sort(key=lambda g: (-g.pin_count, g.area_type != "country", g.area_name))
    return gaps[:limit] if limit else gaps


def summarise(gaps: list[Gap]) -> dict[str, int]:
    """Counts for a dry run: how much work is outstanding, and where."""
    summary = {
        "gaps": len(gaps),
        "areas": len({g.area_id for g in gaps}),
        "countries": len({g.area_id for g in gaps if g.area_type == "country"}),
        "cities": len({g.area_id for g in gaps if g.area_type == "city"}),
    }
    return summary
