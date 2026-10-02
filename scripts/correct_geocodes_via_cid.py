"""Resolve Want-to-go rows via Google Maps CID and write/update the geocoded CSV.

Prefer this over Nominatim title matches for Google Takeout URLs. Run from
the travel/ folder:

    python scripts/correct_geocodes_via_cid.py
    python scripts/correct_geocodes_via_cid.py --only "Links N' Ice"
    python scripts/correct_geocodes_via_cid.py --apply-pins

If Want to go_geocoded.csv is missing, it is created from Want to go.csv.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src_phase1.google_place_identity import (  # noqa: E402
    coords_conflict,
    resolve_coords_via_cid_embed,
)
from travel_atlas.services.pin_service import PinService  # noqa: E402

SAVED_DIR = _ROOT / "Takeout" / "Saved"
SOURCE_CSV = SAVED_DIR / "Want to go.csv"
CSV_PATH = SAVED_DIR / "Want to go_geocoded.csv"

_GEOCODED_FIELDS = [
    "Title",
    "Note",
    "URL",
    "Tags",
    "Comment",
    "Latitude",
    "Longitude",
    "GeocodeNote",
]


def _load_rows() -> tuple[list[str], list[dict[str, str]]]:
    """Load geocoded CSV, or seed it from Want to go.csv when missing."""
    if CSV_PATH.is_file():
        with CSV_PATH.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = list(reader.fieldnames or [])
            for col in ("Latitude", "Longitude", "GeocodeNote"):
                if col not in fieldnames:
                    fieldnames.append(col)
            return fieldnames, list(reader)

    if not SOURCE_CSV.is_file():
        raise SystemExit(f"Missing both {CSV_PATH} and {SOURCE_CSV}")

    with SOURCE_CSV.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows: list[dict[str, str]] = []
        for row in reader:
            title = (row.get("Title") or "").strip()
            url = (row.get("URL") or "").strip()
            if not title and not url:
                continue
            rows.append(
                {
                    "Title": title,
                    "Note": (row.get("Note") or "").strip(),
                    "URL": url,
                    "Tags": (row.get("Tags") or "").strip(),
                    "Comment": (row.get("Comment") or "").strip(),
                    "Latitude": "",
                    "Longitude": "",
                    "GeocodeNote": "",
                }
            )
    print(f"Seeded {len(rows)} rows from {SOURCE_CSV.name} (geocoded CSV was missing)")
    return list(_GEOCODED_FIELDS), rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="Only correct this Title")
    parser.add_argument("--sleep", type=float, default=0.75)
    parser.add_argument("--apply-pins", action="store_true", help="Sync pin DB after")
    parser.add_argument(
        "--fill-missing-pins",
        action="store_true",
        help="Also fill 0,0 pins in travel_pins.db via CID, then reverse-geocode",
    )
    args = parser.parse_args()

    fieldnames, rows = _load_rows()

    changed = 0
    for row in rows:
        title = (row.get("Title") or "").strip()
        if args.only and title != args.only:
            continue
        url = (row.get("URL") or "").strip()
        if not url:
            continue
        coords = resolve_coords_via_cid_embed(url)
        time.sleep(args.sleep)
        if not coords:
            print(f"[--] {title}")
            continue
        try:
            old_lat = float(row.get("Latitude") or 0)
            old_lng = float(row.get("Longitude") or 0)
        except ValueError:
            old_lat = old_lng = 0.0
        if old_lat or old_lng:
            if not coords_conflict(old_lat, old_lng, coords[0], coords[1], threshold_km=25):
                print(f"[ok] {title}")
                continue
        row["Latitude"] = str(coords[0])
        row["Longitude"] = str(coords[1])
        row["GeocodeNote"] = "resolved via Google CID (corrected)"
        changed += 1
        print(f"[FIX] {title} -> {coords[0]}, {coords[1]} (was {old_lat}, {old_lng})")

    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CSV_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Updated {changed} CSV rows -> {CSV_PATH}")

    if args.apply_pins or args.fill_missing_pins:
        service = PinService(
            _ROOT / "travel_pins.db", atlas_database_path=_ROOT / "atlas.db"
        )
        if args.apply_pins:
            enrichment = service.enrich_from_geocoded_csv(CSV_PATH)
            print("enrichment", enrichment)
        if args.fill_missing_pins:
            cid_fill = service.fill_missing_coordinates_from_cid(sleep_s=args.sleep)
            print("cid_fill", cid_fill)
        backfill = service.backfill_places()
        clusters = service.recluster()
        print("backfill", backfill)
        print("clusters", clusters)


if __name__ == "__main__":
    main()
