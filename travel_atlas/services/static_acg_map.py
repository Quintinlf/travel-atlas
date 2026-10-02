"""Static AstroClick-style astrocartography maps for HTML/PDF briefings."""

from __future__ import annotations

import base64
import io
import json
import math
import urllib.error
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Any, Sequence

from travel_atlas.services.trip_map import (
    PLANET_GLYPHS,
    _acg_color,
    _angle_short,
    _edge_label_sites,
    _planet_key,
)

DEFAULT_WEST_EUROPE_BBOX = (35.0, -12.5, 62.0, 12.0)

_GEOJSON_10M = (
    Path(__file__).resolve().parent.parent / "data" / "ne_10m_admin_0_countries.geojson"
)
_GEOJSON_50M = (
    Path(__file__).resolve().parent.parent / "data" / "ne_50m_admin_0_countries.geojson"
)
_GEOJSON_110M = (
    Path(__file__).resolve().parent.parent / "data" / "ne_110m_admin_0_countries.geojson"
)


def _geojson_path() -> Path:
    for path in (_GEOJSON_10M, _GEOJSON_50M, _GEOJSON_110M):
        if path.is_file():
            return path
    return _GEOJSON_110M

_PLANET_ASCII = {
    "sun": "Su",
    "moon": "Mo",
    "mercury": "Me",
    "venus": "Ve",
    "mars": "Ma",
    "jupiter": "Ju",
    "saturn": "Sa",
    "chiron": "Chi",
}

# Wide regional frames (AstroClick-like; not city-tight zooms).
LEG_ACG_BBOX: dict[str, tuple[float, float, float, float]] = {
    "Scotland car loop (Dundee)": (54.8, -7.8, 59.0, -0.5),
    "Glasgow": (54.8, -7.8, 59.0, -0.5),
    "Northern/Central England": (51.8, -4.2, 55.5, 0.8),
    "London Hub": (50.6, -2.2, 52.6, 1.4),
    "SW England & Wales": (50.0, -6.2, 53.4, -1.4),
    "Ireland Loop": (51.2, -10.8, 55.5, -5.2),
    "Northern France & Paris": (46.8, -2.2, 51.4, 5.2),
    "Brittany & SW France": (42.8, -5.2, 49.0, 4.8),
    "Northern Spain / Basque": (41.0, -10.0, 44.5, 0.2),
    "Central & Southern Spain": (35.8, -8.0, 42.0, 0.8),
    "Portugal": (36.5, -10.0, 42.5, -5.5),
}

_MAJOR_LABELS = {
    "United Kingdom",
    "Ireland",
    "France",
    "Spain",
    "Portugal",
    "Belgium",
    "Netherlands",
    "Germany",
    "Switzerland",
    "Italy",
    "Morocco",
}

_TILE_UA = "TravelAtlas/1.0 (personal offline briefing; contact: local)"
_TILE_CACHE = (
    Path(__file__).resolve().parent.parent.parent / "output" / "briefing_assets" / "basemap_tiles"
)
# Esri light-gray canvas (no API key). Path order is z/y/x.
_TILE_URLS = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
)


def _lonlat_to_tile(lon: float, lat: float, z: int) -> tuple[int, int]:
    lat = max(min(lat, 85.05112878), -85.05112878)
    n = 2**z
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n)
    return max(0, min(n - 1, x)), max(0, min(n - 1, y))


def _tile_bounds(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    n = 2**z
    west = x / n * 360.0 - 180.0
    east = (x + 1) / n * 360.0 - 180.0

    def lat_of(ty: int) -> float:
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * ty / n))))

    north = lat_of(y)
    south = lat_of(y + 1)
    return south, west, north, east


def _tile_looks_bad(img: Any) -> bool:
    """Reject OSM block / blank pages — not pale Esri light-gray basemap tiles."""
    try:
        sample = img.resize((48, 48))
        pixels = list(sample.getdata())
    except Exception:
        return True
    if len(pixels) < 10:
        return True
    # Access-blocked pages are almost pure white with a few dark text pixels.
    pure_white = sum(1 for c in pixels if c[0] >= 248 and c[1] >= 248 and c[2] >= 248)
    dark = sum(1 for c in pixels if max(c) < 90)
    if pure_white / len(pixels) > 0.82 and dark >= 3:
        return True
    return False


def _fetch_tile(z: int, x: int, y: int) -> Any | None:
    from PIL import Image
    import time

    n = 2**z
    if not (0 <= x < n and 0 <= y < n):
        return None
    _TILE_CACHE.mkdir(parents=True, exist_ok=True)
    cache_path = _TILE_CACHE / f"{z}_{x}_{y}.png"
    if cache_path.is_file():
        try:
            img = Image.open(cache_path).convert("RGB")
            if not _tile_looks_bad(img):
                return img
            cache_path.unlink(missing_ok=True)
        except OSError:
            pass
    for url_tmpl in _TILE_URLS:
        url = url_tmpl.format(z=z, x=x, y=y)
        for attempt in range(3):
            try:
                request = urllib.request.Request(url, headers={"User-Agent": _TILE_UA})
                with urllib.request.urlopen(request, timeout=20) as response:
                    raw = response.read()
                img = Image.open(io.BytesIO(raw)).convert("RGB")
                if _tile_looks_bad(img):
                    break
                img.save(cache_path, format="PNG")
                return img
            except (urllib.error.URLError, TimeoutError, OSError, ValueError):
                time.sleep(0.35 * (attempt + 1))
                continue
    return None


def _choose_zoom(south: float, west: float, north: float, east: float) -> int:
    span = max(north - south, east - west, 0.05)
    # Prefer fewer tiles so regional frames stay reliable.
    for z in range(7, 3, -1):
        if span * (2**z) / 360.0 <= 6:
            return z
    return 4


def _draw_tile_basemap(ax: Any, *, south: float, west: float, north: float, east: float) -> bool:
    """Carto light tiles; returns False if fetch fails (caller uses vector fallback)."""
    from PIL import Image
    import numpy as np

    z = _choose_zoom(south, west, north, east)
    x0, y1 = _lonlat_to_tile(west, south, z)  # south-west → larger y
    x1, y0 = _lonlat_to_tile(east, north, z)  # north-east → smaller y
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    tiles: list[tuple[int, int, Any]] = []
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            img = _fetch_tile(z, x, y)
            if img is None:
                return False
            tiles.append((x, y, img))
    if not tiles:
        return False

    tw, th = tiles[0][2].size
    cols = x1 - x0 + 1
    rows = y1 - y0 + 1
    mosaic = Image.new("RGB", (cols * tw, rows * th), (215, 228, 242))
    for x, y, img in tiles:
        mosaic.paste(img, ((x - x0) * tw, (y - y0) * th))

    # Geographic extent of the mosaic (tile corners).
    s0, w0, _, _ = _tile_bounds(z, x0, y1)
    _, _, n0, e0 = _tile_bounds(z, x1, y0)
    ax.imshow(
        np.asarray(mosaic),
        extent=[w0, e0, s0, n0],
        origin="upper",
        interpolation="bilinear",
        zorder=0,
        aspect="auto",
    )
    return True


def bbox_from_coords(
    coords: Sequence[tuple[float, float]],
    *,
    pad_frac: float = 0.18,
    min_pad: float = 0.35,
    fallback: tuple[float, float, float, float] = DEFAULT_WEST_EUROPE_BBOX,
) -> tuple[float, float, float, float]:
    if not coords:
        return fallback
    lats = [c[0] for c in coords]
    lons = [c[1] for c in coords]
    south, north = min(lats), max(lats)
    west, east = min(lons), max(lons)
    pad_lat = max(min_pad, (north - south) * pad_frac or min_pad)
    pad_lon = max(min_pad, (east - west) * pad_frac or min_pad)
    return (
        south - pad_lat,
        west - pad_lon,
        north + pad_lat,
        east + pad_lon,
    )


def bbox_for_leg_pins(
    leg_name: str,
    pins: Sequence[Any],
) -> tuple[float, float, float, float]:
    if leg_name in LEG_ACG_BBOX:
        return LEG_ACG_BBOX[leg_name]
    coords: list[tuple[float, float]] = []
    for pin in pins:
        try:
            lat = float(getattr(pin, "latitude"))
            lon = float(getattr(pin, "longitude"))
        except (TypeError, ValueError, AttributeError):
            continue
        if lat == 0.0 and lon == 0.0:
            continue
        coords.append((lat, lon))
    return bbox_from_coords(coords, pad_frac=0.35, min_pad=1.2, fallback=DEFAULT_WEST_EUROPE_BBOX)


def _line_points(line: dict[str, Any]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for pt in line.get("points") or []:
        if not pt or len(pt) < 2:
            continue
        try:
            out.append((float(pt[0]), float(pt[1])))
        except (TypeError, ValueError):
            continue
    return out


def _densify_polyline(
    pts: Sequence[tuple[float, float]], *, steps: int = 56
) -> list[tuple[float, float]]:
    if len(pts) < 2:
        return list(pts)
    out: list[tuple[float, float]] = []
    for i in range(len(pts) - 1):
        lat0, lon0 = pts[i]
        lat1, lon1 = pts[i + 1]
        for j in range(steps + 1):
            if i > 0 and j == 0:
                continue
            t = j / steps
            out.append((lat0 + (lat1 - lat0) * t, lon0 + (lon1 - lon0) * t))
    return out


@lru_cache(maxsize=1)
def _country_features() -> list[tuple[str, list[list[tuple[float, float]]]]]:
    path = _geojson_path()
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    features: list[tuple[str, list[list[tuple[float, float]]]]] = []
    for feature in data.get("features") or []:
        props = feature.get("properties") or {}
        name = str(props.get("NAME") or props.get("ADMIN") or props.get("name") or "")
        geom = feature.get("geometry") or {}
        gtype = geom.get("type")
        coords = geom.get("coordinates") or []
        if gtype == "Polygon":
            polys = [coords]
        elif gtype == "MultiPolygon":
            polys = coords
        else:
            continue
        rings: list[list[tuple[float, float]]] = []
        for poly in polys:
            if not poly:
                continue
            # Outer ring only; skip tiny islets that add noise at regional zoom.
            ring = [(float(lon), float(lat)) for lon, lat, *_ in poly[0]]
            if len(ring) < 8:
                continue
            xs = [p[0] for p in ring]
            ys = [p[1] for p in ring]
            if (max(xs) - min(xs)) * (max(ys) - min(ys)) < 0.002:
                continue
            rings.append(ring)
        if rings:
            features.append((name, rings))
    return features


def _ring_bbox(ring: Sequence[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return min(ys), min(xs), max(ys), max(xs)


def _ring_intersects_bbox(
    ring: Sequence[tuple[float, float]],
    *,
    south: float,
    west: float,
    north: float,
    east: float,
) -> bool:
    rs, rw, rn, re = _ring_bbox(ring)
    return not (re < west - 1 or rw > east + 1 or rn < south - 1 or rs > north + 1)


def _draw_vector_basemap(ax: Any, *, south: float, west: float, north: float, east: float) -> None:
    from matplotlib.collections import PolyCollection

    ax.set_facecolor("#d7e4f2")
    polys: list[list[tuple[float, float]]] = []
    label_candidates: list[tuple[float, str, float, float]] = []
    view_area = max((north - south) * (east - west), 0.1)

    for name, rings in _country_features():
        best_in_view: tuple[float, float, float] | None = None  # area, cx, cy
        for ring in rings:
            if not _ring_intersects_bbox(ring, south=south, west=west, north=north, east=east):
                continue
            polys.append(ring)
            if name not in _MAJOR_LABELS:
                continue
            xs = [p[0] for p in ring]
            ys = [p[1] for p in ring]
            # Approximate visible centroid by clipping ring extents to the view.
            cx = (max(west, min(xs)) + min(east, max(xs))) / 2
            cy = (max(south, min(ys)) + min(north, max(ys))) / 2
            vis_w = max(0.0, min(east, max(xs)) - max(west, min(xs)))
            vis_h = max(0.0, min(north, max(ys)) - max(south, min(ys)))
            vis_area = vis_w * vis_h
            if vis_area < view_area * 0.04:
                continue
            if best_in_view is None or vis_area > best_in_view[0]:
                best_in_view = (vis_area, cx, cy)
        if best_in_view and name in _MAJOR_LABELS:
            label_candidates.append((best_in_view[0], name, best_in_view[1], best_in_view[2]))

    if polys:
        coll = PolyCollection(
            polys,
            facecolors="#f3eee3",
            edgecolors="#7a7164",
            linewidths=0.35,
            antialiaseds=True,
            zorder=1,
        )
        ax.add_collection(coll)

    # Largest visible countries first; skip if too close to an already-placed label.
    label_candidates.sort(reverse=True)
    placed: list[tuple[float, float]] = []
    min_sep = max(north - south, east - west) * 0.18
    for _, name, cx, cy in label_candidates:
        if not (west + 0.08 < cx < east - 0.08 and south + 0.08 < cy < north - 0.08):
            continue
        if any(((cx - px) ** 2 + (cy - py) ** 2) ** 0.5 < min_sep for px, py in placed):
            continue
        ax.text(
            cx,
            cy,
            name,
            fontsize=7.2,
            color="#6b6256",
            ha="center",
            va="center",
            zorder=1.4,
            alpha=0.8,
            fontstyle="italic",
        )
        placed.append((cx, cy))


def _draw_country_names_only(
    ax: Any, *, south: float, west: float, north: float, east: float
) -> None:
    """Country italics over a tile basemap (no land polygons)."""
    view_area = max((north - south) * (east - west), 0.1)
    label_candidates: list[tuple[float, str, float, float]] = []
    for name, rings in _country_features():
        if name not in _MAJOR_LABELS:
            continue
        best_in_view: tuple[float, float, float] | None = None
        for ring in rings:
            if not _ring_intersects_bbox(ring, south=south, west=west, north=north, east=east):
                continue
            xs = [p[0] for p in ring]
            ys = [p[1] for p in ring]
            cx = (max(west, min(xs)) + min(east, max(xs))) / 2
            cy = (max(south, min(ys)) + min(north, max(ys))) / 2
            vis_w = max(0.0, min(east, max(xs)) - max(west, min(xs)))
            vis_h = max(0.0, min(north, max(ys)) - max(south, min(ys)))
            vis_area = vis_w * vis_h
            if vis_area < view_area * 0.04:
                continue
            if best_in_view is None or vis_area > best_in_view[0]:
                best_in_view = (vis_area, cx, cy)
        if best_in_view:
            label_candidates.append((best_in_view[0], name, best_in_view[1], best_in_view[2]))
    label_candidates.sort(reverse=True)
    placed: list[tuple[float, float]] = []
    min_sep = max(north - south, east - west) * 0.18
    for _, name, cx, cy in label_candidates:
        if not (west + 0.08 < cx < east - 0.08 and south + 0.08 < cy < north - 0.08):
            continue
        if any(((cx - px) ** 2 + (cy - py) ** 2) ** 0.5 < min_sep for px, py in placed):
            continue
        ax.text(
            cx,
            cy,
            name,
            fontsize=7.2,
            color="#6b6256",
            ha="center",
            va="center",
            zorder=1.4,
            alpha=0.75,
            fontstyle="italic",
        )
        placed.append((cx, cy))


def _angular_edge_label(line: dict[str, Any]) -> str:
    body = _planet_key(line.get("body"))
    glyph = PLANET_GLYPHS.get(body) or _PLANET_ASCII.get(body, (body or "?")[:2].title())
    angle = _angle_short(line.get("angle")) or ""
    return f"{glyph} {angle}".strip()


def _line_edge_sites(
    pts: Sequence[tuple[float, float]],
    view: tuple[float, float, float, float],
) -> list[tuple[float, float, str]]:
    """Edge hits for a polyline; if both ends sit inside the frame, extend the chord."""
    sites = _edge_label_sites(list(pts), view)
    if len(sites) >= 2:
        return sites
    if len(pts) < 2:
        return sites
    south, west, north, east = view
    lat0, lon0 = pts[0]
    lat1, lon1 = pts[-1]
    span = max(north - south, east - west, 1.0)
    dlat = lat1 - lat0
    dlon = lon1 - lon0
    length = (dlat**2 + dlon**2) ** 0.5 or 1.0
    scale = (span * 4) / length
    a = (lat0 - dlat * scale, lon0 - dlon * scale)
    b = (lat1 + dlat * scale, lon1 + dlon * scale)
    return _edge_label_sites([a, b], view) or sites


def _collect_edge_label(
    line: dict[str, Any],
    pts: Sequence[tuple[float, float]],
    view: tuple[float, float, float, float],
) -> list[tuple[str, float, str, str]]:
    """Return (edge, along_axis_value, text, color) for up to two ends."""
    sites = _line_edge_sites(pts, view)
    label = _angular_edge_label(line)
    color = _acg_color(line.get("body"))
    picked: list[tuple[float, float, str]] = []
    for prefer in (("n", "s"), ("e", "w")):
        pair = [s for s in sites if s[2] in prefer]
        if len(pair) >= 2:
            picked = pair[:2]
            break
    if not picked:
        picked = sites[:2]
    out: list[tuple[str, float, str, str]] = []
    for lat, lon, edge in picked:
        along = lon if edge in ("n", "s") else lat
        out.append((edge, along, label, color))
    return out


def _draw_collected_edge_labels(
    ax: Any,
    labels: Sequence[tuple[str, float, str, str]],
    view: tuple[float, float, float, float],
    *,
    max_per_edge: int = 6,
) -> None:
    """AstroClick-style margin tags: glyphs outside the frame with thin leaders."""
    south, west, north, east = view
    # Place labels *outside* the map spine (not inset into the basemap).
    outset_lat = (north - south) * 0.055
    outset_lon = (east - west) * 0.055
    by_edge: dict[str, list[tuple[float, str, str]]] = {"n": [], "s": [], "e": [], "w": []}
    for edge, along, text, color in labels:
        by_edge.setdefault(edge, []).append((along, text, color))

    for edge, items in by_edge.items():
        if not items:
            continue
        items = sorted(items, key=lambda t: t[0])
        if len(items) > max_per_edge:
            if max_per_edge == 1:
                items = [items[len(items) // 2]]
            else:
                step = (len(items) - 1) / (max_per_edge - 1)
                items = [items[int(round(i * step))] for i in range(max_per_edge)]

        if edge in ("n", "s"):
            min_gap = (east - west) * 0.09
        else:
            min_gap = (north - south) * 0.09

        placed_along: list[float] = []
        for along, text, color in items:
            pos = along
            for _ in range(8):
                if all(abs(pos - p) >= min_gap for p in placed_along):
                    break
                nearest = min(placed_along, key=lambda p: abs(p - pos))
                pos = nearest + (min_gap if pos >= nearest else -min_gap)
            if edge in ("n", "s"):
                pos = min(east - outset_lon * 0.4, max(west + outset_lon * 0.4, pos))
                edge_lon, edge_lat = pos, (north if edge == "n" else south)
                lab_lon, lab_lat = pos, (
                    north + outset_lat if edge == "n" else south - outset_lat
                )
            else:
                pos = min(north - outset_lat * 0.4, max(south + outset_lat * 0.4, pos))
                edge_lat, edge_lon = pos, (east if edge == "e" else west)
                lab_lat, lab_lon = pos, (
                    east + outset_lon if edge == "e" else west - outset_lon
                )
            if any(abs(pos - p) < min_gap * 0.55 for p in placed_along):
                continue
            placed_along.append(pos)
            # Thin leader from map edge to outside glyph (AstroClick gutter).
            ax.plot(
                [edge_lon, lab_lon],
                [edge_lat, lab_lat],
                color=color,
                linewidth=0.35,
                alpha=0.75,
                zorder=5.5,
                solid_capstyle="round",
                clip_on=False,
            )
            ax.text(
                lab_lon,
                lab_lat,
                text,
                color=color,
                fontsize=6.4,
                fontweight="normal",
                fontfamily="DejaVu Sans",
                ha="center",
                va="center",
                zorder=6,
                clip_on=False,
            )


def _spaced_markers(
    markers: Sequence[tuple[float, float, str]] | None,
    *,
    south: float,
    west: float,
    north: float,
    east: float,
    limit: int = 5,
) -> list[tuple[float, float, str]]:
    if not markers:
        return []
    span = max(north - south, east - west, 0.5)
    min_dist = span * 0.14
    chosen: list[tuple[float, float, str]] = []
    for lat, lon, label in markers:
        if not (south <= lat <= north and west <= lon <= east):
            continue
        short = label.strip()
        if any(short.casefold() == c[2].casefold() for c in chosen):
            continue
        if any(((lat - c[0]) ** 2 + (lon - c[1]) ** 2) ** 0.5 < min_dist for c in chosen):
            continue
        chosen.append((lat, lon, short))
        if len(chosen) >= limit:
            break
    return chosen


def render_acg_map_png(
    *,
    angular_lines: Sequence[dict[str, Any]] | None = None,
    aspect_lines: Sequence[dict[str, Any]] | None = None,
    bbox: tuple[float, float, float, float] = DEFAULT_WEST_EUROPE_BBOX,
    title: str = "",
    markers: Sequence[tuple[float, float, str]] | None = None,
    width_in: float = 5.4,
    height_in: float = 4.4,
    dpi: int = 140,
    use_osm_tiles: bool = True,
) -> bytes:
    """Render AstroClick-like ACG map: Carto tiles (or vector fallback), Su MC edge tags."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    south, west, north, east = bbox
    view = (south, west, north, east)
    fig, ax = plt.subplots(figsize=(width_in, height_in), dpi=dpi)
    fig.patch.set_facecolor("#ffffff")
    used_tiles = False
    if use_osm_tiles:
        used_tiles = _draw_tile_basemap(ax, south=south, west=west, north=north, east=east)
    if used_tiles:
        ax.set_facecolor("#d7e4f2")
    else:
        _draw_vector_basemap(ax, south=south, west=west, north=north, east=east)

    for line in aspect_lines or []:
        pts = _densify_polyline(_line_points(line), steps=56)
        if len(pts) < 2:
            continue
        color = _acg_color(line.get("body"))
        ax.plot(
            [p[1] for p in pts],
            [p[0] for p in pts],
            color=color,
            linewidth=0.40,
            alpha=0.55,
            zorder=2,
            solid_capstyle="round",
        )

    edge_labels: list[tuple[str, float, str, str]] = []
    for line in angular_lines or []:
        pts = _densify_polyline(_line_points(line), steps=56)
        if len(pts) < 2:
            continue
        color = _acg_color(line.get("body"))
        ax.plot(
            [p[1] for p in pts],
            [p[0] for p in pts],
            color=color,
            linewidth=1.05,
            alpha=0.92,
            zorder=3,
            solid_capstyle="round",
        )
        edge_labels.extend(_collect_edge_label(line, pts, view))
    _draw_collected_edge_labels(ax, edge_labels, view)

    for lat, lon, label in _spaced_markers(
        markers, south=south, west=west, north=north, east=east, limit=5
    ):
        ax.plot(lon, lat, "o", color="#111827", markersize=2.6, zorder=4)
        ax.annotate(
            label,
            (lon, lat),
            textcoords="offset points",
            xytext=(4, 3),
            fontsize=6.0,
            fontweight="normal",
            color="#334155",
            zorder=5,
        )

    ax.set_xlim(west, east)
    ax.set_ylim(south, north)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xticks([])
    ax.set_yticks([])
    ax.grid(False)
    for spine in ax.spines.values():
        spine.set_color("#94a3b8")
        spine.set_linewidth(0.55)
    if title:
        ax.set_title(title, fontsize=8.5, fontweight="normal", color="#0f172a", pad=10)

    # Leave gutter room for outside-edge glyphs + leader lines.
    fig.subplots_adjust(left=0.08, right=0.92, top=0.90, bottom=0.08)
    buf = io.BytesIO()
    fig.savefig(
        buf,
        format="png",
        dpi=dpi,
        facecolor=fig.get_facecolor(),
        bbox_inches="tight",
        pad_inches=0.22,
    )
    plt.close(fig)
    return buf.getvalue()


def png_to_data_uri(png_bytes: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")


def render_acg_data_uri(
    *,
    angular_lines: Sequence[dict[str, Any]] | None = None,
    aspect_lines: Sequence[dict[str, Any]] | None = None,
    bbox: tuple[float, float, float, float] = DEFAULT_WEST_EUROPE_BBOX,
    title: str = "",
    markers: Sequence[tuple[float, float, str]] | None = None,
    use_osm_tiles: bool = True,
) -> str:
    png = render_acg_map_png(
        angular_lines=angular_lines,
        aspect_lines=aspect_lines,
        bbox=bbox,
        title=title,
        markers=markers,
        use_osm_tiles=use_osm_tiles,
    )
    return png_to_data_uri(png)


def remote_image_to_data_uri(url: str, *, timeout: float = 20.0) -> str | None:
    if not url:
        return None
    if url.startswith("data:"):
        return url
    try:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "TravelAtlas/1.0 (personal)"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            ctype = (response.headers.get("Content-Type") or "image/jpeg").split(";")[0].strip()
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    if not raw:
        return None
    if "png" in ctype:
        mime = "image/png"
    elif "webp" in ctype:
        mime = "image/webp"
    else:
        mime = "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")
