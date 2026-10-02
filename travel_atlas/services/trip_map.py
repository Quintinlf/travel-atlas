"""Folium trip maps: pins, lodging zones, ACG + aspect lines with layer flags."""

from __future__ import annotations

import json
from typing import Any, Sequence

import folium
from branca.element import Element
from folium import Map

from src_phase1.geo_grouping import in_west_europe_box
from travel_atlas.services.lodging_advisor import LocationPick

PLANET_GLYPHS = {
    "sun": "☉",
    "moon": "☽",
    "mercury": "☿",
    "venus": "♀",
    "mars": "♂",
    "jupiter": "♃",
    "saturn": "♄",
    "chiron": "⚷",
}

ASPECT_GLYPHS = {
    "sextile": "⚹",
    "square": "□",
    "trine": "△",
    "opposition": "☍",
}

ANGLE_SHORT = {
    "mc": "MC",
    "ic": "IC",
    "ascendant": "AS",
    "asc": "AS",
    "as": "AS",
    "descendant": "DS",
    "dsc": "DS",
    "ds": "DS",
}


def build_trip_map(
    pins: Sequence[Any],
    lodging_picks: Sequence[LocationPick],
    *,
    acg_lines: list[dict[str, Any]] | None = None,
    aspect_lines: list[dict[str, Any]] | None = None,
    companion_acg_lines: list[dict[str, Any]] | None = None,
    companion_aspect_lines: list[dict[str, Any]] | None = None,
    show_pins: bool = True,
    show_lodging: bool = True,
    show_acg: bool = True,
    show_aspects: bool = False,
    height: str = "560px",
) -> Map | None:
    coords: list[tuple[float, float]] = []
    for pin in pins:
        lat = getattr(pin, "latitude", None)
        lon = getattr(pin, "longitude", None)
        if lat is None or lon is None:
            continue
        if float(lat) == 0.0 and float(lon) == 0.0:
            continue
        coords.append((float(lat), float(lon)))

    if not coords and not lodging_picks:
        return None

    if coords:
        center_lat = sum(c[0] for c in coords) / len(coords)
        center_lon = sum(c[1] for c in coords) / len(coords)
        south = min(c[0] for c in coords)
        north = max(c[0] for c in coords)
        west = min(c[1] for c in coords)
        east = max(c[1] for c in coords)
    else:
        center_lat, center_lon = 51.5, -0.12
        south, north, west, east = 35.0, 60.0, -12.0, 20.0

    # Europe-scale window like astro.com: trip pins plus ocean/Africa margin.
    pad_lat, pad_lon = 12.0, 14.0
    bounds_sw = [max(-75.0, south - pad_lat), max(-180.0, west - pad_lon)]
    bounds_ne = [min(75.0, north + pad_lat), min(180.0, east + pad_lon)]
    view = (bounds_sw[0], bounds_sw[1], bounds_ne[0], bounds_ne[1])

    fmap = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=5,
        min_zoom=3,
        max_bounds=[bounds_sw, bounds_ne],
        max_bounds_viscosity=1.0,
        world_copy_jump=False,
        control_scale=True,
        tiles=None,
    )
    folium.TileLayer(
        "OpenStreetMap",
        no_wrap=True,
        min_zoom=3,
        max_zoom=18,
    ).add_to(fmap)
    fmap.fit_bounds([bounds_sw, bounds_ne])
    fmap.options["maxBounds"] = [bounds_sw, bounds_ne]
    fmap.options["minZoom"] = 3

    fmap._acg_label_specs = []  # type: ignore[attr-defined]

    if show_pins:
        for pin in pins:
            lat = getattr(pin, "latitude", None)
            lon = getattr(pin, "longitude", None)
            if lat is None or lon is None or (float(lat) == 0 and float(lon) == 0):
                continue
            folium.CircleMarker(
                location=[float(lat), float(lon)],
                radius=4,
                color="#6b7280",
                fill=True,
                fill_opacity=0.45,
                opacity=0.55,
                popup=getattr(pin, "name", "pin"),
            ).add_to(fmap)

    city_coords: dict[str, list[tuple[float, float]]] = {}
    for pin in pins:
        city = (getattr(pin, "city", None) or getattr(pin, "region", None) or "").strip()
        lat = getattr(pin, "latitude", None)
        lon = getattr(pin, "longitude", None)
        if not city or lat is None or lon is None:
            continue
        if float(lat) == 0 and float(lon) == 0:
            continue
        city_coords.setdefault(city, []).append((float(lat), float(lon)))

    if show_lodging:
        for pick in lodging_picks:
            samples = city_coords.get(pick.city) or []
            if not samples:
                continue
            lat = sum(p[0] for p in samples) / len(samples)
            lon = sum(p[1] for p in samples) / len(samples)
            folium.Circle(
                location=[lat, lon],
                radius=3500,
                color="#dc2626",
                weight=3,
                fill=True,
                fill_opacity=0.12,
                popup=f"Lodging zone: {pick.city} ({pick.pin_count} pins)",
            ).add_to(fmap)
            folium.Marker(
                location=[lat, lon],
                popup=f"<b>{pick.city}</b><br>{pick.rationale}",
                icon=folium.Icon(color="red", icon="home", prefix="fa"),
            ).add_to(fmap)

    if show_acg:
        for line in acg_lines or []:
            _add_polyline(
                fmap,
                line,
                color=_acg_color(line.get("body")),
                weight=5,
                opacity=0.95,
                bold=True,
                view=view,
            )
        for line in companion_acg_lines or []:
            _add_polyline(
                fmap,
                line,
                color=_companion_acg_color(line.get("body")),
                weight=4,
                opacity=0.75,
                bold=True,
                view=view,
                popup_extra="companion",
            )

    if show_aspects:
        for line in aspect_lines or []:
            planet = _planet_key(line.get("body"))
            aspect = line.get("aspect") or line.get("angle") or ""
            _add_polyline(
                fmap,
                line,
                color=_acg_color(planet),
                weight=1.5,
                opacity=0.55,
                bold=False,
                popup_extra=str(aspect),
                view=view,
            )
        for line in companion_aspect_lines or []:
            planet = _planet_key(line.get("body"))
            aspect = line.get("aspect") or line.get("angle") or ""
            _add_polyline(
                fmap,
                line,
                color=_companion_acg_color(planet),
                weight=1.25,
                opacity=0.45,
                bold=False,
                popup_extra=f"{aspect} · companion".strip(" ·"),
                view=view,
            )

    _attach_edge_glyph_overlay(fmap)
    fmap.get_root().height = height
    return fmap


def _planet_key(body: str | None) -> str:
    raw = (body or "").strip()
    return raw.split()[0].casefold() if raw else ""


def _planet_glyph(body: str | None) -> str:
    return PLANET_GLYPHS.get(_planet_key(body), "•")


def _aspect_glyph(aspect: str | None) -> str:
    text = (aspect or "").casefold()
    for name, glyph in ASPECT_GLYPHS.items():
        if name in text:
            return glyph
    return ""


def _angle_short(angle: str | None) -> str:
    return ANGLE_SHORT.get((angle or "").casefold(), (angle or "").strip())


def _inside(lat: float, lon: float, view: tuple[float, float, float, float]) -> bool:
    south, west, north, east = view
    return south <= lat <= north and west <= lon <= east


def _seg_edge_hits(
    a: tuple[float, float],
    b: tuple[float, float],
    view: tuple[float, float, float, float],
) -> list[tuple[float, float, str]]:
    south, west, north, east = view
    lat1, lon1 = a
    lat2, lon2 = b
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    hits: list[tuple[float, float, str]] = []

    def consider(t: float, lat: float, lon: float, edge: str) -> None:
        if t < -1e-9 or t > 1 + 1e-9:
            return
        if south - 1e-6 <= lat <= north + 1e-6 and west - 1e-6 <= lon <= east + 1e-6:
            hits.append((lat, lon, edge))

    if abs(dlat) > 1e-12:
        t = (north - lat1) / dlat
        consider(t, north, lon1 + t * dlon, "n")
        t = (south - lat1) / dlat
        consider(t, south, lon1 + t * dlon, "s")
    if abs(dlon) > 1e-12:
        t = (east - lon1) / dlon
        consider(t, lat1 + t * dlat, east, "e")
        t = (west - lon1) / dlon
        consider(t, lat1 + t * dlat, west, "w")
    return hits


def _clip_to_view(
    points: list[tuple[float, float]],
    view: tuple[float, float, float, float],
) -> list[tuple[float, float]]:
    """Keep the polyline inside the map window (astro.com crop)."""
    if len(points) < 2:
        return points
    out: list[tuple[float, float]] = []
    for a, b in zip(points, points[1:]):
        a_in = _inside(*a, view)
        b_in = _inside(*b, view)
        hits = _seg_edge_hits(a, b, view)
        chunk: list[tuple[float, float]] = []
        if a_in:
            chunk.append(a)
        for lat, lon, _edge in hits:
            chunk.append((lat, lon))
        if b_in:
            chunk.append(b)
        if not chunk and hits:
            chunk = [(h[0], h[1]) for h in hits]
        if not chunk:
            continue
        if out and chunk and out[-1] == chunk[0]:
            chunk = chunk[1:]
        out.extend(chunk)
    return out


def _edge_label_sites(
    points: list[tuple[float, float]],
    view: tuple[float, float, float, float],
) -> list[tuple[float, float, str]]:
    south, west, north, east = view
    sites: list[tuple[float, float, str]] = []
    seen: set[tuple[float, float, str]] = set()
    for a, b in zip(points, points[1:]):
        for lat, lon, edge in _seg_edge_hits(a, b, view):
            key = (round(lat, 3), round(lon, 3), edge)
            if key in seen:
                continue
            seen.add(key)
            sites.append((lat, lon, edge))
    if len(sites) >= 2:
        return sites[:4]
    # Meridian / short segment: pin labels to north+south (or east+west).
    if not points:
        return []
    lons = [p[1] for p in points]
    lats = [p[0] for p in points]
    if max(lons) - min(lons) < 1.5:
        lon = sum(lons) / len(lons)
        if west <= lon <= east:
            return [(north, lon, "n"), (south, lon, "s")]
    if max(lats) - min(lats) < 1.5:
        lat = sum(lats) / len(lats)
        if south <= lat <= north:
            return [(lat, west, "w"), (lat, east, "e")]
    return sites


def _inset(
    lat: float,
    lon: float,
    edge: str,
    view: tuple[float, float, float, float],
) -> tuple[float, float]:
    south, west, north, east = view
    dlat = max(0.35, (north - south) * 0.018)
    dlon = max(0.35, (east - west) * 0.018)
    if edge == "n":
        return lat - dlat, lon
    if edge == "s":
        return lat + dlat, lon
    if edge == "e":
        return lat, lon - dlon
    return lat, lon + dlon


def _add_polyline(
    fmap: Map,
    line: dict[str, Any],
    *,
    color: str,
    weight: float,
    opacity: float,
    bold: bool,
    view: tuple[float, float, float, float],
    popup_extra: str = "",
) -> None:
    raw = [(float(p[0]), float(p[1])) for p in (line.get("points") or []) if len(p) >= 2]
    if len(raw) < 2:
        return
    # Draw the full line so panning/zooming never drops it; only labels follow the frame.
    planet_g = _planet_glyph(line.get("body"))
    if bold:
        angle = _angle_short(line.get("angle"))
        label = f"{planet_g} {angle}"
        size, font_weight = 18, 800
    else:
        aspect = popup_extra or str(line.get("aspect") or "")
        aspect_g = _aspect_glyph(aspect)
        label = f"{planet_g} {aspect_g}".strip()
        size, font_weight = 12, 500
    folium.PolyLine(
        locations=raw,
        color=color,
        weight=weight,
        opacity=opacity,
        popup=label,
    ).add_to(fmap)
    specs = getattr(fmap, "_acg_label_specs", None)
    if specs is not None:
        specs.append(
            {
                "points": raw,
                "color": color,
                "text": label,
                "size": size,
                "weight": font_weight,
            }
        )


def _attach_edge_glyph_overlay(fmap: Map) -> None:
    """Put ☉ AS / ♄ MC labels in the map margin (outside tiles), updating on pan/zoom."""
    specs = getattr(fmap, "_acg_label_specs", None) or []
    if not specs:
        return
    fmap.get_root().header.add_child(
        Element(
            """
<style>
.leaflet-container { overflow: visible !important; }
.acg-edge-label {
  position: absolute;
  transform: translate(-50%, -50%);
  font-family: Georgia, 'Times New Roman', serif;
  pointer-events: none;
  z-index: 1200;
  white-space: nowrap;
  line-height: 1;
  text-shadow: 0 0 4px #fff, 0 0 8px #fff, 0 1px 0 #fff;
}
</style>
"""
        )
    )
    map_name = fmap.get_name()
    payload = json.dumps(specs)
    fmap.get_root().html.add_child(
        Element(
            f"""
<script>
(function() {{
  var specs = {payload};
  function hitSeg(a, b, south, west, north, east) {{
    var hits = [];
    function add(t, lat, lon, edge) {{
      if (t < -1e-8 || t > 1 + 1e-8) return;
      if (lat >= south - 1e-6 && lat <= north + 1e-6 && lon >= west - 1e-6 && lon <= east + 1e-6)
        hits.push({{lat: lat, lon: lon, edge: edge}});
    }}
    var dlat = b[0] - a[0], dlon = b[1] - a[1];
    if (Math.abs(dlat) > 1e-12) {{
      var tn = (north - a[0]) / dlat; add(tn, north, a[1] + tn * dlon, 'n');
      var ts = (south - a[0]) / dlat; add(ts, south, a[1] + ts * dlon, 's');
    }}
    if (Math.abs(dlon) > 1e-12) {{
      var te = (east - a[1]) / dlon; add(te, a[0] + te * dlat, east, 'e');
      var tw = (west - a[1]) / dlon; add(tw, a[0] + tw * dlat, west, 'w');
    }}
    return hits;
  }}
  function place() {{
    var map = {map_name};
    if (!map || !map.getContainer) return;
    var el = map.getContainer();
    el.querySelectorAll('.acg-edge-label').forEach(function(n) {{ n.remove(); }});
    var b = map.getBounds();
    var south = b.getSouth(), west = b.getWest(), north = b.getNorth(), east = b.getEast();
    var pad = 22;
    specs.forEach(function(spec) {{
      var pts = spec.points;
      var seen = {{}};
      for (var i = 0; i < pts.length - 1; i++) {{
        hitSeg(pts[i], pts[i+1], south, west, north, east).forEach(function(h) {{
          var key = h.edge + ':' + h.lat.toFixed(3) + ':' + h.lon.toFixed(3);
          if (seen[key]) return;
          seen[key] = 1;
          var xy = map.latLngToContainerPoint([h.lat, h.lon]);
          if (h.edge === 'n') xy.y -= pad;
          if (h.edge === 's') xy.y += pad;
          if (h.edge === 'e') xy.x += pad;
          if (h.edge === 'w') xy.x -= pad;
          var d = document.createElement('div');
          d.className = 'acg-edge-label';
          d.textContent = spec.text;
          d.style.color = spec.color;
          d.style.fontSize = spec.size + 'px';
          d.style.fontWeight = spec.weight;
          d.style.left = xy.x + 'px';
          d.style.top = xy.y + 'px';
          el.appendChild(d);
        }});
      }}
    }});
  }}
  function boot() {{
    var map = {map_name};
    if (!map || !map.on) {{ setTimeout(boot, 80); return; }}
    map.on('moveend zoomend resize', place);
    map.whenReady(place);
    setTimeout(place, 200);
  }}
  boot();
}})();
</script>
"""
        )
    )


def _acg_color(body: str | None) -> str:
    # Jim Lewis / astro.com ACG palette (traditional seven) + Chiron.
    colors = {
        "sun": "#e39b00",
        "moon": "#6b7c8a",
        "mercury": "#2e8b57",
        "venus": "#3cb371",
        "mars": "#cc3333",
        "jupiter": "#3b6fd8",
        "saturn": "#8b4513",
        "chiron": "#be185d",
    }
    return colors.get(_planet_key(body), "#7c3aed")


def _companion_acg_color(body: str | None) -> str:
    """Distinct cooler palette so a second natal overlays cleanly."""
    colors = {
        "sun": "#fbbf24",
        "moon": "#cbd5e1",
        "mercury": "#67e8f9",
        "venus": "#a78bfa",
        "mars": "#fb7185",
        "jupiter": "#38bdf8",
        "saturn": "#a8a29e",
        "chiron": "#5eead4",
    }
    return colors.get(_planet_key(body), "#22d3ee")


def render_map_layer_toggles(
    *,
    key_prefix: str,
    acg_available: bool,
) -> dict[str, bool]:
    """Streamlit checkboxes for map layers. Returns flag dict."""
    import streamlit as st

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        show_pins = st.checkbox("Pins", value=True, key=f"{key_prefix}-pins")
    with c2:
        show_lodging = st.checkbox("Lodging zones", value=True, key=f"{key_prefix}-lodging")
    with c3:
        show_acg = st.checkbox(
            "Astrocartography",
            value=bool(acg_available),
            key=f"{key_prefix}-acg-v2",
            disabled=not acg_available,
            help="Angular ACG lines (MC/IC/Asc/Dsc) when birth data resolves.",
        )
    with c4:
        show_aspects = st.checkbox(
            "Major aspect lines",
            value=False,
            key=f"{key_prefix}-aspects",
            disabled=not acg_available,
            help="Sextile / square / trine / opposition to angles (MCP aspect_lines).",
        )
    return {
        "show_pins": show_pins,
        "show_lodging": show_lodging,
        "show_acg": show_acg,
        "show_aspects": show_aspects,
    }


def render_streamlit_map(
    fmap: Map | None,
    *,
    key: str = "atlas-map-glyphs-v13",
    height: int = 600,
    caption: str | None = None,
    return_clicks: bool = False,
) -> dict[str, Any] | None:
    import streamlit as st
    from streamlit_folium import st_folium

    if fmap is None:
        st.caption("No map coordinates available yet.")
        return None
    if caption is None:
        caption = (
            "Glyphs sit in the margin around the map (☉ AS / ♄ MC / ⚷ Chiron), not on the land. "
            "Lines stay drawn as you pan. ☉ gold · ☿/♀ green · ♂ red · ♃ blue · ♄ brown · ⚷ rose."
        )
    if caption:
        st.caption(caption)
    returned = ["last_object_clicked_tooltip"] if return_clicks else []
    clicked = st_folium(
        fmap,
        width=None,
        height=height,
        returned_objects=returned,
        key=key,
    )
    if return_clicks:
        return clicked if isinstance(clicked, dict) else None
    return None


def _pin_city_label(pin: Any) -> str:
    city = (getattr(pin, "city", None) or "").strip()
    return city or "No city"


def _pin_has_coords(pin: Any) -> bool:
    lat = getattr(pin, "latitude", None)
    lon = getattr(pin, "longitude", None)
    if lat is None or lon is None:
        return False
    try:
        return float(lat) != 0.0 or float(lon) != 0.0
    except (TypeError, ValueError):
        return False


def build_focus_map(
    pins: Sequence[Any],
    *,
    height: str = "420px",
) -> Map | None:
    """Tight Folium map for a city/region pin subset (no ACG layers)."""
    coords: list[tuple[float, float, str]] = []
    for pin in pins:
        if not _pin_has_coords(pin):
            continue
        lat = float(pin.latitude)
        lon = float(pin.longitude)
        name = getattr(pin, "name", None) or "pin"
        coords.append((lat, lon, str(name)))
    if not coords:
        return None

    lats = [c[0] for c in coords]
    lngs = [c[1] for c in coords]
    center_lat = sum(lats) / len(lats)
    center_lng = sum(lngs) / len(lngs)
    fmap = folium.Map(
        location=[center_lat, center_lng],
        zoom_start=12 if len(coords) == 1 else 10,
        control_scale=True,
        tiles="OpenStreetMap",
    )
    for lat, lon, name in coords:
        folium.CircleMarker(
            location=[lat, lon],
            radius=7,
            color="#1d4ed8",
            fill=True,
            fill_opacity=0.75,
            popup=folium.Popup(name, max_width=260),
            tooltip=name,
        ).add_to(fmap)
    if len(coords) == 1:
        fmap.location = [coords[0][0], coords[0][1]]
        fmap.zoom_start = 13
    else:
        pad = 0.02
        fmap.fit_bounds(
            [
                [min(lats) - pad, min(lngs) - pad],
                [max(lats) + pad, max(lngs) + pad],
            ]
        )
    fmap.get_root().height = height
    return fmap


#: Itinerary legs for the West Europe browse dropdown (flowchart order).
_ALL_TRIP_PINS_LABEL = "All trip pins"

_WEST_EUROPE_LEG_ORDER = (
    "Scotland car loop (Dundee)",
    "Glasgow",
    "Northern/Central England",
    "London Hub",
    "SW England & Wales",
    "Ireland Loop",
    "Northern France & Paris",
    "Brittany & SW France",
    "Northern Spain / Basque",
    "Central & Southern Spain",
    "Portugal",
)

_SCOTLAND_CAR_LOOP_CITIES = frozenset(
    {
        "almondbank",
        "dalgety bay",
        "edinburgh",
        "perth",
        "saint andrews",
        "st andrews",
    }
)

_LONDON_HUB_CITIES = frozenset(
    {
        "bayswater",
        "bexley",
        "camden town",
        "canterbury",
        "city of london",
        "dover",
        "hackney",
        "hyde park",
        "islington",
        "kensington",
        "knightsbridge and belgravia",
        "london",
        "ponders end",
        "shepherds bush",
        "soho",
        "st james's",
        "west end",
        "west end of london",
        "whitechapel",
        "windsor",
    }
)

_NORTH_CENTRAL_ENGLAND_CITIES = frozenset(
    {
        "belper",
        "birmingham",
        "castle donington",
        "leeds",
        "manchester",
        "manchester city centre",
        "nottingham",
        "oldbury",
        "redcar",
        "york",
    }
)

_SW_ENGLAND_CITIES = frozenset(
    {
        "bovington camp",
        "tintagel",
        "llangefni",
    }
)

_FRANCE_NORTH_CITIES = frozenset(
    {
        "amiens",
        "bondy",
        "coquelles",
        "cormontreuil",
        "gare",
        "le chesnay",
        "levallois-perret",
        "maison blanche",
        "paris",
        "porte saint-denis",
        "quinze-vingts",
        "reims",
        "saint-ambroise",
        "saint-ouen",
        "salpêtrière",
        "vanves",
        "versailles",
        "vimoutiers",
    }
)

_FRANCE_BRITTANY_SW_CITIES = frozenset(
    {
        "agde",
        "bordeaux",
        "carnac",
        "cenon",
        "cognac",
        "lorquin",
        "lyon 02",
        "marignane",
        "mauron",
        "montpellier",
        "mûr-de-bretagne",
        "neuvy-saint-sépulchre",
        "primary",
        "rennes",
        "salon-de-provence",
        "toulouse",
        "verdun-sur-le-doubs",
    }
)

_SPAIN_NORTH_CITIES = frozenset(
    {
        "donostia / san sebastián",
        "fisterra",
        "potes",
        "vilalba",
    }
)

_SPAIN_SOUTH_CITIES = frozenset(
    {
        "granada",
        "marbella",
        "palacio",
        "san javier",
        "tarifa",
        "telde",
        "toledo",
        "villarta de los montes",
    }
)


def _normalize_city_key(value: str | None) -> str:
    return (value or "").strip().casefold()


def _plausible_west_europe(lat: float, lon: float) -> bool:
    # Rough mainland + Ireland/UK box; excludes bad reverse-geocodes overseas.
    return in_west_europe_box(lat, lon)


SCOTLAND_CAR_LOOP_LABEL = "Scotland car loop (Dundee)"


def default_leg_index(names: Sequence[str]) -> int:
    """Open pin browse on the Scotland car loop when that leg exists."""
    listed = list(names)
    if SCOTLAND_CAR_LOOP_LABEL in listed:
        return listed.index(SCOTLAND_CAR_LOOP_LABEL)
    return 0


def default_city_index(city_options: Sequence[str]) -> int:
    """Open the city dropdown on Edinburgh when present."""
    for index, name in enumerate(city_options):
        if str(name).strip().casefold() == "edinburgh":
            return index
    return 0


def travel_leg_for_pin(pin: Any) -> str:
    """Map a pin onto a West Europe itinerary leg (flowchart buckets)."""
    from src_phase1.geo_grouping import destination_label, top_level_destination

    kind, label = top_level_destination(pin)
    region = destination_label(kind, label)
    city = _normalize_city_key(getattr(pin, "city", None))
    lat = lon = None
    if _pin_has_coords(pin):
        lat = float(pin.latitude)
        lon = float(pin.longitude)
        if not _plausible_west_europe(lat, lon):
            lat = lon = None

    if region.startswith("Scotland"):
        name = (getattr(pin, "name", None) or "").strip().casefold()
        if city == "glasgow" or name == "glasgow":
            return "Glasgow"
        if city in _SCOTLAND_CAR_LOOP_CITIES:
            return "Scotland car loop (Dundee)"
        return "Scotland car loop (Dundee)"
    if region == "Ireland":
        return "Ireland Loop"
    if region == "Portugal":
        return "Portugal"

    if region.startswith("Wales") or city in _SW_ENGLAND_CITIES:
        return "SW England & Wales"

    if region.startswith("England"):
        if city in _SW_ENGLAND_CITIES:
            return "SW England & Wales"
        # Prefer plausible coords so mislabeled cities (e.g. Belper + London lat/lng) land right.
        if lat is not None and lon is not None:
            if lat < 51.2 and lon < -1.4:
                return "SW England & Wales"
            if 51.0 <= lat <= 51.75 and -0.9 <= lon <= 1.6:
                return "London Hub"
            if lat >= 52.0:
                return "Northern/Central England"
        if city in _LONDON_HUB_CITIES:
            return "London Hub"
        if city in _NORTH_CENTRAL_ENGLAND_CITIES:
            return "Northern/Central England"
        return "Northern/Central England"

    if region == "France":
        if city in _FRANCE_BRITTANY_SW_CITIES:
            return "Brittany & SW France"
        if city in _FRANCE_NORTH_CITIES:
            return "Northern France & Paris"
        if lat is not None and lon is not None:
            # Brittany / Atlantic west, or south of the Loire
            if lon < -1.0 or lat < 46.5:
                return "Brittany & SW France"
            return "Northern France & Paris"
        return "Northern France & Paris"

    if region == "Spain":
        if city in _SPAIN_NORTH_CITIES:
            return "Northern Spain / Basque"
        if city in _SPAIN_SOUTH_CITIES:
            return "Central & Southern Spain"
        if lat is not None and lon is not None:
            if lat >= 42.0:
                return "Northern Spain / Basque"
            return "Central & Southern Spain"
        return "Central & Southern Spain"

    return region


def _leg_travel_rank(name: str) -> tuple[int, str]:
    try:
        return (_WEST_EUROPE_LEG_ORDER.index(name), name)
    except ValueError:
        return (len(_WEST_EUROPE_LEG_ORDER), name)


def _city_mean_lat(city_pins: Sequence[Any]) -> float:
    lats = [
        float(p.latitude)
        for p in city_pins
        if _pin_has_coords(p) and _plausible_west_europe(float(p.latitude), float(p.longitude))
    ]
    if not lats:
        return -90.0
    return sum(lats) / len(lats)


def render_pins_by_region(pins: Sequence[Any], *, key_prefix: str = "pin-region") -> None:
    """Browse trip pins: itinerary leg → city, with a zoomed map and pin list."""
    import streamlit as st

    groups: dict[str, list[Any]] = {}
    for pin in pins:
        groups.setdefault(travel_leg_for_pin(pin), []).append(pin)
    if not groups:
        st.caption("No pins in the current trip filter.")
        return

    ordered = sorted(groups.items(), key=lambda item: _leg_travel_rank(item[0]))
    st.subheader("Browse pins by itinerary leg")
    st.caption(
        "Legs follow your route: Scotland car loop (Dundee) → Glasgow → N/C England → London → SW & Wales → "
        "Ireland → N France/Paris → Brittany & SW France → Basque → S Spain → Portugal. "
        "Pick All trip pins for the full map. Cities within a leg are north → south."
    )
    names = [_ALL_TRIP_PINS_LABEL] + [name for name, _rows in ordered]
    counts = {name: len(rows) for name, rows in ordered}
    counts[_ALL_TRIP_PINS_LABEL] = len(pins)
    pick = st.selectbox(
        "Leg",
        names,
        index=default_leg_index(names),
        format_func=lambda n: f"{n} ({counts[n]})",
        key=f"{key_prefix}-leg-v5",
    )
    if pick == _ALL_TRIP_PINS_LABEL:
        region_pins = list(pins)
    else:
        region_pins = groups.get(pick) or []

    by_city: dict[str, list[Any]] = {}
    for pin in region_pins:
        by_city.setdefault(_pin_city_label(pin), []).append(pin)
    city_names = sorted(
        by_city.keys(),
        key=lambda c: (
            c == "No city",
            -_city_mean_lat(by_city[c]),
            c.lower(),
        ),
    )
    all_cities_label = (
        "All cities (entire trip)"
        if pick == _ALL_TRIP_PINS_LABEL
        else f"All cities in {pick}"
    )
    city_options = [all_cities_label] + city_names
    city_pick = st.selectbox(
        "City",
        city_options,
        index=default_city_index(city_options),
        format_func=lambda n: (
            n
            if n == all_cities_label
            else f"{n} ({len(by_city[n])})"
        ),
        key=f"{key_prefix}-city-v5",
    )
    if city_pick == all_cities_label:
        focus_pins = region_pins
        focus_title = pick
    else:
        focus_pins = by_city.get(city_pick) or []
        focus_title = f"{city_pick} · {pick}"

    with_coords = sum(
        1
        for p in focus_pins
        if _pin_has_coords(p)
        and _plausible_west_europe(float(p.latitude), float(p.longitude))
    )
    st.caption(
        f"{len(focus_pins)} pin(s) in {focus_title}"
        + (
            f" · {with_coords} with plausible map coords"
            if with_coords != len(focus_pins)
            else ""
        )
    )

    def _safe_key(part: str) -> str:
        return "".join(ch if ch.isalnum() else "-" for ch in part)[:48]

    map_col, list_col = st.columns([1.35, 1])
    with map_col:
        # Prefer pins with plausible WE coords so bad geocodes don't yank the zoom.
        map_pins = [
            p
            for p in focus_pins
            if _pin_has_coords(p)
            and _plausible_west_europe(float(p.latitude), float(p.longitude))
        ] or focus_pins
        focus_map = build_focus_map(map_pins)
        render_streamlit_map(
            focus_map,
            key=f"{key_prefix}-focus-{_safe_key(pick)}-{_safe_key(city_pick)}",
            height=440,
            caption="Blue markers = selected leg/city pins. Click a marker for the name.",
        )
    with list_col:
        st.dataframe(
            [
                {
                    "name": getattr(p, "name", ""),
                    "city": getattr(p, "city", "") or "No city",
                    "lat": getattr(p, "latitude", None),
                    "lon": getattr(p, "longitude", None),
                }
                for p in sorted(
                    focus_pins,
                    key=lambda p: (
                        _pin_city_label(p).lower(),
                        (getattr(p, "name", None) or "").lower(),
                    ),
                )
            ],
            hide_index=True,
            use_container_width=True,
            height=440,
        )
