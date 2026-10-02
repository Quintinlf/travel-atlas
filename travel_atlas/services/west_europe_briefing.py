"""HTML trip briefing for the West Europe plan (print → Save as PDF)."""

from __future__ import annotations

import html
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from travel_atlas.services.static_acg_map import (
    DEFAULT_WEST_EUROPE_BBOX,
    bbox_for_leg_pins,
    bbox_from_coords,
    remote_image_to_data_uri,
    render_acg_data_uri,
)
from travel_atlas.services.trip_map import (
    _WEST_EUROPE_LEG_ORDER,
    travel_leg_for_pin,
)

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent / "templates" / "west_europe_trip_briefing.html"
)
_LEG_DAYS_PATH = _DATA_DIR / "west_europe_leg_days.json"
_SCOTLAND_HOTELS_PATH = _DATA_DIR / "scotland_hotels.json"

_HERO_IMAGE = (
    "https://images.unsplash.com/photo-1505761671935-60b3a7427bad"
    "?auto=format&fit=crop&w=1600&q=80"
)

_MAX_PINS_PER_CITY = 6
_MAX_CITIES_PER_LEG = 8

ChartLayers = tuple[list[dict[str, Any]], list[dict[str, Any]]]


def _escape(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_leg_plan() -> dict[str, Any]:
    return _load_json(_LEG_DAYS_PATH)


def load_scotland_hotels() -> dict[str, Any]:
    return _load_json(_SCOTLAND_HOTELS_PATH)


def total_planned_days(leg_plan: dict[str, Any] | None = None) -> int:
    plan = leg_plan or load_leg_plan()
    return int(plan.get("total_days") or sum(int(leg["days"]) for leg in plan["legs"]))


def _pin_plausible(pin: Any) -> bool:
    lat = getattr(pin, "latitude", None)
    lon = getattr(pin, "longitude", None)
    if lat is None or lon is None:
        return False
    try:
        lat_f, lon_f = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    if lat_f == 0.0 and lon_f == 0.0:
        return False
    from src_phase1.geo_grouping import in_west_europe_box

    return in_west_europe_box(lat_f, lon_f)


def _group_pins_by_leg(pins: Sequence[Any]) -> dict[str, list[Any]]:
    groups: dict[str, list[Any]] = defaultdict(list)
    for pin in pins:
        if not _pin_plausible(pin):
            continue
        groups[travel_leg_for_pin(pin)].append(pin)
    return groups


def _overview_bbox(pins: Sequence[Any]) -> tuple[float, float, float, float]:
    coords: list[tuple[float, float]] = []
    for pin in pins:
        if not _pin_plausible(pin):
            continue
        coords.append((float(pin.latitude), float(pin.longitude)))
    if len(coords) < 3:
        return DEFAULT_WEST_EUROPE_BBOX
    return bbox_from_coords(coords, pad_frac=0.12, min_pad=1.0, fallback=DEFAULT_WEST_EUROPE_BBOX)


def _leg_markers(leg_pins: Sequence[Any], *, limit: int = 6) -> list[tuple[float, float, str]]:
    """City centroids, densest first — map renderer further thins for spacing."""
    by_city: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for pin in leg_pins:
        city = (getattr(pin, "city", None) or "").strip()
        if not city:
            continue
        by_city[city].append((float(pin.latitude), float(pin.longitude)))
    markers: list[tuple[float, float, str]] = []
    for city, pts in sorted(by_city.items(), key=lambda item: -len(item[1]))[:limit]:
        lat = sum(p[0] for p in pts) / len(pts)
        lon = sum(p[1] for p in pts) / len(pts)
        markers.append((lat, lon, city))
    return markers


def _natal_caption(traveler: Mapping[str, Any] | None) -> str:
    if not traveler:
        return ""
    name = traveler.get("display_name") or "Traveler"
    return (
        f"{name} · {traveler.get('birth_date') or '—'} "
        f"{traveler.get('birth_time') or '—'} "
        f"{traveler.get('birth_timezone') or '—'} · "
        f"{traveler.get('birth_place') or '—'}"
    )


def _resolve_layers(
    traveler: Mapping[str, Any] | None,
    layers: ChartLayers | None,
) -> ChartLayers | None:
    if layers is not None:
        return layers
    if not traveler:
        return None
    from travel_atlas.services.astro_helper import chart_layers_for_traveler

    angular, aspects, msg = chart_layers_for_traveler(dict(traveler))
    if msg != "ok":
        return None
    return (list(angular), list(aspects))


def _acg_pair_html(
    *,
    primary: Mapping[str, Any] | None,
    companion: Mapping[str, Any] | None,
    primary_layers: ChartLayers | None,
    companion_layers: ChartLayers | None,
    bbox: tuple[float, float, float, float],
    markers: Sequence[tuple[float, float, str]] | None = None,
    region_label: str = "",
) -> str:
    panels: list[str] = []
    for traveler, layers in ((primary, primary_layers), (companion, companion_layers)):
        if not traveler or not layers:
            continue
        angular, aspects = layers
        name = str(traveler.get("display_name") or "Traveler")
        title = f"{name}" + (f" — {region_label}" if region_label else "")
        uri = render_acg_data_uri(
            angular_lines=angular,
            aspect_lines=aspects,
            bbox=bbox,
            title=title,
            markers=markers,
        )
        panels.append(
            f"""
      <figure class="acg-panel">
        <img class="acg-map" src="{uri}" alt="{_escape(title)} astrocartography" />
        <figcaption>{_escape(_natal_caption(traveler))}
          · angular lines + thin aspects · glyphs outside frame</figcaption>
      </figure>
"""
        )
    if not panels:
        return ""
    return f'<div class="acg-pair">{"".join(panels)}</div>'


def _pdf_safe_maps_url(
    name: str,
    *,
    lat: float | None = None,
    lon: float | None = None,
    city: str = "",
) -> str:
    """PDF-safe Google Maps link (no ``?api=1&query=`` query strings).

    ``/maps/place/{name}/@{lat},{lng}`` often redirects to empty ``/place//@coords``
    (blank sidebar). Prefer ``/maps/search/{name}/@{lat},{lng},15z`` when coords
    exist; otherwise Alaska-style ``/maps/search/{name}``.
    """
    from urllib.parse import quote_plus

    label = (name or "place").strip() or "place"
    try:
        lat_f = float(lat) if lat is not None else 0.0
        lon_f = float(lon) if lon is not None else 0.0
    except (TypeError, ValueError):
        lat_f = lon_f = 0.0
    if lat_f or lon_f:
        return (
            f"https://www.google.com/maps/search/{quote_plus(label)}"
            f"/@{lat_f},{lon_f},15z"
        )
    city = (city or "").strip()
    query = f"{label} {city}".strip() if city else label
    return f"https://www.google.com/maps/search/{quote_plus(query)}"


def _is_fragile_maps_search_url(url: str) -> bool:
    """True for Maps URLs that break in PDF viewers or resolve to empty places."""
    lower = (url or "").casefold()
    if "maps/search/?api=1" in lower or "maps/search?api=1" in lower:
        return True
    # Bare /place//@lat,lng or /place/{slug}/@… that Google empties out.
    if "/maps/place/" in lower:
        return True
    return False


def _hotel_maps_url(hotel: Mapping[str, Any], city: str = "") -> str:
    """Maps button for a Scotland hotel card — prefer lat/lng, else safe path URL."""
    name = str(hotel.get("name") or "hotel").strip()
    lat = hotel.get("lat", hotel.get("latitude"))
    lon = hotel.get("lng", hotel.get("longitude"))
    try:
        lat_f = float(lat) if lat is not None else None
        lon_f = float(lon) if lon is not None else None
    except (TypeError, ValueError):
        lat_f = lon_f = None
    if lat_f is not None and lon_f is not None and (lat_f or lon_f):
        return _pdf_safe_maps_url(name, lat=lat_f, lon=lon_f, city=city)

    override = str(hotel.get("maps_url") or "").strip()
    if override and not _is_fragile_maps_search_url(override):
        return override
    return _pdf_safe_maps_url(name, city=city)


def _pin_maps_url(pin: Any) -> str:
    """Build a Google Maps link for a saved pin (PDF-safe path URLs)."""
    for attr in ("google_maps_url", "maps_url", "url"):
        raw = getattr(pin, attr, None)
        if raw and not _is_fragile_maps_search_url(str(raw)):
            return str(raw)
    raw_json = getattr(pin, "raw_json", None)
    if raw_json:
        try:
            payload = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
            if isinstance(payload, dict):
                for key in ("url", "googleMapsUrl", "google_maps_url"):
                    if payload.get(key) and not _is_fragile_maps_search_url(
                        str(payload[key])
                    ):
                        return str(payload[key])
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    name = (getattr(pin, "name", None) or "place").strip()
    try:
        lat = float(getattr(pin, "latitude"))
        lon = float(getattr(pin, "longitude"))
    except (TypeError, ValueError, AttributeError):
        lat = lon = 0.0
    if lat or lon:
        return _pdf_safe_maps_url(name, lat=lat, lon=lon)
    # Name only — do not append city (Takeout city is often wrong).
    return _pdf_safe_maps_url(name)


def _render_leg_pin_highlights(leg_pins: Sequence[Any]) -> str:
    by_city: dict[str, list[Any]] = defaultdict(list)
    for pin in leg_pins:
        city = (getattr(pin, "city", None) or getattr(pin, "region", None) or "Other").strip()
        by_city[city].append(pin)

    ordered_cities = sorted(by_city.items(), key=lambda item: (-len(item[1]), item[0].casefold()))
    chunks: list[str] = []
    for city, city_pins in ordered_cities[:_MAX_CITIES_PER_LEG]:
        shown = city_pins[:_MAX_PINS_PER_CITY]
        items = "".join(
            f'<li><a href="{_escape(_pin_maps_url(p))}" target="_blank" rel="noopener">'
            f"{_escape(getattr(p, 'name', 'pin'))}</a></li>"
            for p in shown
        )
        extra = len(city_pins) - len(shown)
        more = f"<li><em>+{extra} more</em></li>" if extra > 0 else ""
        chunks.append(
            f'<div class="city-block"><div class="city-name">{_escape(city)}'
            f" ({len(city_pins)})</div><ul class=\"pin-list\">{items}{more}</ul></div>"
        )
    if not chunks:
        return "<p><em>No mappable saved pins in this leg yet.</em></p>"
    omitted = len(ordered_cities) - len(chunks)
    if omitted > 0:
        chunks.append(f"<p><em>+{omitted} more cities/areas in this leg.</em></p>")
    return "\n".join(chunks)


def _render_leg_sections(
    leg_plan: dict[str, Any],
    pins_by_leg: dict[str, list[Any]],
    *,
    primary: Mapping[str, Any] | None = None,
    companion: Mapping[str, Any] | None = None,
    primary_layers: ChartLayers | None = None,
    companion_layers: ChartLayers | None = None,
    include_acg_maps: bool = True,
    embed_images: bool = True,
) -> str:
    sections: list[str] = []
    for leg in leg_plan.get("legs") or []:
        name = leg["name"]
        days = int(leg["days"])
        blurb = leg.get("blurb") or ""
        image_url = leg.get("image_url") or ""
        leg_pins = pins_by_leg.get(name) or []
        region_img = ""
        if image_url:
            src = _embed_image_src(str(image_url), embed=embed_images)
            region_img = (
                f'<img class="region-photo" src="{_escape(src)}" '
                f'alt="{_escape(name)}" loading="lazy" />'
            )
        acg_html = ""
        if include_acg_maps and (primary_layers or companion_layers):
            bbox = bbox_for_leg_pins(name, leg_pins)
            acg_html = _acg_pair_html(
                primary=primary,
                companion=companion,
                primary_layers=primary_layers,
                companion_layers=companion_layers,
                bbox=bbox,
                markers=_leg_markers(leg_pins),
                region_label=name,
            )
            if acg_html:
                acg_html = (
                    f'<h3 class="acg-subhead">Astrocartography — {_escape(name)}</h3>'
                    f"{acg_html}"
                )
        sections.append(
            f"""
    <section class="card leg-card">
      {region_img}
      <div class="leg-heading">
        <h2>{_escape(name)}</h2>
        <span class="day-badge">{days} day{"s" if days != 1 else ""}</span>
      </div>
      <p>{_escape(blurb)}</p>
      {acg_html}
      <p><strong>{len(leg_pins)}</strong> saved pin(s) in this leg (highlights below).</p>
      {_render_leg_pin_highlights(leg_pins)}
    </section>
"""
        )
    return "\n".join(sections)


def _embed_image_src(url: str, *, embed: bool) -> str:
    """Prefer a data URI so headless PDF print does not need live network."""
    if not url:
        return ""
    if not embed:
        return url
    return remote_image_to_data_uri(url) or url


def _enrich_scotland_hotel_photos(hotels_data: dict[str, Any]) -> None:
    from travel_atlas.services.hotel_photo import resolve_hotel_photo

    for city_block in hotels_data.get("cities") or []:
        city = str(city_block.get("city") or "")
        for hotel in city_block.get("hotels") or []:
            if hotel.get("photo_url"):
                continue
            name = hotel.get("name")
            if not name:
                continue
            hit = resolve_hotel_photo(
                property_name=str(name),
                city=city,
                country="United Kingdom",
            )
            if hit and hit.url:
                hotel["photo_url"] = hit.url


def _embed_hotel_photos(hotels_data: dict[str, Any], *, embed: bool) -> None:
    if not embed:
        return
    for city_block in hotels_data.get("cities") or []:
        for hotel in city_block.get("hotels") or []:
            url = hotel.get("photo_url")
            if not url:
                continue
            embedded = remote_image_to_data_uri(str(url))
            if embedded:
                hotel["photo_url"] = embedded


def _render_scotland_hotels(hotels_data: dict[str, Any]) -> str:
    chunks: list[str] = []
    for city_block in hotels_data.get("cities") or []:
        city = city_block.get("city") or ""
        role = city_block.get("role") or ""
        airport = city_block.get("airport") or ""
        chunks.append(f"<h3>{_escape(city)} <small>({_escape(airport)})</small></h3>")
        chunks.append(f"<p>{_escape(role)}</p>")
        cards: list[str] = []
        for hotel in city_block.get("hotels") or []:
            starred = bool(hotel.get("airport_shuttle"))
            star = '<span class="star-tag">★ shuttle</span>' if starred else ""
            cls = "hotel-card starred" if starred else "hotel-card"
            booking = hotel.get("booking_url") or "#"
            maps = _hotel_maps_url(hotel, city=str(city))
            if booking == "#":
                booking = maps
            photo = hotel.get("photo_url") or ""
            if photo:
                img = (
                    f'<img class="hotel-photo" src="{_escape(photo)}" '
                    f'alt="{_escape(hotel.get("name"))}" loading="lazy" />'
                )
            else:
                img = '<div class="hotel-photo placeholder">No photo</div>'
            cards.append(
                f"""
        <div class="{cls}">
          {img}
          <div class="hotel-body">
          <h4 class="hotel-name">
            <a href="{_escape(booking)}">{_escape(hotel.get("name"))}</a>{star}
          </h4>
          <p class="hotel-meta">{_escape(hotel.get("area") or "")}</p>
          <p class="hotel-why">{_escape(hotel.get("why") or "")}</p>
          <p class="hotel-shuttle">{_escape(hotel.get("shuttle_note") or "")}</p>
          <p class="links">
            <a class="btn-link" href="{_escape(booking)}">Booking</a>
            <a class="btn-link secondary" href="{_escape(maps)}">Maps</a>
          </p>
          </div>
        </div>
"""
            )
        chunks.append(f'<div class="hotel-grid">{"".join(cards)}</div>')
    return "\n".join(chunks)


def _route_flow_line(leg_plan: dict[str, Any]) -> str:
    parts = [
        f"{leg['name']} ({int(leg['days'])}d)" for leg in leg_plan.get("legs") or []
    ]
    return " → ".join(parts)


def _fill_template(mapping: dict[str, str]) -> str:
    text = _TEMPLATE_PATH.read_text(encoding="utf-8")
    for key, value in mapping.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def build_west_europe_briefing_html(
    *,
    pins: Sequence[Any] | None = None,
    leg_plan: dict[str, Any] | None = None,
    scotland_hotels: dict[str, Any] | None = None,
    primary_traveler: Mapping[str, Any] | None = None,
    companion_traveler: Mapping[str, Any] | None = None,
    primary_layers: ChartLayers | None = None,
    companion_layers: ChartLayers | None = None,
    enrich_hotel_photos: bool = True,
    include_acg_maps: bool = True,
    embed_images: bool = True,
) -> str:
    """Build a self-contained West Europe HTML briefing for print / Save as PDF."""
    plan = leg_plan or load_leg_plan()
    hotels = json.loads(json.dumps(scotland_hotels or load_scotland_hotels()))
    if enrich_hotel_photos:
        _enrich_scotland_hotel_photos(hotels)
    _embed_hotel_photos(hotels, embed=embed_images)

    pin_list = list(pins or [])
    pins_by_leg = _group_pins_by_leg(pin_list)
    total_days = total_planned_days(plan)
    leg_names = [leg["name"] for leg in plan.get("legs") or []]

    p_layers = (
        _resolve_layers(primary_traveler, primary_layers) if include_acg_maps else None
    )
    c_layers = (
        _resolve_layers(companion_traveler, companion_layers) if include_acg_maps else None
    )

    overview_acg = ""
    if include_acg_maps and (p_layers or c_layers):
        overview_acg = _acg_pair_html(
            primary=primary_traveler,
            companion=companion_traveler,
            primary_layers=p_layers,
            companion_layers=c_layers,
            bbox=_overview_bbox(pin_list),
            markers=_leg_markers(
                [p for group in pins_by_leg.values() for p in group],
                limit=10,
            ),
            region_label="West Europe",
        )

    mapping = {
        "title": "West Europe Trip Briefing",
        "subtitle": (
            f"{total_days}-day open-jaw route · {len(leg_names)} itinerary legs · "
            "land EDI · exit Lisbon/Porto"
        ),
        "hero_image_url": _HERO_IMAGE,
        "total_days": str(total_days),
        "leg_count": str(len(leg_names)),
        "pin_count": str(sum(len(v) for v in pins_by_leg.values())),
        "route_flow": _escape(_route_flow_line(plan)),
        "route_debrief": _escape(plan.get("route_debrief") or ""),
        "overview_acg_section": overview_acg,
        "scotland_hotels_intro": _escape(hotels.get("intro") or ""),
        "scotland_hotels_section": _render_scotland_hotels(hotels),
        "leg_sections": _render_leg_sections(
            plan,
            pins_by_leg,
            primary=primary_traveler,
            companion=companion_traveler,
            primary_layers=p_layers,
            companion_layers=c_layers,
            include_acg_maps=include_acg_maps,
            embed_images=embed_images,
        ),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    _ = _WEST_EUROPE_LEG_ORDER
    return _fill_template(mapping)


def briefing_filename() -> str:
    return "west-europe-trip.html"


def briefing_pdf_filename() -> str:
    return "west-europe-trip.pdf"


def try_print_html_to_pdf(html_path: Path, pdf_path: Path) -> bool:
    """Best-effort Chromium/Edge headless print on Windows. Returns True on success."""
    import shutil
    import subprocess

    candidates = [
        shutil.which("msedge"),
        shutil.which("chrome"),
        shutil.which("google-chrome"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    browser = next((c for c in candidates if c and Path(c).exists()), None)
    if not browser:
        return False
    html_uri = html_path.resolve().as_uri()
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        browser,
        "--headless=new",
        "--disable-gpu",
        f"--print-to-pdf={pdf_path.resolve()}",
        "--no-pdf-header-footer",
        html_uri,
    ]
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0 and pdf_path.is_file() and pdf_path.stat().st_size > 0
