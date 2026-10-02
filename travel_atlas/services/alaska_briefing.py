"""HTML trip briefing for Alaska aurora booking (print → Save as PDF)."""

from __future__ import annotations

import calendar
import html
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

from travel_atlas.services.alaska_bases import FAIRBANKS_BASE, HOME_AIRPORT
from travel_atlas.services.alaska_flight_routes import route_briefing
from travel_atlas.services.aurora_service import AuroraService, NightScore
from travel_atlas.services.aurora_weather import build_aurora_weather_report
from travel_atlas.services.fairbanks_guide import fairbanks_guide
from travel_atlas.services.fairbanks_trip_budget import build_trip_budget
from travel_atlas.services.flight_search import search_roundtrip_fares
from travel_atlas.services.hotel_photo import resolve_hotel_photo
from travel_atlas.services.hotel_search import search_hotels_by_geocode

_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "alaska_trip_briefing.html"
_SNAPSHOT_PATH = Path(__file__).resolve().parent.parent.parent / "fairbanks_price_snapshot.json"
_HERO_IMAGE = (
    "https://images.unsplash.com/photo-1531366936337-7c912a4589a7"
    "?auto=format&fit=crop&w=1400&q=80"
)
_QUEEN_BED_TYPES = ["queen"]


def _escape(value: Any) -> str:
    return html.escape(str(value))


def _usd(value: float | int | None) -> str:
    if value is None:
        return "—"
    return f"${float(value):,.0f}"


def _load_snapshot(path: Path | None = None) -> dict[str, Any]:
    snap_path = path or _SNAPSHOT_PATH
    if not snap_path.is_file():
        return {}
    return json.loads(snap_path.read_text(encoding="utf-8"))


def _cost_range(est: tuple[float, float] | list[float] | None) -> str:
    if not est:
        return ""
    low, high = float(est[0]), float(est[1])
    if low == 0 and high == 0:
        return "Free"
    if low == high:
        return _usd(low)
    return f"{_usd(low)}–{_usd(high)}"


def _hotel_rows_from_result(result: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not result:
        return []
    rows = list(result.get("sorted_by_price") or result.get("hotels") or [])
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "hotel": row.get("hotel_name") or row.get("hotel"),
                "room": row.get("room_name") or row.get("room"),
                "total": row.get("total_price") or row.get("total"),
                "nightly": row.get("nightly_rate") or row.get("nightly"),
                "rating": row.get("rating"),
                "bed_verify": row.get("bed_verify"),
                "booking_url": row.get("booking_url"),
                "google_hotels_url": row.get("google_hotels_url"),
                "photo_url": row.get("photo_url"),
                "lat": row.get("lat"),
                "lon": row.get("lon"),
            }
        )
    return out


def _enrich_hotel_photos(rows: list[dict[str, Any]], *, limit: int = 12) -> None:
    for row in rows[:limit]:
        if row.get("photo_url"):
            continue
        lat = row.get("lat")
        lon = row.get("lon")
        if lat is None or lon is None:
            continue
        hit = resolve_hotel_photo(
            property_name=str(row.get("hotel") or ""),
            city="Fairbanks",
            country="United States",
            lat=float(lat),
            lon=float(lon),
        )
        if hit:
            row["photo_url"] = hit.url


def _hotel_rows_from_snapshot_window(window: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not window:
        return []
    hotels = (window.get("hotels") or {}).get("hotels") or []
    return list(hotels)


def _render_hotel_cards(rows: Sequence[Mapping[str, Any]], *, highlight_first: bool = True) -> str:
    if not rows:
        return "<p><em>No hotel quotes available — use Booking.com link below.</em></p>"
    cards: list[str] = ['<div class="hotel-grid">']
    for index, row in enumerate(rows):
        cls = "hotel-card highlight" if highlight_first and index == 0 else "hotel-card"
        name = _escape(row.get("hotel") or "—")
        room = _escape(row.get("room") or "—")
        verify = " (verify beds)" if row.get("bed_verify") else ""
        book = row.get("booking_url") or ""
        google = row.get("google_hotels_url") or ""
        photo = row.get("photo_url") or ""
        if photo:
            img = (
                f'<img class="hotel-photo" src="{_escape(photo)}" alt="{name}" '
                'loading="lazy" />'
            )
        else:
            img = '<div class="hotel-photo placeholder">No photo</div>'
        title = (
            f'<a href="{_escape(book)}">{name}</a>' if book else f"<strong>{name}</strong>"
        )
        links = ""
        if book:
            links += (
                f'<a class="btn-link" href="{_escape(book)}">Book on Booking.com</a>'
            )
        if google:
            links += (
                f'<a class="btn-link secondary" href="{_escape(google)}">'
                "Room photos (Google)</a>"
            )
        cards.append(
            f'<div class="{cls}">{img}'
            f'<div class="hotel-body"><h3 class="hotel-name">{title}</h3>'
            f'<p class="hotel-room"><strong>Room:</strong> {room}{verify}</p>'
            f'<p class="hotel-price">{_usd(row.get("total"))} total · '
            f'{_usd(row.get("nightly"))}/night · '
            f'rating {_escape(row.get("rating") or "—")}</p>'
            f'<p class="no-print links">{links}</p></div></div>'
        )
    cards.append("</div>")
    return "\n".join(cards)


def _flight_budget_from_sources(
    *,
    flight_result: dict[str, Any] | None,
    snapshot: dict[str, Any],
    arrive: date,
    leave: date,
    travelers: int,
    routes: dict[str, Any],
) -> tuple[float, float, str]:
    """Return (low, high, label) for flight budget line."""
    low, high = routes["flight_benchmark_per_adult"]
    low *= travelers
    high *= travelers
    label = "September benchmark"

    fares = list((flight_result or {}).get("fares") or [])
    if not fares:
        for window in (snapshot.get("windows") or {}).values():
            w_arrive = date.fromisoformat(window["arrive"])
            w_leave = date.fromisoformat(window["leave"])
            if w_arrive == arrive and w_leave == leave:
                fares = list((window.get("flights") or {}).get("fares") or [])
                break

    if fares:
        totals = [
            float(f.get("total_for_party") or f.get("price_per_adult", 0) * travelers)
            for f in fares
        ]
        totals = [t for t in totals if t > 0]
        if totals:
            cheapest = min(totals)
            highest = max(totals)
            return cheapest, highest, "live Aviasales quote"

    benchmark = snapshot.get("flight_benchmark") or {}
    if benchmark:
        low = float(benchmark.get("per_adult_low_usd") or low / travelers) * travelers
        high = float(benchmark.get("per_adult_high_usd") or high / travelers) * travelers

    return float(low), float(high), label


def _render_aurora_strategy_section(report: dict[str, Any]) -> str:
    hist = report.get("historical") or {}
    lines = [
        "<section class=\"card\">",
        "<h2>Aurora viewing strategy</h2>",
        f"<p>{_escape(report.get('strategy_summary') or '')}</p>",
    ]
    if hist:
        lines.append(
            "<p><strong>Historical "
            f"{_escape(calendar.month_name[hist.get('month', 9)])}:</strong> "
            f"mean cloud cover ~{_escape(hist.get('mean_cloud_cover_pct'))}%, "
            f"~{_escape(hist.get('clear_night_pct'))}% of nights clear enough for DIY "
            f"(≤{_escape(hist.get('clear_night_threshold_pct'))}% cloud).</p>"
        )
    if report.get("forecast_note"):
        lines.append(
            f"<p class=\"callout\"><strong>Forecast:</strong> "
            f"{_escape(report['forecast_note'])}</p>"
        )
    lines.extend(
        [
            "<table>",
            "<thead><tr><th>Date</th><th class=\"num\">Cloud %</th>"
            "<th>Source</th><th>Recommendation</th></tr></thead><tbody>",
        ]
    )
    for night in report.get("nights") or []:
        cloud = night.get("cloud_cover_pct")
        cloud_txt = f"{cloud:.0f}" if cloud is not None else "—"
        lines.append(
            "<tr>"
            f"<td>{_escape(night.get('date'))}</td>"
            f'<td class="num">{cloud_txt}</td>'
            f"<td>{_escape(night.get('source'))}</td>"
            f"<td>{_escape(night.get('recommendation_label'))}</td>"
            "</tr>"
        )
    lines.append("</tbody></table>")
    lines.append(
        '<p class="no-print links">'
        f'<a class="btn-link" href="{_escape(report.get("chena_maps_url") or "")}">'
        "DIY darker-sky pullouts (Chena Rd)</a>"
        f'<a class="btn-link secondary" href="{_escape(report.get("tour_maps_url") or "")}">'
        "Guided aurora tours</a>"
        "</p>"
    )
    lines.append("</section>")
    return "\n".join(lines)


def _render_aurora_table(nights: Sequence[Mapping[str, Any]]) -> str:
    if not nights:
        return ""
    lines = [
        "<table>",
        "<thead><tr>"
        "<th>Date</th><th class=\"num\">Dark hours</th>"
        "<th class=\"num\">Score</th><th>Good night?</th>"
        "</tr></thead><tbody>",
    ]
    for night in nights:
        visible = "Yes" if night.get("visible_enough") else "—"
        lines.append(
            "<tr>"
            f"<td>{_escape(night.get('date') or night.get('on_date'))}</td>"
            f'<td class="num">{_escape(night.get("night_hours") or "—")}</td>'
            f'<td class="num">{_escape(night.get("combined") or "—")}</td>'
            f"<td>{visible}</td>"
            "</tr>"
        )
    lines.append("</tbody></table>")
    return "\n".join(lines)


def _compare_section(
    *,
    arrive: date,
    leave: date,
    travelers: int,
    snapshot: dict[str, Any],
    current_hotel_total: float | None,
) -> str:
    windows = snapshot.get("windows") or {}
    if not windows:
        return ""

    alt_blocks: list[str] = []
    night_count = (leave - arrive).days
    for label, window in windows.items():
        w_arrive = date.fromisoformat(window["arrive"])
        w_leave = date.fromisoformat(window["leave"])
        if w_arrive == arrive and w_leave == leave:
            continue
        hotels = _hotel_rows_from_snapshot_window(window)
        if not hotels:
            continue
        cheapest = hotels[0]
        benchmark = snapshot.get("flight_benchmark") or {}
        party_mid = benchmark.get("party_of_2_mid_usd")
        if party_mid is None:
            routes = route_briefing(adults=travelers)
            party_mid = routes["flight_benchmark_party_mid"]
        hotel_total = float(cheapest.get("total") or 0)
        trip_total = hotel_total + float(party_mid)
        alt_blocks.append(
            f"<div class=\"stat\">"
            f"<div class=\"label\">{label} (leave {w_leave.isoformat()})</div>"
            f"<div class=\"value\">Hotel {_usd(hotel_total)} · Est. trip {_usd(trip_total)}</div>"
            f"</div>"
        )

    if not alt_blocks and current_hotel_total is not None:
        routes = route_briefing(adults=travelers)
        party_mid = routes["flight_benchmark_party_mid"]
        trip_total = current_hotel_total + party_mid
        return (
            "<section class=\"card\">"
            "<h2>Estimated trip total</h2>"
            "<div class=\"stats\">"
            f"<div class=\"stat\"><div class=\"label\">Hotel (best 2-queen)</div>"
            f"<div class=\"value\">{_usd(current_hotel_total)}</div></div>"
            f"<div class=\"stat\"><div class=\"label\">Flights ({travelers} adults, benchmark)</div>"
            f"<div class=\"value\">{_usd(party_mid)}</div></div>"
            f"<div class=\"stat\"><div class=\"label\">Estimated total</div>"
            f"<div class=\"value\">{_usd(trip_total)}</div></div>"
            "</div></section>"
        )

    if not alt_blocks:
        return ""

    compare_html = (
        "<section class=\"card\"><h2>3-night vs 4-night comparison</h2>"
        "<div class=\"compare-grid\">" + "".join(alt_blocks) + "</div>"
        "<p><small>Hotel totals from saved snapshot; flights use September benchmark for "
        f"{travelers} adults.</small></p></section>"
    )
    if current_hotel_total is not None and night_count in (3, 4):
        routes = route_briefing(adults=travelers)
        party_mid = routes["flight_benchmark_party_mid"]
        current_trip = current_hotel_total + party_mid
        compare_html = (
            "<section class=\"card\"><h2>Estimated trip total (your dates)</h2>"
            "<div class=\"stats\">"
            f"<div class=\"stat\"><div class=\"label\">Your stay ({night_count} nights)</div>"
            f"<div class=\"value\">{_usd(current_trip)}</div></div>"
            + "".join(alt_blocks)
            + "</div></section>"
        )
    return compare_html


def _render_bullet_list(items: Sequence[str]) -> str:
    if not items:
        return ""
    lines = ["<ul class=\"spot-list\">"]
    for item in items:
        lines.append(f"<li>{_escape(item)}</li>")
    lines.append("</ul>")
    return "\n".join(lines)


def _render_optional_add_ons_section(guide: dict[str, Any]) -> str:
    hs = guide["hot_springs"]
    car = guide["optional_add_ons"]["car_rental"]
    car_cost = _cost_range(car.get("est_cost_party_usd"))

    lines = [
        "<section class=\"card\">",
        "<h2>Optional add-ons</h2>",
        "<p>These are <strong>not required</strong> for a great aurora trip. "
        "The core plan works with airport rides, in-town sights, and an optional guided aurora night.</p>",
        "<h3>Rental car</h3>",
        f"<p><strong>Est. for 2:</strong> {car_cost} — { _escape(car.get('cost_note') or '')}</p>",
        "<p><strong>Add it if:</strong></p>",
        f"{_render_bullet_list(list(car.get('why_add') or []))}",
        "<p><strong>Skip it if:</strong></p>",
        f"{_render_bullet_list(list(car.get('skip_if') or []))}",
        "<h3>Chena Hot Springs day</h3>",
        f'<div class="mom-pick"><span class="tag">{_escape(hs["tag"])}</span></div>',
        f"<p><strong>Day pass (self-drive):</strong> {_cost_range(hs.get('est_cost_party_usd'))}</p>",
        f"<p><strong>Day shuttle (no car):</strong> "
        f"{_cost_range(hs.get('shuttle_cost_party_usd'))}</p>",
        f"<p>{_escape(hs.get('without_car_note') or '')}</p>",
        "<p><strong>Add it if (especially for Mom):</strong></p>",
        f"{_render_bullet_list(list(hs.get('why_add') or []))}",
        "<p><strong>Skip it if:</strong></p>",
        f"{_render_bullet_list(list(hs.get('skip_if') or []))}",
        f'<p class="no-print links">'
        f'<a class="btn-link" href="{_escape(hs["url"])}">Chena Hot Springs Resort</a>'
        f'<a class="btn-link secondary" href="{_escape(hs["maps_url"])}">Map</a>'
        f"</p>",
        "</section>",
    ]
    return "\n".join(lines)


def _render_guide_sections(guide: dict[str, Any], routes: dict[str, Any]) -> dict[str, str]:
    hs = guide["hot_springs"]
    hs_cost = _cost_range(hs.get("est_cost_party_usd"))
    hot_springs = (
        f'<div class="mom-pick"><span class="tag">{_escape(hs["tag"])}</span></div>'
        f'<p><strong><a href="{_escape(hs["maps_url"])}">{_escape(hs["name"])}</a></strong>'
        f" — {_escape(hs['drive'])}</p>"
        f"<p>{_escape(hs['summary'])}</p>"
        + (f"<p><strong>Day pass (self-drive):</strong> {hs_cost}</p>" if hs_cost else "")
        + (
            f"<p><strong>Shuttle from Fairbanks (no car):</strong> "
            f"{_cost_range(hs.get('shuttle_cost_party_usd'))}</p>"
        )
        + f"<p>{_escape(hs.get('without_car_note') or '')}</p>"
        + "<p><strong>Why add it:</strong></p>"
        + f"{_render_bullet_list(list(hs.get('why_add') or []))}"
        + f'<p class="no-print links">'
        f'<a class="btn-link" href="{_escape(hs["url"])}">Chena Hot Springs Resort</a>'
        f'<a class="btn-link secondary" href="{_escape(hs["maps_url"])}">Map</a>'
        f"</p>"
    )

    mk = guide["markets"]
    mk_cost = _cost_range(mk.get("est_cost_party_usd"))
    markets = (
        f'<p><strong><a href="{_escape(mk["maps_url"])}">{_escape(mk["name"])}</a></strong>'
        f" — {_escape(mk['address'])}</p>"
        f"<p>{_escape(mk['hours'])}</p>"
        + (f"<p><strong>Est. for 2:</strong> {mk_cost}</p>" if mk_cost else "")
        + f'<p class="callout">{_escape(mk["note"])}</p>'
        f"<p>{_escape(mk['la_note'])}</p>"
        f"<p><strong>What to buy:</strong></p>{_render_bullet_list(mk['buy'])}"
    )

    nf = guide["native_foods"]
    native_rows = []
    for item in nf["try"]:
        food, where, url = item[0], item[1], item[2]
        native_rows.append(
            f"<tr><td>{_escape(food)}</td>"
            f'<td><a href="{_escape(url)}">{_escape(where)}</a></td></tr>'
        )
    native_foods = (
        f"<p>{_escape(nf['intro'])}</p>"
        "<table><thead><tr><th>Try</th><th>Where</th></tr></thead><tbody>"
        + "".join(native_rows)
        + "</tbody></table>"
        f'<p class="no-print links">'
        f'<a class="btn-link secondary" href="{_escape(nf["culture_url"])}">Morris Thompson Center</a>'
        f"</p>"
    )

    see_lines = []
    for s in guide["things_to_see"]:
        cost = _cost_range(s.get("est_cost_party_usd"))
        cost_txt = f" <em>(est. {cost})</em>" if cost else ""
        see_lines.append(
            f'<li><strong><a href="{_escape(s["maps_url"])}">{_escape(s["name"])}</a></strong>'
            f" — {_escape(s['why'])}{cost_txt}</li>"
        )
    see_section = "<ul class=\"spot-list\">" + "".join(see_lines) + "</ul>"

    eat_lines = [
        "<table><thead><tr><th>Restaurant</th><th>Style</th>"
        "<th>Est. dinner (2)</th><th>Notes</th></tr></thead><tbody>"
    ]
    for row in guide["places_to_eat"]:
        eat_lines.append(
            f'<tr><td><a href="{_escape(row["maps_url"])}">{_escape(row["name"])}</a></td>'
            f"<td>{_escape(row['style'])}</td>"
            f'<td class="num">{_cost_range(row.get("est_cost_party_usd"))}</td>'
            f"<td>{_escape(row['note'])}</td></tr>"
        )
    eat_lines.append("</tbody></table>")
    eat_section = "\n".join(eat_lines)

    do_lines = []
    for item in guide["things_to_do"]:
        cost = _cost_range(item.get("est_cost_party_usd"))
        cost_txt = f" — est. {cost}" if cost else ""
        do_lines.append(
            f'<li><a href="{_escape(item["maps_url"])}">{_escape(item["label"])}</a>{cost_txt}</li>'
        )
    activities = (
        "<ul class=\"spot-list\">" + "".join(do_lines) + "</ul>"
        + "<h3>Suggested day-by-day</h3><ol class=\"checklist\">"
        + "".join(
            f"<li><strong>{_escape(d['label'])}:</strong> {_escape(d['plan'])}</li>"
            for d in guide["suggested_days"]
        )
        + "</ol>"
    )

    return {
        "hot_springs_section": hot_springs,
        "markets_section": markets,
        "native_foods_section": native_foods,
        "see_section": see_section,
        "eat_section": eat_section,
        "activities_section": activities,
        "no_red_eye_summary": routes.get("no_red_eye_summary", ""),
    }


def _render_budget_section(budget: dict[str, Any]) -> str:
    def rows(items: list[dict[str, Any]]) -> list[str]:
        out: list[str] = []
        for item in items:
            label = _escape(item["label"])
            if item.get("maps_url"):
                label = f'<a href="{_escape(item["maps_url"])}">{label}</a>'
            out.append(
                f"<tr><td>{label}</td><td>{_escape(item['category'])}</td>"
                f'<td class="num">{_usd(item["low"])}</td>'
                f'<td class="num">{_usd(item["high"])}</td></tr>'
            )
        return out

    core_rows = rows(budget["line_items"])
    optional_rows = rows(budget.get("optional_line_items") or [])

    return (
        "<section class=\"card\">"
        "<h2>Estimated full trip cost (2 travelers)</h2>"
        f"<p><strong>Core trip (mid):</strong> {_usd(budget['core_total_mid'])} "
        f"· range {_usd(budget['core_total_low'])}–{_usd(budget['core_total_high'])}</p>"
        f"<p><em>Core includes flights, hotel, airport rides, in-town sights, food — "
        f"no car or Chena.</em></p>"
        "<table><thead><tr><th>Item</th><th>Category</th>"
        '<th class="num">Low</th><th class="num">High</th></tr></thead><tbody>'
        + "\n".join(core_rows)
        + "</tbody></table>"
        + "<h3>Optional add-ons (not in core total)</h3>"
        "<table><thead><tr><th>Item</th><th>Category</th>"
        '<th class="num">Low</th><th class="num">High</th></tr></thead><tbody>'
        + "\n".join(optional_rows)
        + "</tbody></table>"
        + f"<p><strong>All optional add-ons (mid):</strong> "
        f"{_usd(budget.get('optional_total_mid'))} · "
        f"range {_usd(budget.get('optional_total_low'))}–"
        f"{_usd(budget.get('optional_total_high'))}</p>"
        + f"<p><small>{_escape(budget['note'])}</small></p></section>"
    )


def _fill_template(mapping: dict[str, str]) -> str:
    text = _TEMPLATE_PATH.read_text(encoding="utf-8")
    for key, value in mapping.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def build_alaska_briefing_html(
    *,
    arrive: date,
    leave: date,
    travelers: int = 2,
    flight_result: dict[str, Any] | None = None,
    hotel_result: dict[str, Any] | None = None,
    stay_nights: Sequence[NightScore | Mapping[str, Any]] | None = None,
    snapshot_path: Path | None = None,
    allow_live_fetch: bool = True,
) -> str:
    """Build a self-contained HTML briefing for print / Save as PDF."""
    base = FAIRBANKS_BASE
    routes = route_briefing(adults=travelers)
    snapshot = _load_snapshot(snapshot_path)

    if flight_result is None and allow_live_fetch:
        flight_result = search_roundtrip_fares(
            origin=HOME_AIRPORT,
            destination=base.airport,
            depart=arrive,
            return_on=leave,
            adults=travelers,
        )

    if hotel_result is None and allow_live_fetch:
        hotel_result = search_hotels_by_geocode(
            latitude=base.latitude,
            longitude=base.longitude,
            check_in=arrive.isoformat(),
            check_out=leave.isoformat(),
            radius_km=20.0,
            adults=travelers,
            bed_types=_QUEEN_BED_TYPES,
            currency="USD",
            city=base.hotel_query,
            include_google_lodging=False,
        )

    hotel_rows = _hotel_rows_from_result(hotel_result)
    if not hotel_rows:
        for label, window in (snapshot.get("windows") or {}).items():
            w_arrive = date.fromisoformat(window["arrive"])
            w_leave = date.fromisoformat(window["leave"])
            if w_arrive == arrive and w_leave == leave:
                hotel_rows = _hotel_rows_from_snapshot_window(window)
                break
        if not hotel_rows and snapshot.get("windows"):
            first = next(iter(snapshot["windows"].values()))
            hotel_rows = _hotel_rows_from_snapshot_window(first)

    _enrich_hotel_photos(hotel_rows)

    links = (flight_result or {}).get("links") or {}
    if not links:
        for window in (snapshot.get("windows") or {}).values():
            if window.get("flights", {}).get("links"):
                links = window["flights"]["links"]
                break

    area_links = (hotel_result or {}).get("area_links") or {}
    booking_url = area_links.get("booking")
    if not booking_url:
        for window in (snapshot.get("windows") or {}).values():
            area = (window.get("hotels") or {}).get("area_links") or {}
            if area.get("booking"):
                booking_url = area["booking"]
                break
    if not booking_url:
        booking_url = (
            "https://www.booking.com/searchresults.html?"
            f"ss=Fairbanks%2C+Alaska&checkin={arrive.isoformat()}"
            f"&checkout={leave.isoformat()}&group_adults={travelers}"
        )

    if stay_nights is None:
        aurora = AuroraService()
        scored = aurora.score_window(base, arrive, leave)
        night_dicts = [n.as_dict() for n in scored]
    else:
        night_dicts = [
            n.as_dict() if hasattr(n, "as_dict") else dict(n) for n in stay_nights
        ]
        for row in night_dicts:
            if "date" not in row and "on_date" in row:
                od = row["on_date"]
                row["date"] = od.isoformat() if hasattr(od, "isoformat") else od

    mean_score = round(
        sum(float(n.get("combined") or 0) for n in night_dicts) / max(len(night_dicts), 1),
        1,
    )

    benchmark = snapshot.get("flight_benchmark") or {}
    low, high = routes["flight_benchmark_per_adult"]
    if benchmark:
        low = int(benchmark.get("per_adult_low_usd") or low)
        high = int(benchmark.get("per_adult_high_usd") or high)

    flight_note = (flight_result or {}).get("message") or (
        benchmark.get("note")
        or "Confirm live prices on Kayak or Google Flights before booking."
    )

    aviasales_url = links.get("aviasales")
    aviasales_link = (
        f'<a class="btn-link secondary" href="{_escape(aviasales_url)}">Aviasales</a>'
        if aviasales_url
        else ""
    )

    current_hotel_total = None
    if hotel_rows and hotel_rows[0].get("total") is not None:
        current_hotel_total = float(hotel_rows[0]["total"])

    night_count = (leave - arrive).days
    guide = fairbanks_guide(arrive=arrive, leave=leave)
    guide_html = _render_guide_sections(guide, routes)

    weather_report = build_aurora_weather_report(
        arrive=arrive,
        leave=leave,
        allow_network=allow_live_fetch,
    )
    flight_low, flight_high, flight_label = _flight_budget_from_sources(
        flight_result=flight_result,
        snapshot=snapshot,
        arrive=arrive,
        leave=leave,
        travelers=travelers,
        routes=routes,
    )

    budget = build_trip_budget(
        arrive=arrive,
        leave=leave,
        travelers=travelers,
        hotel_total=current_hotel_total,
        flight_party_low=flight_low,
        flight_party_high=flight_high,
        flight_label=flight_label,
        include_car_rental=False,
        include_chena=False,
        include_chena_shuttle=False,
        include_aurora_tour=False,
        aurora_tour_maps_url=str(weather_report.get("tour_maps_url") or ""),
    )

    mapping = {
        "title": "Alaska Northern Lights — Fairbanks Trip Briefing",
        "subtitle": (
            f"Los Angeles ({HOME_AIRPORT}) to Fairbanks · {travelers} travelers · "
            f"arrive {arrive.strftime('%B %d, %Y')} · {night_count} nights"
        ),
        "hero_image_url": _HERO_IMAGE,
        "travelers": str(travelers),
        "arrive": arrive.strftime("%b %d, %Y"),
        "leave": leave.strftime("%b %d, %Y"),
        "night_count": str(night_count),
        "aurora_intro": (
            "Late September is one of the best windows for aurora near Fairbanks: "
            "long dark nights, active aurora season, and strong darkness scores. "
            "Scores below combine night length and location — they do not predict clouds."
        ),
        "mean_aurora_score": str(mean_score),
        "aurora_table": _render_aurora_table(night_dicts),
        "aurora_strategy_section": _render_aurora_strategy_section(weather_report),
        "origin": HOME_AIRPORT,
        "no_nonstop_summary": routes["no_nonstop_summary"],
        "hubs_summary": routes["hubs_summary"],
        "anc_footnote": routes["anc_footnote"],
        "benchmark_low": str(low),
        "benchmark_high": str(high),
        "benchmark_party_low": str(low * travelers),
        "benchmark_party_high": str(high * travelers),
        "kayak_url": _escape(links.get("kayak") or ""),
        "google_flights_url": _escape(links.get("google_flights") or ""),
        "aviasales_link": aviasales_link,
        "flight_note": _escape(flight_note),
        "no_red_eye_summary": _escape(guide_html["no_red_eye_summary"]),
        "hotel_intro": (
            f"One room for {travelers} adults, filtered to queen / 2-queen room names. "
            "Highlighted card is the best value for two queen beds. Click hotel name to book."
        ),
        "hotel_cards": _render_hotel_cards(hotel_rows),
        "booking_url": _escape(booking_url),
        "optional_add_ons_section": _render_optional_add_ons_section(guide),
        "budget_section": _render_budget_section(budget),
        "compare_section": "",
        "hot_springs_section": guide_html["hot_springs_section"],
        "markets_section": guide_html["markets_section"],
        "native_foods_section": guide_html["native_foods_section"],
        "see_section": guide_html["see_section"],
        "eat_section": guide_html["eat_section"],
        "activities_section": guide_html["activities_section"],
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    return _fill_template(mapping)


def briefing_filename(*, arrive: date) -> str:
    return f"fairbanks-aurora-{arrive.isoformat()}.html"
