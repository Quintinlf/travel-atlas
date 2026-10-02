"""Generate West Europe HTML briefing (and PDF when Edge/Chrome is available).

    python travel/scripts/generate_west_europe_briefing.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from travel_atlas.database import AtlasDatabase
from travel_atlas.env_loader import load_travel_env
from travel_atlas.repository import AtlasRepository
from travel_atlas.services.pin_service import PinService
from travel_atlas.services.traveler_service import TravelerService
from travel_atlas.services.west_europe_briefing import (
    briefing_filename,
    briefing_pdf_filename,
    build_west_europe_briefing_html,
    try_print_html_to_pdf,
)

load_travel_env()

OUT_DIR = _ROOT / "output"
PINS_DB = _ROOT / "travel_pins.db"
ATLAS_DB = _ROOT / "atlas.db"


def main() -> int:
    pins: list = []
    if PINS_DB.exists():
        pin_service = PinService(PINS_DB, atlas_database_path=ATLAS_DB)
        pins = list(pin_service.list_pins())
    else:
        print(
            "warning: travel_pins.db missing — briefing will have empty pin lists",
            file=sys.stderr,
        )

    primary = companion = None
    if ATLAS_DB.exists():
        database = AtlasDatabase(ATLAS_DB)
        database.migrate()
        travelers = TravelerService(AtlasRepository(database))
        primary = travelers.ensure_primary()
        companion = travelers.ensure_companion()
    else:
        print("warning: atlas.db missing — ACG maps skipped", file=sys.stderr)

    html = build_west_europe_briefing_html(
        pins=pins,
        primary_traveler=primary,
        companion_traveler=companion,
        enrich_hotel_photos=True,
        include_acg_maps=True,
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    html_path = OUT_DIR / briefing_filename()
    html_path.write_text(html, encoding="utf-8")
    print("wrote", html_path)

    pdf_path = OUT_DIR / briefing_pdf_filename()
    if try_print_html_to_pdf(html_path, pdf_path):
        print("wrote", pdf_path)
    else:
        print(
            "pdf skipped — open the HTML in Edge/Chrome and Print → Save as PDF",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
