"""Astrocartography via hellenistic_astrology (same code as EOS MCP)."""

from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .base import StubResult

# travel/.../providers → parents[5] == My_folder (mcp_server sibling of hobbies/)
_CANDIDATES = (
    Path(__file__).resolve().parents[5] / "mcp_server",
    Path(__file__).resolve().parents[4] / "mcp_server",
)
_MCP_ROOT = next((p for p in _CANDIDATES if p.is_dir()), _CANDIDATES[0])


def _ensure_mcp_path() -> bool:
    root = str(_MCP_ROOT)
    if _MCP_ROOT.is_dir() and root not in sys.path:
        sys.path.insert(0, root)
    return _MCP_ROOT.is_dir()


def _serialize_line(line: Any) -> dict[str, Any]:
    if hasattr(line, "points"):
        return {
            "body": getattr(line, "body", "") or "",
            "angle": getattr(line, "angle", "") or "",
            "kind": getattr(line, "kind", "") or "",
            "points": [list(p) for p in (getattr(line, "points", None) or ())],
            "note": getattr(line, "note", "") or "",
        }
    if hasattr(line, "__dataclass_fields__"):
        payload = asdict(line)
        points = payload.get("points") or []
        payload["points"] = [list(p) for p in points]
        return payload
    return dict(line)


_DEFAULT_ACG_BODIES = (
    "Sun",
    "Moon",
    "Mercury",
    "Venus",
    "Mars",
    "Jupiter",
    "Saturn",
    "Chiron",
)


def _configure_swisseph_path() -> str:
    """Prefer the same asteroid ephemeris folder Astrology_project uses."""
    import swisseph as swe

    candidates = [
        Path(__file__).resolve().parents[5] / "Astrology_project" / "ephemeris",
        Path(__file__).resolve().parents[4] / "Astrology_project" / "ephemeris",
    ]
    for candidate in candidates:
        if not candidate.is_dir():
            continue
        if any(candidate.glob("seas*.se1")) or any(candidate.glob("sepl*.se1")):
            swe.set_ephe_path(str(candidate))
            return str(candidate)
    return ""


def _chiron_longitude(jd: float) -> float | None:
    """Ecliptic longitude of Chiron at Julian day, or None if asteroid ephemeris missing."""
    try:
        import swisseph as swe
    except ImportError:
        return None
    _configure_swisseph_path()
    try:
        pos, _ret = swe.calc_ut(jd, swe.CHIRON)
        return float(pos[0]) % 360.0
    except Exception:
        return None


class HellenisticAstrologyProvider:
    """Real ACG lines when Astrology_project / swisseph path works; else graceful fail."""

    key = "hellenistic-astrocartography-v1"

    def chart_lines_for_birth(
        self,
        *,
        when_iso: str,
        latitude: float,
        longitude: float,
        timezone: str,
        bodies: tuple[str, ...] = _DEFAULT_ACG_BODIES,
        aspects: tuple[str, ...] = ("sextile", "square", "trine", "opposition"),
    ) -> StubResult:
        """Return both angular ACG lines and major aspect lines (incl. Chiron when available)."""
        if not _ensure_mcp_path():
            return StubResult(
                provider=self.key,
                status="unavailable",
                payload={"message": f"mcp_server not found at {_MCP_ROOT}"},
                links={},
            )
        try:
            from datetime import datetime

            from domains.hellenistic_astrology import astrolocality
            from domains.hellenistic_astrology.chart import build_chart
            from domains.hellenistic_astrology.models import PLANETS
            from domains.picatrix import bridge as picatrix_bridge
        except Exception as exc:  # noqa: BLE001
            return StubResult(
                provider=self.key,
                status="unavailable",
                payload={"message": f"Hellenistic astrology import failed: {exc}"},
                links={},
            )
        try:
            context = picatrix_bridge.build_chart_context(
                datetime.fromisoformat(when_iso), latitude, longitude, timezone
            )
            raw = dict(context.positions)
            raw.pop("ASC", None)
            positions = {name: float(raw[name]) for name in PLANETS if name in raw}
            chiron_lon = _chiron_longitude(float(context.jd))
            chiron_note = ""
            if chiron_lon is not None:
                positions["Chiron"] = chiron_lon
            else:
                chiron_note = (
                    "Chiron omitted — asteroid ephemeris (seas_*.se1) not found. "
                    "Place seas_18.se1 next to sepl_18.se1 (usually Downloads)."
                )
            # Midheaven via same helper path as build_chart_from_moment.
            from domains.hellenistic_astrology.chart import _midheaven_from_context

            chart = build_chart(
                positions,
                float(context.ascendant),
                midheaven=_midheaven_from_context(context),
                retrograde=getattr(context, "retrograde", None),
                sect="diurnal" if context.is_day_chart else "nocturnal",
                note=f"Built from {when_iso} at {latitude},{longitude} ({timezone}).",
            )
            present = {p.name.casefold() for p in chart.positions}
            line_bodies = tuple(b for b in bodies if b.casefold() in present)
            angular = astrolocality.angular_lines(
                chart, longitude, bodies=line_bodies
            )
            aspect = astrolocality.aspect_lines(
                chart, longitude, aspects=aspects, bodies=line_bodies
            )
        except Exception as exc:  # noqa: BLE001
            return StubResult(
                provider=self.key,
                status="unavailable",
                payload={
                    "message": (
                        "Could not build chart (need Astrology_project + swisseph). "
                        f"{exc}"
                    )
                },
                links={},
            )

        wanted = {b.casefold() for b in bodies}
        angular_out = []
        for line in angular:
            body = getattr(line, "body", "") or ""
            if wanted and body.casefold() not in wanted:
                continue
            angular_out.append(_serialize_line(line))

        aspect_out = []
        for line in aspect:
            body = getattr(line, "body", "") or ""
            # aspect_lines labels bodies as "Sun square", "Venus trine (left)", etc.
            planet = body.split()[0] if body else ""
            if wanted and planet.casefold() not in wanted:
                continue
            row = _serialize_line(line)
            row["line_kind"] = "aspect"
            row["aspect"] = " ".join(body.split()[1:]) if body else ""
            aspect_out.append(row)

        message = "Astrocartography angular + aspect lines (incl. Chiron when available)."
        if chiron_note:
            message = f"{message} {chiron_note}"

        return StubResult(
            provider=self.key,
            status="ok",
            payload={
                "message": message,
                "count": len(angular_out),
                "lines": angular_out,
                "aspect_lines": aspect_out,
                "chiron_included": chiron_lon is not None,
                "birth": {
                    "when": when_iso,
                    "latitude": latitude,
                    "longitude": longitude,
                    "timezone": timezone,
                },
            },
            links={},
        )

    def lines_for_birth(
        self,
        *,
        when_iso: str,
        latitude: float,
        longitude: float,
        timezone: str,
        bodies: tuple[str, ...] = _DEFAULT_ACG_BODIES,
    ) -> StubResult:
        return self.chart_lines_for_birth(
            when_iso=when_iso,
            latitude=latitude,
            longitude=longitude,
            timezone=timezone,
            bodies=bodies,
        )

    def near(
        self,
        *,
        when_iso: str,
        birth_lat: float,
        birth_lon: float,
        timezone: str,
        place_lat: float,
        place_lon: float,
        orb: float = 5.0,
    ) -> StubResult:
        base = self.lines_for_birth(
            when_iso=when_iso,
            latitude=birth_lat,
            longitude=birth_lon,
            timezone=timezone,
        )
        if base.status != "ok":
            return base
        if not _ensure_mcp_path():
            return base
        try:
            from domains.hellenistic_astrology.chart import build_chart_from_moment
            from domains.hellenistic_astrology import astrolocality

            chart = build_chart_from_moment(
                when_iso, birth_lat, birth_lon, timezone
            )
            near = astrolocality.lines_near(
                chart, birth_lon, place_lat, place_lon, orb=orb
            )
        except Exception as exc:  # noqa: BLE001
            return StubResult(
                provider=self.key,
                status="degraded",
                payload={**base.payload, "near_error": str(exc)},
                links={},
            )
        payload = dict(base.payload)
        payload["near"] = near
        return StubResult(
            provider=self.key, status="ok", payload=payload, links={}
        )


class StubAstrologyProvider(HellenisticAstrologyProvider):
    """Alias — real provider when deps exist; StubResult unavailable otherwise."""

    def signals(self, *, destination: str, on_date: str | None = None) -> StubResult:
        return StubResult(
            provider=self.key,
            status="unavailable",
            payload={
                "message": "Use lines_for_birth() with traveler birth data.",
                "destination": destination,
                "on_date": on_date,
            },
            links={},
        )
