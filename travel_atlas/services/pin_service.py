"""Read-only adapter over Phase 1 imported Google Maps pins."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from src_phase1.clustering import ClusterConfig, PinClusterer
from src_phase1.geocoding import GeocodeCache, GeocodeResult, reverse_geocode_pin
from src_phase1.geo_grouping import is_wishlist_country_name, normalize_country
from src_phase1.google_place_identity import (
    MEDIA_STRATEGY_VERSION,
    coords_conflict,
    resolve_place_identity,
    url_from_raw_json,
)
from src_phase1.models import SavedLocation
from src_phase1.pin_repository import PinRepository, haversine_km
from src_phase1.places_api import PlaceMediaCache
from src_phase1.takeout_parser import TakeoutParser


class PinDataUnavailableError(RuntimeError):
    """Raised when the Phase 1 pin database cannot safely be read."""


class PinService:
    """Expose Phase 1 pins without coupling callers to its SQLite schema."""

    def __init__(
        self,
        pin_database_path: Path,
        *,
        atlas_database_path: Path | None = None,
    ) -> None:
        path = Path(pin_database_path)
        self._validate_database_file(path)
        self._repository = PinRepository(path)
        self._atlas_db_path = Path(atlas_database_path) if atlas_database_path else None
        self.last_bootstrap: dict[str, int] | None = None
        self.last_enrichment: dict[str, int] | None = None
        self.last_place_backfill: dict[str, int] | None = None
        self.last_cid_reconcile: dict[str, int] | None = None
        self.last_sync: dict[str, int] | None = None

    def list_pins(self) -> list[SavedLocation]:
        return self._repository.get_all_pins()

    def get_pin_details(self, pin_id: str) -> SavedLocation | None:
        return next((pin for pin in self.list_pins() if pin.id == pin_id), None)

    def list_clusters(self) -> list[dict]:
        """Return Phase 1's persisted geographic clusters without recomputing them."""
        return self._repository.load_clusters()

    def sync_pipeline(
        self,
        takeout_directory: Path,
        geocoded_csv_path: Path,
        *,
        threshold_km: float = 15.0,
        force_refresh: bool = False,
    ) -> dict[str, int]:
        """Run import enrichment, geocoding, and clustering in the correct order."""
        if force_refresh or self._repository.count() > 0:
            merge = self.refresh_from_takeout(takeout_directory)
            bootstrap = {
                "inserted": merge.get("inserted", 0),
                "duplicates_removed": 0,
                "clusters": 0,
                "updated": merge.get("updated", 0),
            }
        else:
            bootstrap = self.bootstrap_from_takeout(
                takeout_directory, threshold_km=threshold_km
            )
        enrichment = self.enrich_from_geocoded_csv(geocoded_csv_path, threshold_km=threshold_km)
        backfill = self.backfill_places()
        clusters = self.recluster(threshold_km=threshold_km)
        self.last_sync = {
            "inserted": bootstrap["inserted"],
            "updated": int(bootstrap.get("updated") or 0),
            "coordinates_updated": enrichment["updated"],
            "places_backfilled": backfill["updated"],
            "clusters": clusters,
        }
        return self.last_sync

    def refresh_from_takeout(self, takeout_directory: Path) -> dict[str, int]:
        """Merge a fresh Takeout export into an existing pin DB (insert + update)."""
        directory = Path(takeout_directory)
        if not directory.is_dir():
            self.last_bootstrap = {
                "inserted": 0,
                "updated": 0,
                "unchanged": 0,
                "duplicates_removed": 0,
                "clusters": 0,
            }
            return self.last_bootstrap
        parser = TakeoutParser()
        locations = parser.parse_directory(directory)
        stats = self._repository.upsert_pins_batch(locations)
        duplicates_removed = self._repository.deduplicate()
        self.last_bootstrap = {
            **stats,
            "duplicates_removed": duplicates_removed,
            "clusters": 0,
        }
        return self.last_bootstrap

    def recluster(self, threshold_km: float = 15.0) -> int:
        clusters = PinClusterer(
            ClusterConfig(distance_threshold_km=threshold_km)
        ).cluster_pins(self._repository.get_pins_with_coords())
        self._repository.save_clusters(clusters)
        return len(clusters)

    def bootstrap_from_takeout(
        self, takeout_directory: Path, threshold_km: float = 15.0
    ) -> dict[str, int]:
        """Import the owner's local Saved-list export only into an empty pin database."""
        if self._repository.count() > 0:
            self.last_bootstrap = {"inserted": 0, "duplicates_removed": 0, "clusters": 0}
            return self.last_bootstrap
        directory = Path(takeout_directory)
        if not directory.is_dir():
            self.last_bootstrap = {"inserted": 0, "duplicates_removed": 0, "clusters": 0}
            return self.last_bootstrap
        parser = TakeoutParser()
        locations = parser.parse_directory(directory)
        inserted = self._repository.insert_pins_batch(locations)
        duplicates_removed = self._repository.deduplicate()
        self.last_bootstrap = {
            "inserted": inserted,
            "duplicates_removed": duplicates_removed,
            "clusters": 0,
        }
        return self.last_bootstrap

    def enrich_from_geocoded_csv(
        self, csv_path: Path, threshold_km: float = 15.0
    ) -> dict[str, int]:
        """Apply geocoded Want-to-go CSV coords (fill missing or correct conflicts).

        When the CSV and pin disagree by more than ``threshold_km`` for the same
        URL/title, the CSV wins — that is how CID-corrected rows fix Nominatim
        misses like Links N' Ice in the wrong country.
        """
        path = Path(csv_path)
        empty = {"updated": 0, "unmatched": 0, "clusters": 0, "corrected": 0}
        if not path.is_file():
            self.last_enrichment = empty
            return self.last_enrichment

        by_url: dict[str, tuple[float, float]] = {}
        by_title: dict[str, tuple[float, float]] = {}
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                title = (row.get("Title") or "").strip()
                url = (row.get("URL") or "").strip()
                try:
                    lat = float(row.get("Latitude") or "")
                    lng = float(row.get("Longitude") or "")
                except (TypeError, ValueError):
                    continue
                if lat == 0.0 and lng == 0.0:
                    continue
                if not (-90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0):
                    continue
                if url:
                    by_url[url] = (lat, lng)
                if title and title not in by_title:
                    by_title[title] = (lat, lng)

        media_cache = (
            PlaceMediaCache(self._atlas_db_path) if self._atlas_db_path else None
        )
        updated = 0
        corrected = 0
        unmatched = 0
        for pin in self.list_pins():
            coords = None
            pin_url = self._url_from_pin(pin)
            if pin_url and pin_url in by_url:
                coords = by_url[pin_url]
            elif pin.name in by_title:
                coords = by_title[pin.name]
            if coords is None:
                if not self._has_coordinates(pin):
                    unmatched += 1
                continue

            if self._has_coordinates(pin):
                if not coords_conflict(
                    pin.latitude,
                    pin.longitude,
                    coords[0],
                    coords[1],
                    threshold_km=threshold_km,
                ):
                    continue
                # CSV disagrees — treat as correction of a bad Nominatim hit.
                if self._repository.update_pin_coordinates(pin.id, coords[0], coords[1]):
                    self._repository.update_pin_place(pin.id, None, None, None)
                    if media_cache:
                        media_cache.invalidate_pin(pin.id)
                    if self._atlas_db_path:
                        GeocodeCache(self._atlas_db_path).delete(pin.id)
                    corrected += 1
                    updated += 1
                continue

            if self._repository.update_pin_coordinates(pin.id, coords[0], coords[1]):
                updated += 1

        self.last_enrichment = {
            "updated": updated,
            "corrected": corrected,
            "unmatched": unmatched,
            "clusters": 0,
        }
        return self.last_enrichment

    def fill_missing_coordinates_from_cid(
        self,
        *,
        sleep_s: float = 0.0,
        limit: int | None = None,
    ) -> dict[str, int]:
        """Resolve lat/lng for pins stuck at 0,0 via Google Maps CID embed.

        Only touches pins without coordinates that have a Maps URL in raw_json.
        Does not run on every page-load sync — call from Refresh or a script.
        """
        import time

        from src_phase1.google_place_identity import resolve_coords_via_cid_embed

        updated = 0
        checked = 0
        failed = 0
        for pin in self.list_pins():
            if limit is not None and checked >= limit:
                break
            if self._has_coordinates(pin):
                continue
            url = url_from_raw_json(pin.raw_json)
            if not url:
                continue
            checked += 1
            coords = resolve_coords_via_cid_embed(url)
            if sleep_s > 0:
                time.sleep(sleep_s)
            if not coords:
                failed += 1
                continue
            if self._repository.update_pin_coordinates(pin.id, coords[0], coords[1]):
                updated += 1

        self.last_cid_reconcile = {
            "updated": updated,
            "checked": checked,
            "failed": failed,
        }
        return self.last_cid_reconcile

    def reconcile_coordinates_from_google_cid(
        self,
        *,
        conflict_km: float = 50.0,
        limit: int | None = None,
    ) -> dict[str, int]:
        """Correct pins whose Nominatim coords disagree with the Google Maps CID.

        Uses keyless CID embed resolution (and Places API when keyed). Clears
        place labels + media cache for corrected pins so reverse geocode can
        refill the right country.
        """
        updated = 0
        checked = 0
        media_cache = (
            PlaceMediaCache(self._atlas_db_path) if self._atlas_db_path else None
        )
        for pin in self.list_pins():
            if limit is not None and checked >= limit:
                break
            url = url_from_raw_json(pin.raw_json)
            if not url:
                continue
            checked += 1
            resolved = resolve_place_identity(
                name=pin.name,
                url=url,
                latitude=pin.latitude,
                longitude=pin.longitude,
            )
            if resolved is None:
                continue
            if not coords_conflict(
                pin.latitude,
                pin.longitude,
                resolved.latitude,
                resolved.longitude,
                threshold_km=conflict_km,
            ):
                continue
            if self._repository.update_pin_coordinates(
                pin.id, resolved.latitude, resolved.longitude
            ):
                # Force place backfill on next pass.
                self._repository.update_pin_place(pin.id, None, None, None)
                if media_cache:
                    media_cache.invalidate_pin(pin.id)
                if self._atlas_db_path:
                    GeocodeCache(self._atlas_db_path).delete(pin.id)
                updated += 1

        self.last_cid_reconcile = {"updated": updated, "checked": checked}
        return self.last_cid_reconcile

    def backfill_places(self) -> dict[str, int]:
        """Fill missing city/region/country via cached reverse geocoding."""
        cache = GeocodeCache(self._atlas_db_path) if self._atlas_db_path else None
        updated = 0
        skipped = 0
        for pin in self.list_pins():
            if is_wishlist_country_name(pin.name) and not pin.country:
                country = normalize_country(pin.name) or pin.name.strip()
                if self._repository.update_pin_place(
                    pin.id, city=None, country=country, region=None
                ):
                    updated += 1
                continue

            if not self._has_coordinates(pin):
                skipped += 1
                continue
            if pin.city and pin.country and (pin.region or not self._needs_region(pin)):
                continue

            result: GeocodeResult | None = None
            if cache:
                result = cache.get(pin.id)
            if result is None:
                result = reverse_geocode_pin(pin.latitude, pin.longitude)
                if result and cache:
                    cache.save(pin.id, result)
            if result is None:
                skipped += 1
                continue

            next_city = pin.city or result.city
            next_region = pin.region or result.region
            next_country = pin.country or result.country
            if not next_city and not next_country:
                skipped += 1
                continue
            if self._repository.update_pin_place(
                pin.id, next_city, next_country, next_region
            ):
                updated += 1
            else:
                skipped += 1

        self.last_place_backfill = {"updated": updated, "skipped": skipped}
        return self.last_place_backfill

    def source_hash(self, pin: SavedLocation) -> str:
        payload = {
            "media_strategy": MEDIA_STRATEGY_VERSION,
            "name": pin.name,
            "city": pin.city,
            "region": pin.region,
            "country": pin.country,
            "latitude": round(pin.latitude, 5),
            "longitude": round(pin.longitude, 5),
            "category": pin.category,
            "notes": pin.notes,
            "list_name": pin.list_name,
            "tags": pin.tags,
            "raw_json": self._safe_raw_fields(pin.raw_json),
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()

    def nearby_pins(self, pin: SavedLocation, limit: int = 5) -> list[SavedLocation]:
        if not self._has_coordinates(pin):
            return []
        distances = [
            (
                haversine_km(pin.latitude, pin.longitude, other.latitude, other.longitude),
                other,
            )
            for other in self.list_pins()
            if other.id != pin.id and self._has_coordinates(other)
        ]
        return [other for _, other in sorted(distances, key=lambda item: item[0])[:limit]]

    @staticmethod
    def _needs_region(pin: SavedLocation) -> bool:
        from src_phase1.geo_grouping import is_united_kingdom, is_united_states

        return is_united_states(pin.country) or is_united_kingdom(pin.country)

    @staticmethod
    def _validate_database_file(path: Path) -> None:
        if not path.exists():
            return
        header = path.read_bytes()[:64]
        if header.startswith(b"version https://git-lfs.github.com/spec/v1"):
            raise PinDataUnavailableError(
                "travel_pins.db is a Git LFS pointer, not the SQLite database. "
                "Run `git lfs pull` from the repository root to restore your local pin data."
            )
        if not header.startswith(b"SQLite format 3\x00"):
            raise PinDataUnavailableError(
                "travel_pins.db is not a valid SQLite file. Restore it from a backup "
                "or re-import your Google Takeout data through the Phase 1 dashboard."
            )

    @staticmethod
    def _has_coordinates(pin: SavedLocation) -> bool:
        return pin.latitude != 0 or pin.longitude != 0

    @staticmethod
    def _url_from_pin(pin: SavedLocation) -> str | None:
        try:
            payload = json.loads(pin.raw_json)
        except (TypeError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        url = payload.get("URL") or payload.get("url")
        return str(url).strip() if url else None

    @staticmethod
    def _safe_raw_fields(raw_json: str) -> dict[str, str]:
        try:
            payload = json.loads(raw_json)
        except (TypeError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {
            key: value
            for key, value in payload.items()
            if isinstance(value, str) and key.lower() in {"name", "title", "category", "description"}
        }
