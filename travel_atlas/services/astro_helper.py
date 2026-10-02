"""Helpers to load ACG + aspect lines for the primary traveler."""

from __future__ import annotations

from typing import Any

from travel_atlas.providers.astrology import HellenisticAstrologyProvider


def chart_layers_for_traveler(
    traveler: dict[str, Any] | None,
) -> tuple[list[dict], list[dict], str]:
    """Return (angular_lines, aspect_lines, status_message)."""
    if not traveler:
        return [], [], "No primary traveler profile."
    birth_date = (traveler.get("birth_date") or "").strip()
    birth_place = (traveler.get("birth_place") or "").strip()
    birth_time = (traveler.get("birth_time") or "12:00").strip() or "12:00"
    timezone = (
        traveler.get("birth_timezone")
        or traveler.get("timezone")
        or "America/Los_Angeles"
    ).strip()
    try:
        lat = float(traveler.get("birth_latitude") or traveler.get("birth_lat") or 0)
        lon = float(traveler.get("birth_longitude") or traveler.get("birth_lon") or 0)
    except (TypeError, ValueError):
        lat = lon = 0.0

    if not birth_date:
        birth_date = "2000-01-01"
        birth_place = birth_place or "Los Angeles, California"
        birth_time = birth_time if birth_time != "12:00" else "12:00"
        timezone = timezone or "America/Los_Angeles"

    if lat == 0 and lon == 0:
        lat, lon = 34.0522, -118.2437

    when = birth_date
    if "T" not in when:
        when = f"{birth_date}T{birth_time if len(birth_time) > 4 else birth_time + ':00'}"

    result = HellenisticAstrologyProvider().chart_lines_for_birth(
        when_iso=when,
        latitude=lat,
        longitude=lon,
        timezone=timezone,
    )
    if result.status != "ok":
        return [], [], str((result.payload or {}).get("message") or result.status)
    payload = result.payload or {}
    return (
        list(payload.get("lines") or []),
        list(payload.get("aspect_lines") or []),
        "ok",
    )


def acg_lines_for_traveler(traveler: dict[str, Any] | None) -> tuple[list[dict], str]:
    """Backward-compatible: angular lines only."""
    angular, _aspects, msg = chart_layers_for_traveler(traveler)
    return angular, msg


def _geocode_place(place: str) -> tuple[float, float]:
    import json
    import urllib.parse
    import urllib.request

    url = (
        "https://nominatim.openstreetmap.org/search?"
        + urllib.parse.urlencode({"q": place, "format": "json", "limit": "1"})
    )
    request = urllib.request.Request(
        url, headers={"User-Agent": "TravelAtlas/1.0 (personal)"}
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = json.loads(response.read().decode("utf-8"))
    except Exception:
        return 0.0, 0.0
    if not body:
        return 0.0, 0.0
    try:
        return float(body[0]["lat"]), float(body[0]["lon"])
    except (KeyError, TypeError, ValueError):
        return 0.0, 0.0


_SUPPORTIVE = frozenset({"sun", "moon", "venus", "jupiter"})
_CHALLENGING = frozenset({"mars", "saturn"})
_HARD_ASPECTS = ("square", "opposition")


def _line_body(line: dict[str, Any]) -> str:
    raw = str(line.get("body") or line.get("planet") or "")
    return raw.split()[0].casefold() if raw else ""


def _angular_delta_deg(a: float, b: float) -> float:
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def score_place_against_lines(
    latitude: float,
    longitude: float,
    angular: list[dict[str, Any]],
    aspects: list[dict[str, Any]] | None = None,
    *,
    orb: float = 8.0,
) -> dict[str, Any]:
    """Heuristic natal-line score for a city (higher is more supportive)."""
    score = 0.0
    hits: list[str] = []
    for line in angular:
        body = _line_body(line)
        lon = line.get("longitude")
        lat = line.get("latitude")
        if lon is None and line.get("lon") is not None:
            lon = line.get("lon")
        if lat is None and line.get("lat") is not None:
            lat = line.get("lat")
        dist = None
        if lon is not None:
            try:
                dist = _angular_delta_deg(longitude, float(lon))
            except (TypeError, ValueError):
                dist = None
        if dist is None and lat is not None:
            try:
                dist = abs(latitude - float(lat))
            except (TypeError, ValueError):
                dist = None
        if dist is None or dist > orb:
            continue
        closeness = max(0.0, (orb - dist) / orb)
        kind = str(line.get("kind") or line.get("line_kind") or "angular")
        if body in _SUPPORTIVE:
            score += 3.0 * closeness
            hits.append(f"{body.title()} {kind} (~{dist:.1f}°)")
        elif body in _CHALLENGING:
            score -= 2.0 * closeness
            hits.append(f"{body.title()} {kind} (~{dist:.1f}°)")
    for line in aspects or []:
        body = _line_body(line)
        aspect = str(line.get("aspect") or line.get("body") or "").casefold()
        lon = line.get("longitude") or line.get("lon")
        if lon is None:
            continue
        try:
            dist = _angular_delta_deg(longitude, float(lon))
        except (TypeError, ValueError):
            continue
        if dist > orb:
            continue
        closeness = max(0.0, (orb - dist) / orb)
        hard = any(h in aspect for h in _HARD_ASPECTS)
        if body in _SUPPORTIVE and not hard:
            score += 1.5 * closeness
            hits.append(f"{body.title()} {aspect.strip()} (~{dist:.1f}°)")
        elif body in _CHALLENGING or hard:
            score -= 1.5 * closeness
            hits.append(f"{body.title()} {aspect.strip()} (~{dist:.1f}°)")
    return {"score": round(score, 2), "hits": hits[:6]}


def rank_trip_route(
    traveler: dict[str, Any] | None,
    destinations: list[dict[str, Any]],
    *,
    angular: list[dict[str, Any]] | None = None,
    aspects: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Rank trip legs and seeded cities by natal ACG proximity."""
    from travel_atlas.services.traveler_docs import CITY_COORDS, MAJOR_CITIES

    if angular is None or aspects is None:
        angular, aspects, msg = chart_layers_for_traveler(traveler)
        if msg != "ok":
            return {"status": msg, "cities": [], "legs": []}
    else:
        msg = "ok"

    cities: list[dict[str, Any]] = []
    labels = []
    for dest in destinations:
        label = (dest.get("destination_label") or dest.get("label") or "").replace(
            " (UK)", ""
        ).strip()
        if label:
            labels.append(label)
        for city in MAJOR_CITIES.get(label, []):
            coords = CITY_COORDS.get(city)
            if not coords:
                continue
            rated = score_place_against_lines(coords[0], coords[1], angular, aspects)
            cities.append(
                {
                    "city": city,
                    "leg": label,
                    "score": rated["score"],
                    "hits": rated["hits"],
                }
            )
    cities.sort(key=lambda row: (-row["score"], row["city"]))
    by_leg: dict[str, float] = {}
    for row in cities:
        by_leg[row["leg"]] = by_leg.get(row["leg"], 0.0) + row["score"]
    # Include legs with no seeded city scores at 0.
    for label in labels:
        by_leg.setdefault(label, 0.0)
    legs = [
        {"label": label, "score": round(score, 2)}
        for label, score in sorted(by_leg.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    return {"status": msg, "cities": cities[:12], "legs": legs}
