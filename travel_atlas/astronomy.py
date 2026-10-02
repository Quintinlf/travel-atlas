"""Local, offline computation of sky events.

Sun/moon position comes from the `astral` library. Solstices/equinoxes are
NOT provided by `astral`, so they are computed here with a small, well-known
dependency-free approximation (Meeus, "Astronomical Algorithms" 2nd ed.,
ch. 27, mean equinoxes/solstices, valid 1000-3000 CE) accurate to roughly
+/-1 day -- adequate for seasonal narrative purposes, not ephemeris-grade
precision. True heliacal-rising-of-a-star calculations (e.g. the Pleiades)
are out of scope for this adapter; see seasonal knowledge claims for
documented historical/cultural traditions tied to such events instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from astral import Observer
from astral.moon import phase as moon_phase_value
from astral.sun import sun

from .adapters import SkyEvent, SkySnapshot
from .seasonal_matching import month_day


@dataclass(frozen=True)
class MeteorShower:
    key: str
    name: str
    peak_month_day: str  # "MM-DD"
    active_window_label: str  # descriptive only, e.g. "mid-July to late August"
    typical_zhr: int  # zenithal hourly rate, descriptive only
    parent_body: str


METEOR_SHOWERS: tuple[MeteorShower, ...] = (
    MeteorShower("quadrantids", "Quadrantids", "01-03", "late December to mid-January", 110, "2003 EH1"),
    MeteorShower("lyrids", "Lyrids", "04-22", "mid to late April", 18, "Comet Thatcher"),
    MeteorShower("eta_aquariids", "Eta Aquariids", "05-05", "mid-April to late May", 50, "Comet 1P/Halley"),
    MeteorShower("perseids", "Perseids", "08-12", "mid-July to late August", 100, "Comet 109P/Swift-Tuttle"),
    MeteorShower("orionids", "Orionids", "10-21", "late September to late November", 20, "Comet 1P/Halley"),
    MeteorShower("leonids", "Leonids", "11-17", "early November to early December", 15, "Comet 55P/Tempel-Tuttle"),
    MeteorShower("geminids", "Geminids", "12-14", "mid-November to late December", 120, "3200 Phaethon"),
    MeteorShower("ursids", "Ursids", "12-22", "mid to late December", 10, "Comet 8P/Tuttle"),
)

_MOON_PHASE_NAMES = (
    (1.0, "new moon"),
    (6.5, "waxing crescent"),
    (8.0, "first quarter"),
    (13.5, "waxing gibbous"),
    (15.5, "full moon"),
    (21.0, "waning gibbous"),
    (23.0, "last quarter"),
    (28.0, "waning crescent"),
)

_MARCH_EQUINOX = (2451623.80984, 365242.37404, 0.05169, -0.00411, -0.00057)
_JUNE_SOLSTICE = (2451716.56767, 365241.62603, 0.00325, 0.00888, -0.00030)
_SEPTEMBER_EQUINOX = (2451810.21715, 365242.01767, -0.11575, 0.00337, 0.00078)
_DECEMBER_SOLSTICE = (2451900.05952, 365242.74049, -0.06223, -0.00823, 0.00032)


def _julian_day_to_date(jd: float) -> date:
    """Standard JD -> proleptic Gregorian calendar date (Meeus, ch. 7)."""
    jd += 0.5
    z = int(jd)
    if z < 2299161:
        a = z
    else:
        alpha = int((z - 1867216.25) / 36524.25)
        a = z + 1 + alpha - alpha // 4
    b = a + 1524
    c = int((b - 122.1) / 365.25)
    d = int(365.25 * c)
    e = int((b - d) / 30.6001)
    day = b - d - int(30.6001 * e)
    month = e - 1 if e < 14 else e - 13
    year = c - 4716 if month > 2 else c - 4715
    return date(year, month, day)


def _mean_equinox_or_solstice(year: int, coeffs: tuple[float, float, float, float, float]) -> date:
    y = (year - 2000) / 1000
    jde = coeffs[0] + coeffs[1] * y + coeffs[2] * y**2 + coeffs[3] * y**3 + coeffs[4] * y**4
    return _julian_day_to_date(jde)


def _solar_year_markers(year: int) -> dict[str, date]:
    return {
        "march_equinox": _mean_equinox_or_solstice(year, _MARCH_EQUINOX),
        "june_solstice": _mean_equinox_or_solstice(year, _JUNE_SOLSTICE),
        "september_equinox": _mean_equinox_or_solstice(year, _SEPTEMBER_EQUINOX),
        "december_solstice": _mean_equinox_or_solstice(year, _DECEMBER_SOLSTICE),
    }


_MARKER_KIND = {
    "march_equinox": "equinox",
    "june_solstice": "solstice",
    "september_equinox": "equinox",
    "december_solstice": "solstice",
}


def _moon_phase_name(value: float) -> str:
    for threshold, name in _MOON_PHASE_NAMES:
        if value < threshold:
            return name
    return "waning crescent"


def _approximate_local_timezone(longitude: float) -> timezone:
    """A coarse longitude/15 timezone estimate, only used to keep a single
    calendar date's sunrise/sunset in the correct order; not a real
    timezone-database lookup.
    """
    offset_hours = round(longitude / 15)
    return timezone(timedelta(hours=offset_hours))


class AstralAstronomyAdapter:
    """Local computation. See AstronomyAdapter contract in adapters.py."""

    key = "astral-local-v1"

    def fetch(self, *, latitude: float, longitude: float, on_date: date) -> SkySnapshot:
        events: list[SkyEvent] = []
        day_length_event = self._day_length_event(latitude, longitude, on_date)
        if day_length_event:
            events.append(day_length_event)
        events.append(self._moon_phase_event(on_date))
        events.append(self._solar_year_position_event(on_date))
        landmark = self._solstice_or_equinox_landmark_event(on_date)
        if landmark:
            events.append(landmark)
        events.extend(self._meteor_shower_events(on_date))
        return SkySnapshot(
            adapter_key=self.key,
            latitude=latitude,
            longitude=longitude,
            date=on_date,
            events=tuple(events),
            generated_at=datetime.now(timezone.utc),
        )

    def _day_length_event(self, latitude: float, longitude: float, on_date: date) -> SkyEvent | None:
        try:
            times = sun(
                Observer(latitude=latitude, longitude=longitude),
                date=on_date,
                tzinfo=_approximate_local_timezone(longitude),
            )
        except ValueError:
            return None  # polar day/night: sunrise/sunset undefined
        length_hours = round((times["sunset"] - times["sunrise"]).total_seconds() / 3600, 2)
        return SkyEvent(
            key="day_length",
            kind="day_length",
            title="Day length",
            description=f"About {length_hours} hours of daylight.",
            occurs_on=on_date,
            detail={
                "sunrise_local": times["sunrise"].isoformat(),
                "sunset_local": times["sunset"].isoformat(),
                "day_length_hours": length_hours,
            },
        )

    def _moon_phase_event(self, on_date: date) -> SkyEvent:
        value = moon_phase_value(on_date)
        name = _moon_phase_name(value)
        return SkyEvent(
            key="moon_phase",
            kind="moon_phase",
            title="Moon phase",
            description=f"The moon is in its {name} phase.",
            occurs_on=on_date,
            detail={"phase_value": value, "phase_name": name},
        )

    def _solar_year_position_event(self, on_date: date) -> SkyEvent:
        markers = _solar_year_markers(on_date.year)
        nearest_key, nearest_date = min(markers.items(), key=lambda kv: abs((kv[1] - on_date).days))
        offset = (on_date - nearest_date).days
        return SkyEvent(
            key="solar_year_position",
            kind="solar_year_position",
            title="Position in the solar year",
            description=(
                f"{abs(offset)} day(s) {'after' if offset >= 0 else 'before'} the "
                f"{nearest_key.replace('_', ' ')}."
            ),
            occurs_on=on_date,
            detail={
                "nearest_marker": nearest_key,
                "marker_date": nearest_date.isoformat(),
                "days_offset": offset,
            },
        )

    def _solstice_or_equinox_landmark_event(self, on_date: date) -> SkyEvent | None:
        markers = _solar_year_markers(on_date.year)
        for name, marker_date in markers.items():
            if marker_date == on_date:
                kind = _MARKER_KIND[name]
                return SkyEvent(
                    key=name,
                    kind=kind,
                    title=name.replace("_", " ").title(),
                    description=f"Today is the (approximate) {name.replace('_', ' ')}.",
                    occurs_on=on_date,
                    detail={"marker": name},
                )
        return None

    def _meteor_shower_events(self, on_date: date) -> list[SkyEvent]:
        today = month_day(on_date)
        return [
            SkyEvent(
                key=f"meteor_shower_{shower.key}",
                kind="meteor_shower",
                title=f"{shower.name} peak",
                description=(
                    f"The {shower.name} meteor shower (from {shower.parent_body}) peaks around "
                    f"today, active {shower.active_window_label}."
                ),
                occurs_on=on_date,
                detail={"typical_zhr": shower.typical_zhr, "parent_body": shower.parent_body},
            )
            for shower in METEOR_SHOWERS
            if shower.peak_month_day == today
        ]
