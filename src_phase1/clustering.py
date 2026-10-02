"""
Phase 1 — Geographic pin clustering.

Uses a simple greedy distance-based algorithm rather than full DBSCAN so
there are zero external dependencies beyond the standard library.

The distance threshold is fully configurable (no hardcoded 15 km).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .models import Cluster, SavedLocation
from .pin_repository import haversine_km

logger = logging.getLogger(__name__)


@dataclass
class ClusterConfig:
    """Parameters that control how pins are grouped."""

    distance_threshold_km: float = 15.0
    """Pins within this distance of a cluster's centroid are added to it."""

    min_pins_per_cluster: int = 1
    """Clusters smaller than this are discarded."""

    def __post_init__(self) -> None:
        if self.distance_threshold_km <= 0:
            raise ValueError("distance_threshold_km must be > 0")
        if self.min_pins_per_cluster < 1:
            raise ValueError("min_pins_per_cluster must be >= 1")


class PinClusterer:
    """Group SavedLocation objects into geographic Cluster objects.

    Algorithm (single-pass greedy):
    1. Iterate over all pins.
    2. For each pin find the existing cluster whose centroid is within
       ``threshold_km``.  If several qualify, pick the nearest one.
    3. If no cluster is close enough, create a new cluster.
    4. After all pins are assigned, recompute every centroid as the
       arithmetic mean of its members and discard under-sized clusters.

    This runs in O(N·C) where C is the number of clusters — fast enough
    for up to ~50,000 pins on a laptop.
    """

    def __init__(self, config: Optional[ClusterConfig] = None) -> None:
        self.config = config or ClusterConfig()

    def cluster_pins(self, pins: List[SavedLocation]) -> List[Cluster]:
        """Return a list of Cluster objects from the given pins."""
        valid = [p for p in pins if p.latitude != 0 or p.longitude != 0]
        if not valid:
            logger.warning("No valid (non-zero) pins to cluster.")
            return []

        # {cluster_id: [pin, ...]}
        raw: Dict[str, List[SavedLocation]] = {}
        centroids: Dict[str, Tuple[float, float]] = {}  # cluster_id -> (lat, lng)

        for pin in valid:
            best_id, best_dist = self._nearest_cluster(
                pin.latitude, pin.longitude, centroids
            )
            if best_id and best_dist <= self.config.distance_threshold_km:
                raw[best_id].append(pin)
                # Incrementally update centroid
                members = raw[best_id]
                centroids[best_id] = (
                    sum(p.latitude for p in members) / len(members),
                    sum(p.longitude for p in members) / len(members),
                )
            else:
                cid = str(uuid.uuid4())
                raw[cid] = [pin]
                centroids[cid] = (pin.latitude, pin.longitude)

        clusters: List[Cluster] = []
        for cid, members in raw.items():
            if len(members) < self.config.min_pins_per_cluster:
                continue

            c_lat, c_lng = centroids[cid]
            city = _majority_value([p.city for p in members])
            region = _majority_value([p.region for p in members])
            country = _majority_value([p.country for p in members])
            primary_cat = _majority_value([p.category for p in members])
            name = city or _cluster_label(members, country=country, region=region)

            clusters.append(
                Cluster(
                    id=cid,
                    name=name,
                    centroid_lat=c_lat,
                    centroid_lng=c_lng,
                    pin_ids=[p.id for p in members],
                    threshold_km=self.config.distance_threshold_km,
                    city=city,
                    country=country,
                    primary_category=primary_cat,
                )
            )

        clusters.sort(key=lambda c: c.pin_count, reverse=True)
        logger.info(
            "Clustered %d pins into %d clusters (threshold=%.1f km)",
            len(valid),
            len(clusters),
            self.config.distance_threshold_km,
        )
        return clusters

    # ---------------------------------------------------------------- #
    # Internal helpers                                                   #
    # ---------------------------------------------------------------- #

    @staticmethod
    def _nearest_cluster(
        lat: float,
        lng: float,
        centroids: Dict[str, Tuple[float, float]],
    ) -> Tuple[Optional[str], float]:
        """Return (cluster_id, distance_km) for the nearest centroid."""
        best_id: Optional[str] = None
        best_dist = float("inf")
        for cid, (c_lat, c_lng) in centroids.items():
            d = haversine_km(lat, lng, c_lat, c_lng)
            if d < best_dist:
                best_dist = d
                best_id = cid
        return best_id, best_dist


# ------------------------------------------------------------------ #
# Module-level helpers                                                 #
# ------------------------------------------------------------------ #

def _majority_value(values: List[Optional[str]]) -> Optional[str]:
    """Return the most-common non-None value, or None if all are None."""
    counts: Dict[str, int] = {}
    for v in values:
        if v:
            counts[v] = counts.get(v, 0) + 1
    return max(counts, key=counts.__getitem__) if counts else None


def _cluster_label(
    members: List[SavedLocation],
    *,
    country: Optional[str] = None,
    region: Optional[str] = None,
) -> str:
    """Derive a human-readable label from cluster members."""
    if region and country:
        return f"{region} area"
    if country:
        return f"{country} area"
    best = max(members, key=lambda p: len(p.notes or "") + len(p.name))
    label = best.name if len(best.name) <= 40 else best.name[:37] + "…"
    return label
