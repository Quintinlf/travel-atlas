"""Load bundled, reviewed Travel Atlas knowledge into the local database."""

from __future__ import annotations

import json
from pathlib import Path

from .repository import AtlasRepository

DATA_PATH = Path(__file__).parent / "data" / "seed_knowledge.json"


def load_bundled_knowledge(repository: AtlasRepository, path: Path = DATA_PATH) -> None:
    """Idempotently load the offline seed corpus and calculate coverage."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    repository.upsert_categories(payload["categories"])
    repository.upsert_topics(payload["topics"])
    for area in payload["areas"]:
        repository.upsert_area(area)
    for source in payload["sources"]:
        repository.upsert_source(source)
    for claim in payload["claims"]:
        repository.upsert_claim(claim)
    repository.replace_coverage_rules(payload["coverage_rules"])
    for area in payload["areas"]:
        repository.recompute_coverage(area["id"])
