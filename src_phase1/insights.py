"""
Phase 1 — Destination scoring and statistics.

``DestinationInsights`` answers questions like:
  - Which cities do I care about most?
  - Which countries appear most often?
  - What is my breakdown by list?

Scoring formula
---------------
destination_score =
    0.45 * normalised_note_volume    (log1p of non-blank lines across real notes)
  + 0.35 * normalised_note_depth     (characters per annotated pin)
  + 0.20 * normalised_breadth        (log1p of distinct cities)

Each component is first scaled by an optional per-destination ``boost`` (default 1.0),
a manual override for when the computed signal disagrees with the traveller.

Raw pin count is deliberately *not* a term. It measures how finely a place was broken
into individual saves rather than how much it is wanted — a country saved as 40
individual restaurants would otherwise bury one saved as three pins carrying long notes.
What the user actually wrote is the interest signal, so the score is built from notes,
with distinct cities as a log-damped breadth term.

Notes matching ``GEOCODE_PENDING_NOTE`` are system placeholders and are filtered out at
read time; see :func:`real_note`.

Each component is min-max normalised to [0, 1] before weighting. A component whose
values are identical across every destination carries no ranking information, so it is
dropped and its weight redistributed across the survivors — never folded in as a
constant offset.

The composite is multiplied by 100 and rounded to one decimal place so the output reads
as "Vietnam: 79.5" rather than "Vietnam: 0.795".
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .models import SavedLocation
from .takeout_parser import GEOCODE_PENDING_NOTE

#: Weights for the three scoring components, keyed as returned by ``_components``.
_WEIGHTS: Dict[str, float] = {
    "note_volume": 0.45,
    "note_depth": 0.35,
    "breadth": 0.20,
}

#: Bounds for the manual per-destination multiplier.
BOOST_MIN = 0.25
BOOST_MAX = 3.0
BOOST_DEFAULT = 1.0

#: Score given to every destination when no component varies (no signal to rank on).
_NEUTRAL_SCORE = 50.0

_PLACEHOLDER_NOTES = frozenset({GEOCODE_PENDING_NOTE.strip().casefold()})


def real_note(pin: SavedLocation) -> Optional[str]:
    """Return *pin*'s user-authored note, or ``None`` if there isn't one.

    Empty notes and the ``GEOCODE_PENDING_NOTE`` placeholder both count as "no note".
    The comparison is against the whole normalised string rather than a substring scan,
    so a genuine note that happens to quote the placeholder survives.
    """
    text = (pin.notes or "").strip()
    if not text or text.casefold() in _PLACEHOLDER_NOTES:
        return None
    return text


class DestinationInsights:
    """Compute destination scores and aggregate statistics from a list of pins.

    Parameters
    ----------
    pins:
        All loaded SavedLocation objects.
    boosts:
        Optional ``{destination_label: multiplier}`` overrides applied to the composite
        score. Missing entries default to ``BOOST_DEFAULT`` (1.0), so an empty mapping
        is an exact no-op.
    """

    def __init__(
        self,
        pins: List[SavedLocation],
        boosts: Optional[Dict[str, float]] = None,
        country_ratings: Optional[Dict[str, int]] = None,
    ) -> None:
        self._pins = pins
        self._boosts = boosts or {}
        self._country_ratings = country_ratings or {}

    # ---------------------------------------------------------------- #
    # Public API                                                         #
    # ---------------------------------------------------------------- #

    def get_destination_scores(self) -> List[Tuple[str, float, int]]:
        """Return ``(city_name, score, pin_count)`` sorted by score desc.

        Only cities that appear in at least one pin are included.
        Pins without a city are grouped under ``"(unknown)"``.
        """
        by_city: Dict[str, List[SavedLocation]] = defaultdict(list)
        for pin in self._pins:
            key = (pin.city or "(unknown)").strip()
            by_city[key].append(pin)

        signals = self._score_groups(by_city)
        return [(s["destination"], s["score"], s["pin_count"]) for s in signals]

    def get_top_destinations(self, n: int = 10) -> List[Tuple[str, float, int]]:
        """Top *n* destinations by score (country or US state)."""
        signals = self.get_destination_signals(n=n)
        return [(s["destination"], s["score"], s["pin_count"]) for s in signals]

    def get_destination_signals(self, n: Optional[int] = None) -> List[Dict]:
        """Scored destinations with the underlying signals exposed.

        Each entry carries ``destination``, ``score``, ``pin_count``, ``note_lines``,
        ``note_chars``, ``annotated_pins``, ``cities`` and the applied ``boost`` — the
        chart needs these to show *why* a destination ranks where it does.
        """
        from .geo_grouping import destination_label, top_level_destination

        grouped: Dict[str, List[SavedLocation]] = defaultdict(list)
        for pin in self._pins:
            kind, label = top_level_destination(pin)
            grouped[destination_label(kind, label)].append(pin)

        signals = self._score_groups(grouped)
        return signals[:n] if n is not None else signals

    # ---------------------------------------------------------------- #
    # Scoring core                                                       #
    # ---------------------------------------------------------------- #

    def _score_groups(
        self, grouped: Dict[str, List[SavedLocation]]
    ) -> List[Dict]:
        """Score pre-grouped pins, sorted by score descending."""
        if not grouped:
            return []

        stats = {name: _group_stats(members) for name, members in grouped.items()}
        boosts = {
            name: clamp_boost(self._boosts.get(name, BOOST_DEFAULT)) for name in stats
        }

        # The boost scales the raw signals, not the finished score. Scaling afterwards
        # looks equivalent but isn't: min-max normalisation pins the weakest
        # destination at exactly 0.0, and 0.0 * boost is still 0.0 — the one place most
        # in need of a manual override would be the one place unable to receive one.
        # Scaling beforehand also makes a uniform boost exactly invariant, since
        # min-max normalisation is unchanged by scaling every value by the same factor.
        boosted = {
            name: {
                component: stat[component] * boosts[name]
                if component in _WEIGHTS
                else stat[component]
                for component in stat
            }
            for name, stat in stats.items()
        }
        weights = _effective_weights(boosted.values())

        results: List[Dict] = []
        for name, stat in stats.items():
            if weights is None:
                composite = _NEUTRAL_SCORE / 100.0
            else:
                composite = sum(
                    weight
                    * _minmax_norm(
                        boosted[name][component],
                        [s[component] for s in boosted.values()],
                    )
                    for component, weight in weights.items()
                )

            score = min(1.0, max(0.0, composite)) * 100
            boost = boosts[name]

            results.append(
                {
                    "destination": name,
                    "score": round(score, 1),
                    "pin_count": stat["pin_count"],
                    "note_lines": stat["note_lines"],
                    "note_chars": stat["note_chars"],
                    "annotated_pins": stat["annotated_pins"],
                    "cities": stat["city_count"],
                    "boost": boost,
                }
            )

        results.sort(key=lambda item: (-item["score"], item["destination"]))
        return results

    def get_top_countries(self, n: int = 10) -> List[Tuple[str, int]]:
        """Top *n* destinations by personal rating, then pin count.

        Uses ``uk_nation`` / country buckets so England/Scotland split out and
        Ireland stays separate. Ratings (1–5) outrank raw pin volume.
        """
        from .geo_grouping import destination_label, top_level_destination

        counter: Counter = Counter()
        for pin in self._pins:
            kind, label = top_level_destination(pin)
            counter[destination_label(kind, label)] += 1

        ratings = self._country_ratings

        def sort_key(item: Tuple[str, int]) -> Tuple[int, int, str]:
            name, count = item
            rating = int(ratings.get(name) or ratings.get(name.split(" (")[0]) or 0)
            return (-rating, -count, name)

        ranked = sorted(counter.items(), key=sort_key)
        return ranked[:n]

    def get_list_breakdown(self) -> Dict[str, int]:
        """Pin count per list name, sorted descending."""
        counter: Counter = Counter(p.list_name for p in self._pins)
        return dict(sorted(counter.items(), key=lambda kv: kv[1], reverse=True))

    def get_statistics(self) -> Dict:
        """Overall statistics for the dashboard header."""
        cities = {p.city for p in self._pins if p.city}
        countries = {p.country for p in self._pins if p.country}
        lists = {p.list_name for p in self._pins}

        by_city_count = Counter(p.city for p in self._pins if p.city)
        avg_per_city = (
            sum(by_city_count.values()) / len(by_city_count)
            if by_city_count
            else 0.0
        )

        return {
            "total_pins": len(self._pins),
            "unique_cities": len(cities),
            "unique_countries": len(countries),
            "unique_lists": len(lists),
            "avg_pins_per_city": round(avg_per_city, 1),
            "pins_with_notes": sum(1 for p in self._pins if p.notes),
            "pins_with_coords": sum(
                1 for p in self._pins
                if p.latitude != 0 or p.longitude != 0
            ),
        }

    def get_cities_by_count(self) -> List[Tuple[str, int]]:
        """All cities sorted by pin count descending."""
        counter: Counter = Counter(
            p.city.strip() for p in self._pins if p.city
        )
        return counter.most_common()

    def generate_top_destinations(self, n: int = 10) -> List[Tuple[str, float, int]]:
        """Alias for ``get_top_destinations``.

        Named explicitly per the Phase 1 spec:
        *generate_top_destinations()* returns ranked cities based on saved pins.
        """
        return self.get_top_destinations(n=n)


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

def clamp_boost(boost: float) -> float:
    """Clamp a manual multiplier into ``[BOOST_MIN, BOOST_MAX]``."""
    try:
        value = float(boost)
    except (TypeError, ValueError):
        return BOOST_DEFAULT
    if math.isnan(value):
        return BOOST_DEFAULT
    return min(BOOST_MAX, max(BOOST_MIN, value))


def _group_stats(members: List[SavedLocation]) -> Dict[str, float]:
    """Aggregate the scoring signals for one destination's pins."""
    notes = [note for note in (real_note(pin) for pin in members) if note]
    note_lines = sum(
        len([line for line in note.splitlines() if line.strip()]) for note in notes
    )
    note_chars = sum(len(note) for note in notes)
    city_count = len({(pin.city or "").strip() for pin in members if pin.city})

    return {
        "pin_count": len(members),
        "annotated_pins": len(notes),
        "note_lines": note_lines,
        "note_chars": note_chars,
        "city_count": city_count,
        # Scoring components. log1p damps both counts so one sprawling destination
        # cannot saturate the scale; depth is per-annotated-pin so a single long,
        # thoughtful note counts as strongly as several short ones.
        "note_volume": math.log1p(note_lines),
        "note_depth": (note_chars / len(notes)) if notes else 0.0,
        "breadth": math.log1p(city_count),
    }


def _effective_weights(
    all_stats: Iterable[Dict[str, float]]
) -> Optional[Dict[str, float]]:
    """Drop components that carry no ranking information and renormalise the rest.

    A component whose value is identical across every destination cannot separate them.
    Min-max normalising it would yield the same number for all — folding in a constant
    offset that inflates every score while explaining nothing. Such components are
    removed and their weight is redistributed proportionally across the survivors.

    Returns ``None`` when *every* component is degenerate, meaning there is no signal to
    rank on at all.
    """
    stats = list(all_stats)
    varying = {
        component: weight
        for component, weight in _WEIGHTS.items()
        if not _is_constant([s[component] for s in stats])
    }
    if not varying:
        return None

    total = sum(varying.values())
    return {component: weight / total for component, weight in varying.items()}


def _is_constant(values: Sequence[float]) -> bool:
    return math.isclose(min(values), max(values))


def _minmax_norm(value: float, all_values: Sequence[float]) -> float:
    """Min-max normalise *value* to [0, 1].

    Returns 0.0 when every value is equal. Returning 1.0 here — as this function used to
    — is what silently turned the constant ``user_priority`` and ``list_name`` columns
    into a flat score offset for every destination.
    """
    mn = min(all_values)
    mx = max(all_values)
    if math.isclose(mn, mx):
        return 0.0
    return (value - mn) / (mx - mn)
