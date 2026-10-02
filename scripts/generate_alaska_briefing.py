"""Regenerate Fairbanks aurora HTML briefing from price snapshot."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from travel_atlas.env_loader import load_travel_env
from travel_atlas.services.alaska_briefing import (
    briefing_filename,
    build_alaska_briefing_html,
)

load_travel_env()

ARRIVE = date(2026, 9, 26)
LEAVE = date(2026, 9, 30)
TRAVELERS = 2
OUT_DIR = _ROOT / "output"


def main() -> None:
    html = build_alaska_briefing_html(
        arrive=ARRIVE,
        leave=LEAVE,
        travelers=TRAVELERS,
        allow_live_fetch=True,
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / briefing_filename(arrive=ARRIVE)
    out_path.write_text(html, encoding="utf-8")
    print("wrote", out_path)


if __name__ == "__main__":
    main()
