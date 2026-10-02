"""Load fixture pins when travel_pins.db is empty (for local UI demos)."""

from __future__ import annotations

import sys
from pathlib import Path

_TRAVEL = Path(__file__).resolve().parent
if str(_TRAVEL) not in sys.path:
    sys.path.insert(0, str(_TRAVEL))

from src_phase1.clustering import ClusterConfig, PinClusterer
from src_phase1.pin_repository import PinRepository
from src_phase1.takeout_parser import TakeoutParser

DB_PATH = _TRAVEL / "travel_pins.db"
FIXTURE_DIR = _TRAVEL / "fixtures" / "sample_takeout"


def main() -> int:
    repo = PinRepository(DB_PATH)
    stats = repo.get_stats()
    if stats["total"] > 0:
        print(f"travel_pins.db already has {stats['total']} pins — skipping bootstrap.")
        return 0

    if not FIXTURE_DIR.is_dir():
        print(f"Fixture directory not found: {FIXTURE_DIR}", file=sys.stderr)
        return 1

    parser = TakeoutParser()
    locations = parser.parse_directory(FIXTURE_DIR)
    inserted = repo.insert_pins_batch(locations)
    removed = repo.deduplicate()
    pins = repo.get_pins_with_coords()
    clusters = PinClusterer(ClusterConfig(distance_threshold_km=15.0)).cluster_pins(pins)
    repo.save_clusters(clusters)
    print(f"Bootstrapped {inserted} demo pins ({removed} duplicates removed).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
