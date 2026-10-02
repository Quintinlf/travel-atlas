"""Command line for the knowledge ingestion pipeline.

Run from the ``travel`` directory (or anywhere, with ``--atlas-db``)::

    python -m travel_atlas.ingest areas                 # geography from your pins
    python -m travel_atlas.ingest gaps                  # what's missing, and the cost
    python -m travel_atlas.ingest run --limit-areas 3   # draft claims for 3 areas
    python -m travel_atlas.ingest status                # drafts awaiting review

``gaps`` touches no network and no model — start there.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..database import AtlasDatabase
from ..knowledge_loader import load_bundled_knowledge
from ..repository import AtlasRepository
from . import extract
from .areas import DEFAULT_CITY_MIN_PINS, provision_areas
from .gaps import build_worklist, summarise
from .pipeline import approve, run_ingest

DEFAULT_ROOT = Path(__file__).resolve().parents[2]


def _repository(args: argparse.Namespace) -> AtlasRepository:
    database = AtlasDatabase(args.atlas_db)
    database.migrate()
    repository = AtlasRepository(database)
    load_bundled_knowledge(repository)
    return repository


def cmd_areas(args: argparse.Namespace) -> int:
    repository = _repository(args)
    provisioned = provision_areas(
        repository,
        args.pin_db,
        countries=args.countries,
        city_min_pins=args.city_min_pins,
    )
    print(
        f"Provisioned {provisioned.total} areas: "
        f"{len(provisioned.countries)} countries, {len(provisioned.cities)} cities."
    )
    return 0


def cmd_gaps(args: argparse.Namespace) -> int:
    repository = _repository(args)
    gaps = build_worklist(
        repository,
        pin_db_path=args.pin_db,
        area_types=args.area_types,
        limit=args.limit,
    )
    stats = summarise(gaps)
    if not gaps:
        print("No outstanding gaps. Every area meets its coverage ruleset.")
        return 0

    print(
        f"{stats['gaps']} gaps across {stats['areas']} areas "
        f"({stats['countries']} countries, {stats['cities']} cities)."
    )
    # Roughly two model calls per area, since an area's topics share two articles.
    calls = stats["areas"] * 2
    print(f"~{calls} model calls, approx ${extract.estimate_cost(calls)} at Opus 5 rates.\n")

    shown = 0
    current_area = None
    for gap in gaps:
        if gap.area_id != current_area:
            if shown >= args.show:
                break
            current_area = gap.area_id
            print(f"  {gap.area_name} ({gap.area_type}, {gap.pin_count} pins)")
            shown += 1
        print(f"      - {gap.category_name} / {gap.topic_name}")
    if stats["areas"] > args.show:
        print(f"  ... and {stats['areas'] - args.show} more areas")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    repository = _repository(args)
    try:
        result = run_ingest(
            repository,
            pin_db_path=args.pin_db,
            area_ids=args.area_ids,
            area_types=args.area_types,
            limit_areas=args.limit_areas,
            model=args.model,
            effort=args.effort,
            on_progress=print,
        )
    except extract.ExtractionUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if result.errors:
        print("\nErrors:", file=sys.stderr)
        for message in result.errors[:20]:
            print(f"  {message}", file=sys.stderr)
    print(
        f"\n{result.claims_drafted} drafts are waiting for review. "
        "Open the Knowledge Review page, or run: "
        "python -m travel_atlas.ingest status"
    )
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    repository = _repository(args)
    counts = repository.count_claims_by_status()
    print("Claims by review status:")
    for status in ("reviewed", "draft", "needs_review"):
        print(f"  {status:<13} {counts.get(status, 0)}")

    drafts = repository.list_claims_by_status("draft", limit=args.show)
    if drafts:
        print(f"\nNext {len(drafts)} drafts:")
        for claim in drafts:
            print(
                f"  [{claim['confidence']:<6}] {claim['area_name']} / "
                f"{claim['topic_name']}: {claim['value']['title']}"
            )
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    repository = _repository(args)
    drafts = repository.list_claims_by_status("draft", area_id=args.area_id, limit=10000)
    if args.min_confidence:
        ranks = {"low": 1, "medium": 2, "high": 3}
        floor = ranks[args.min_confidence]
        drafts = [c for c in drafts if ranks[c["confidence"]] >= floor]
    if not drafts:
        print("Nothing to approve.")
        return 0
    areas = approve(repository, [claim["id"] for claim in drafts])
    print(f"Approved {len(drafts)} claims; rescored {len(areas)} areas.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="travel_atlas.ingest", description=__doc__)
    parser.add_argument(
        "--atlas-db", type=Path, default=DEFAULT_ROOT / "atlas.db",
        help="Atlas knowledge database (created if missing).",
    )
    parser.add_argument(
        "--pin-db", type=Path, default=DEFAULT_ROOT / "travel_pins.db",
        help="Phase 1 pin database. Read-only; never modified.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    areas = subparsers.add_parser("areas", help="Create geo_area rows from saved pins.")
    areas.add_argument("--countries", nargs="*", help="Limit to these country names.")
    areas.add_argument(
        "--city-min-pins", type=int, default=DEFAULT_CITY_MIN_PINS,
        help="Only provision cities with at least this many pins.",
    )
    areas.set_defaults(func=cmd_areas)

    gaps = subparsers.add_parser("gaps", help="Show outstanding gaps. No network calls.")
    gaps.add_argument("--area-types", nargs="*", default=["country", "city"])
    gaps.add_argument("--limit", type=int, help="Cap the number of gaps considered.")
    gaps.add_argument("--show", type=int, default=10, help="Areas to print.")
    gaps.set_defaults(func=cmd_gaps)

    run = subparsers.add_parser("run", help="Fetch sources and draft claims.")
    run.add_argument("--area-ids", nargs="*", help="Restrict to specific geo_area ids.")
    run.add_argument("--area-types", nargs="*", default=["country", "city"])
    run.add_argument(
        "--limit-areas", type=int, default=5,
        help="Areas per run. Kept low by default so a first run is cheap to inspect.",
    )
    run.add_argument("--model", default=None, help=f"Default: {extract.DEFAULT_MODEL}")
    run.add_argument(
        "--effort", default=extract.DEFAULT_EFFORT,
        choices=["low", "medium", "high", "xhigh", "max"],
    )
    run.set_defaults(func=cmd_run)

    status = subparsers.add_parser("status", help="Counts and the head of the review queue.")
    status.add_argument("--show", type=int, default=20)
    status.set_defaults(func=cmd_status)

    approve_cmd = subparsers.add_parser(
        "approve", help="Bulk-approve drafts. Prefer the review UI for anything you have not read."
    )
    approve_cmd.add_argument("--area-id", help="Restrict to one area.")
    approve_cmd.add_argument("--min-confidence", choices=["low", "medium", "high"])
    approve_cmd.set_defaults(func=cmd_approve)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
