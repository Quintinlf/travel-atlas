"""Search Edinburgh hotels via Amadeus and write edinburgh_hotel_matches.json.

Requires AMADEUS_CLIENT_ID and AMADEUS_CLIENT_SECRET (Self-Service).

    python scripts/edinburgh_hotel_search.py
    python scripts/edinburgh_hotel_search.py --check-in 2028-03-28 --check-out 2028-03-29
    python scripts/edinburgh_hotel_search.py --env production
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from travel_atlas.providers.amadeus_hotel import AmadeusHotelProvider  # noqa: E402
from travel_atlas.services.hotel_search import search_hotels_by_geocode  # noqa: E402

DEFAULT_CHECK_IN = "2027-03-28"
DEFAULT_CHECK_OUT = "2027-03-29"
OUTPUT_PATH = _ROOT / "edinburgh_hotel_matches.json"


def _parse_date(value: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid date {value!r}; use YYYY-MM-DD") from exc


def run_search(
    *,
    check_in: str,
    check_out: str,
    adults: int = 1,
    currency: str = "GBP",
    env: str | None = None,
    provider: AmadeusHotelProvider | None = None,
) -> dict:
    return search_hotels_by_geocode(
        check_in=check_in,
        check_out=check_out,
        adults=adults,
        currency=currency,
        env=env,
        provider=provider,
        include_google_lodging=False,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-in", type=_parse_date, default=DEFAULT_CHECK_IN)
    parser.add_argument("--check-out", type=_parse_date, default=DEFAULT_CHECK_OUT)
    parser.add_argument("--adults", type=int, default=1)
    parser.add_argument("--currency", default="GBP")
    parser.add_argument(
        "--env",
        choices=("test", "production"),
        default=None,
        help="Amadeus environment (default: AMADEUS_ENV or test)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_PATH,
        help="JSON output path",
    )
    args = parser.parse_args(argv)

    if date.fromisoformat(args.check_out) <= date.fromisoformat(args.check_in):
        print("check-out must be after check-in", file=sys.stderr)
        return 2

    payload = run_search(
        check_in=args.check_in,
        check_out=args.check_out,
        adults=args.adults,
        currency=args.currency,
        env=args.env,
    )
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {args.output}")
    if not payload.get("ok"):
        print(payload.get("message"), file=sys.stderr)
        return 1
    summary = payload.get("summary") or {}
    lowest = summary.get("lowest_rate") or {}
    print(f"Matches: {summary.get('count', 0)}")
    if lowest:
        print(
            f"Lowest: {lowest.get('hotel_name')} — "
            f"{lowest.get('total_price')} {lowest.get('currency')} "
            f"({lowest.get('distance_km_to_center')} km from center)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
