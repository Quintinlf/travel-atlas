"""Drive the gap → source → draft loop, one area at a time.

The unit of work is an *area*, not a topic. All of an area's missing topics draw on the
same two articles, so the article is fetched once, split once, and the topics that share
a source are extracted in a single model call. That turns roughly ten calls per country
into two.

Nothing here writes a reviewed claim. Everything lands as ``review_status='draft'``,
invisible to coverage scoring, waiting for the review queue.
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, Iterable, Sequence

from ..repository import AtlasRepository
from . import extract, sources
from .gaps import Gap, build_worklist

#: Wikimedia is generous but not free to hammer. One article fetch every 200ms is
#: comfortably inside their expectations for a single-user client.
FETCH_DELAY_SECONDS = 0.2


@dataclass
class IngestResult:
    areas_processed: int = 0
    calls_made: int = 0
    claims_drafted: int = 0
    topics_no_source: int = 0
    topics_no_claims: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [
            f"{self.areas_processed} areas",
            f"{self.calls_made} model calls",
            f"{self.claims_drafted} drafts",
        ]
        if self.topics_no_source:
            parts.append(f"{self.topics_no_source} without source text")
        if self.topics_no_claims:
            parts.append(f"{self.topics_no_claims} unsupported by source")
        if self.errors:
            parts.append(f"{len(self.errors)} errors")
        return ", ".join(parts)


def _assign_sources(gaps: Sequence[Gap]) -> dict[str, list[Gap]]:
    """Group an area's gaps by the corpus most likely to answer them.

    A topic is assigned to its first listed plan. Fallback plans are used only when the
    primary corpus has no article for the area at all, which is handled by the caller.
    """
    grouped: dict[str, list[Gap]] = defaultdict(list)
    for gap in gaps:
        plans = sources.TOPIC_SOURCES.get(gap.topic_key)
        if plans:
            grouped[plans[0].source_id].append(gap)
    return dict(grouped)


def _fallback_source(gap: Gap, unavailable: set[str]) -> str | None:
    for plan in sources.TOPIC_SOURCES.get(gap.topic_key, ()):
        if plan.source_id not in unavailable:
            return plan.source_id
    return None


def _sections_for(source_id: str, gaps: Iterable[Gap]) -> list[str]:
    wanted: list[str] = []
    for gap in gaps:
        for plan in sources.TOPIC_SOURCES.get(gap.topic_key, ()):
            if plan.source_id == source_id:
                wanted.extend(plan.sections)
    return wanted


def run_ingest(
    repository: AtlasRepository,
    *,
    pin_db_path: Path | None = None,
    area_ids: Iterable[str] | None = None,
    area_types: Iterable[str] = ("country", "city"),
    limit_areas: int | None = None,
    model: str | None = None,
    effort: str = extract.DEFAULT_EFFORT,
    api_key: str | None = None,
    client=None,
    on_progress: Callable[[str], None] | None = None,
) -> IngestResult:
    """Draft claims for every outstanding gap, area by area."""
    model = model or extract.default_model()
    result = IngestResult()
    report = on_progress or (lambda message: None)

    gaps = build_worklist(
        repository, pin_db_path=pin_db_path, area_types=area_types, area_ids=area_ids
    )
    if not gaps:
        report("No gaps outstanding.")
        return result

    by_area: dict[str, list[Gap]] = defaultdict(list)
    for gap in gaps:
        by_area[gap.area_id].append(gap)

    ordered_areas = list(by_area)
    if limit_areas:
        ordered_areas = ordered_areas[:limit_areas]

    for definition in sources.SOURCE_DEFINITIONS:
        repository.upsert_source({**definition, "retrieved_at": date.today().isoformat()})

    if client is None:
        client = extract.build_client(api_key)

    for index, area_id in enumerate(ordered_areas, start=1):
        area_gaps = by_area[area_id]
        area_name = area_gaps[0].area_name
        area_type = area_gaps[0].area_type
        report(f"[{index}/{len(ordered_areas)}] {area_name} - {len(area_gaps)} topics")

        section_cache: dict[str, dict[str, str] | None] = {}
        unavailable: set[str] = set()
        assignments = _assign_sources(area_gaps)

        # Reassign topics whose primary corpus has no article for this place.
        for source_id in list(assignments):
            if source_id not in section_cache:
                try:
                    section_cache[source_id] = sources.fetch_sections(source_id, area_name)
                except sources.SourceUnavailable as exc:
                    section_cache[source_id] = None
                    result.errors.append(f"{area_name} / {source_id}: {exc}")
                time.sleep(FETCH_DELAY_SECONDS)
            if section_cache[source_id] is None:
                unavailable.add(source_id)
                for gap in assignments.pop(source_id):
                    alternate = _fallback_source(gap, unavailable)
                    if alternate:
                        assignments.setdefault(alternate, []).append(gap)
                    else:
                        repository.record_attempt(
                            area_id=area_id,
                            topic_key=gap.topic_key,
                            status="no_source",
                            detail=f"No article for {area_name}",
                        )
                        result.topics_no_source += 1

        for source_id, source_gaps in assignments.items():
            if source_id not in section_cache:
                try:
                    section_cache[source_id] = sources.fetch_sections(source_id, area_name)
                except sources.SourceUnavailable as exc:
                    section_cache[source_id] = None
                    result.errors.append(f"{area_name} / {source_id}: {exc}")
                time.sleep(FETCH_DELAY_SECONDS)

            section_map = section_cache.get(source_id)
            if not section_map:
                for gap in source_gaps:
                    repository.record_attempt(
                        area_id=area_id,
                        topic_key=gap.topic_key,
                        status="no_source",
                        detail=f"No article for {area_name}",
                    )
                    result.topics_no_source += 1
                continue

            document = sources.assemble_document(
                source_id, area_name, section_map, _sections_for(source_id, source_gaps)
            )
            if document is None:
                for gap in source_gaps:
                    repository.record_attempt(
                        area_id=area_id,
                        topic_key=gap.topic_key,
                        status="no_source",
                        detail="Article has no relevant sections",
                    )
                    result.topics_no_source += 1
                continue

            record_id = f"rec-{source_id}-{uuid.uuid5(uuid.NAMESPACE_URL, document.url)}"
            repository.upsert_source_record(
                id=record_id,
                source_id=source_id,
                external_key=document.external_key,
                raw_payload=document.text,
                checksum=document.checksum,
            )
            stored = repository.find_source_record(source_id, document.external_key)
            record_id = stored["id"] if stored else record_id

            try:
                claims = extract.extract_claims(
                    client,
                    area_name=area_name,
                    area_type=area_type,
                    gaps=source_gaps,
                    document=document,
                    model=model,
                    effort=effort,
                )
                result.calls_made += 1
            except Exception as exc:  # network, rate limit, refusal, bad JSON
                message = f"{area_name} / {source_id}: {exc}"
                result.errors.append(message)
                report(f"    error: {message}")
                for gap in source_gaps:
                    repository.record_attempt(
                        area_id=area_id,
                        topic_key=gap.topic_key,
                        status="error",
                        detail=str(exc)[:500],
                        model=model,
                    )
                continue

            claims_by_topic: dict[str, list[extract.ExtractedClaim]] = defaultdict(list)
            for claim in claims:
                claims_by_topic[claim.topic_key].append(claim)

            for gap in source_gaps:
                topic_claims = claims_by_topic.get(gap.topic_key, [])
                if not topic_claims:
                    repository.record_attempt(
                        area_id=area_id,
                        topic_key=gap.topic_key,
                        status="no_claims",
                        detail=f"{document.url} does not cover this topic",
                        model=model,
                    )
                    result.topics_no_claims += 1
                    continue

                for position, claim in enumerate(topic_claims):
                    repository.upsert_claim(
                        {
                            "id": f"{area_id}-{gap.topic_key}-{source_id}-{position}",
                            "area_id": area_id,
                            "category_key": gap.category_key,
                            "topic_key": gap.topic_key,
                            "value": claim.value(),
                            "source_id": source_id,
                            "source_record_id": record_id,
                            "confidence": claim.confidence,
                            "review_status": "draft",
                            "season_label": claim.season_label,
                            "season_start_month_day": claim.season_start_month_day,
                            "season_end_month_day": claim.season_end_month_day,
                        }
                    )
                repository.record_attempt(
                    area_id=area_id,
                    topic_key=gap.topic_key,
                    status="extracted",
                    detail=document.url,
                    model=model,
                    claim_count=len(topic_claims),
                )
                result.claims_drafted += len(topic_claims)

        result.areas_processed += 1

    report(f"Done: {result.summary()}")
    return result


def approve(repository: AtlasRepository, claim_ids: Sequence[str]) -> list[str]:
    """Promote drafts to reviewed and rescore the areas they belong to."""
    areas = repository.set_review_status(claim_ids, "reviewed")
    for area_id in areas:
        repository.recompute_coverage(area_id)
    return areas


def reject(repository: AtlasRepository, claim_ids: Sequence[str]) -> int:
    """Delete drafts outright. The ``ingest_attempt`` row stays, so a plain rerun will
    not redraft the same rejected claim — use ``clear_attempts`` to deliberately retry."""
    return repository.delete_claims(claim_ids)
