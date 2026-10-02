"""
Phase 1 — Google Takeout parser with full import auditing.

Every skipped record is logged with a reason in ``ImportReport``.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from .import_report import DropRecord, FileReport, ImportReport
from .models import SavedLocation

logger = logging.getLogger(__name__)

_DEBUG_LOG = Path(__file__).resolve().parents[2] / "debug-485335.log"

# Written into ``notes`` when a CSV row arrives without coordinates. It is a system
# placeholder, not something the user typed, so scoring must not treat it as a note.
GEOCODE_PENDING_NOTE = "Imported from CSV without coordinates — geocode pending"

_FILE_MAP: List[Tuple[str, str, str]] = [
    ("Saved Places.json",      "saved_places",   "Saved Places"),
    ("Reviews.json",           "reviews",        "Reviews"),
    ("Want to go.json",        "want_to_go",     "Want To Go"),
    ("Labeled places.json",    "labeled_places", "Labeled Places"),
    ("Starred places.json",    "starred_places", "Starred Places"),
    ("Visited places.json",    "visited_places", "Visited Places"),
]


def _agent_log(location: str, message: str, data: dict, hypothesis_id: str) -> None:
    # #region agent log
    try:
        payload = {
            "sessionId": "485335",
            "timestamp": int(time.time() * 1000),
            "location": location,
            "message": message,
            "data": data,
            "hypothesisId": hypothesis_id,
        }
        with _DEBUG_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        pass
    # #endregion


def _coords_from_google_url(url: str) -> Tuple[Optional[float], Optional[float]]:
    """Extract lat/lng embedded in Google Maps URLs (Takeout CSV/JSON often only have URLs)."""
    if not url:
        return None, None
    # ?q=41.993752,5.326894 or &q=lat,lng
    m = re.search(r"[?&]q=(-?\d+\.?\d*),(-?\d+\.?\d*)", url)
    if m:
        lat, lng = float(m.group(1)), float(m.group(2))
        if _valid_coords(lat, lng):
            return lat, lng
    # /@34.0167898,-118.4709157,17z
    m = re.search(r"@(-?\d+\.?\d*),(-?\d+\.?\d*)", url)
    if m:
        lat, lng = float(m.group(1)), float(m.group(2))
        if _valid_coords(lat, lng):
            return lat, lng
    # !3d34.0167898!4d-118.47091569999999
    m = re.search(r"!3d(-?\d+\.?\d*)!4d(-?\d+\.?\d*)", url)
    if m:
        lat, lng = float(m.group(1)), float(m.group(2))
        if _valid_coords(lat, lng):
            return lat, lng
    # /search/41.993752,5.326894
    m = re.search(r"/search/(-?\d+\.?\d*),(-?\d+\.?\d*)", url)
    if m:
        lat, lng = float(m.group(1)), float(m.group(2))
        if _valid_coords(lat, lng):
            return lat, lng
    return None, None


def check_takeout_completeness(root: Path) -> dict:
    """Report which Takeout categories are present vs missing for full pin export."""
    root = Path(root)
    checks = {
        "has_saved_places_json": bool(list(root.rglob("Saved Places.json"))),
        "has_reviews_json": bool(list(root.rglob("Reviews.json"))),
        "has_labeled_places": bool(list(root.rglob("Labeled places.json"))),
        "has_want_to_go_csv": bool(list(root.rglob("Want to go.csv"))),
        "has_starred_csv": bool(list(root.rglob("Starred places.csv"))),
        "has_favorites_csv": bool(list(root.rglob("Favorites.csv"))),
        "saved_csv_lists": sorted(
            p.name
            for p in root.rglob("*.csv")
            if "Saved" in p.parts or "saved" in str(p).lower()
        ),
        "maps_json_count": len(list(root.rglob("Maps/**/*.json"))) if root.exists() else 0,
    }
    checks["likely_incomplete"] = not (
        checks["has_want_to_go_csv"]
        or checks["has_starred_csv"]
        or checks["saved_csv_lists"]
    )
    checks["hint"] = (
        "Your export may only include 'Maps (your places)'. "
        "Re-export at takeout.google.com and also select **Saved** — "
        "that is where Want to go, Favorites, Starred, and custom lists live (CSV, one file per list)."
        if checks["likely_incomplete"]
        else "Saved list CSVs detected — good for full pin coverage."
    )
    return checks


class TakeoutParser:
    """Parse Google Takeout Maps data into SavedLocation objects."""

    def __init__(
        self,
        skip_missing_coords: bool = True,
        import_coordinateless: bool = True,
    ) -> None:
        """
        Args:
            skip_missing_coords: Skip records with no lat/lng unless
                ``import_coordinateless`` applies for Saved Places with a name.
            import_coordinateless: Import Saved Places that have a name from
                ``google_maps_url`` but Takeout sentinel coords [0, 0].
        """
        self.skip_missing_coords = skip_missing_coords
        self.import_coordinateless = import_coordinateless
        self._errors: List[str] = []
        self.last_report: ImportReport = ImportReport()
        self._current_file: str = ""

    def parse_zip(self, zip_path: Path) -> List[SavedLocation]:
        """Extract and parse every Maps/Saved JSON and CSV inside a Takeout ZIP."""
        locations: List[SavedLocation] = []
        self.last_report = ImportReport(source=str(zip_path))
        _agent_log("takeout_parser.parse_zip", "start", {"zip": str(zip_path)}, "B")

        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                names = zf.namelist()
                self.last_report.zip_total_entries = len(names)
                _agent_log(
                    "takeout_parser.parse_zip",
                    "zip_entries",
                    {"total": len(names), "sample": names[:20]},
                    "B",
                )

                for name in sorted(names):
                    if name.endswith("/"):
                        continue
                    lower = name.lower()
                    if lower.endswith(".json"):
                        if not self._is_maps_file(name):
                            continue
                        locations.extend(self._parse_zip_json(zf, name))
                    elif lower.endswith(".csv"):
                        if not self._is_takeout_csv(name):
                            self.last_report.non_json_skipped += 1
                            continue
                        locations.extend(self._parse_zip_csv(zf, name))
                    else:
                        self.last_report.non_json_skipped += 1

        except zipfile.BadZipFile as exc:
            logger.error("Bad ZIP file %s: %s", zip_path, exc)
            raise

        self.last_report.total_imported = len(locations)
        _agent_log(
            "takeout_parser.parse_zip",
            "complete",
            self.last_report.to_dict(),
            "A",
        )
        return locations

    def _parse_zip_json(self, zf: zipfile.ZipFile, name: str) -> List[SavedLocation]:
        self.last_report.json_files_matched += 1
        self._current_file = name
        file_report = self.last_report.get_or_create_file(name)
        try:
            raw = zf.read(name).decode("utf-8", errors="replace")
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            file_report.parse_error = str(exc)
            self.last_report.json_files_failed += 1
            logger.warning("Could not read %s: %s", name, exc)
            self._errors.append(f"{name}: {exc}")
            self.last_report.record_drop(name, "parse_failure", str(exc))
            return []
        self.last_report.json_files_parsed += 1
        parsed = self._dispatch(data, name)
        file_report.records_imported = len(parsed)
        return parsed

    def _parse_zip_csv(self, zf: zipfile.ZipFile, name: str) -> List[SavedLocation]:
        self.last_report.csv_files_matched += 1
        self._current_file = name
        file_report = self.last_report.get_or_create_file(name)
        try:
            raw = zf.read(name).decode("utf-8", errors="replace")
        except UnicodeDecodeError as exc:
            file_report.parse_error = str(exc)
            self.last_report.record_drop(name, "parse_failure", str(exc))
            return []
        self.last_report.csv_files_parsed += 1
        parsed = self._parse_csv_text(raw, name)
        file_report.records_imported = len(parsed)
        return parsed

    def parse_file(self, json_path: Path) -> List[SavedLocation]:
        """Parse a single JSON file."""
        self.last_report = ImportReport(source=str(json_path))
        self._current_file = json_path.name
        try:
            data = json.loads(json_path.read_text(encoding="utf-8", errors="replace"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Cannot parse %s: %s", json_path, exc)
            self.last_report.record_drop(json_path.name, "parse_failure", str(exc))
            return []
        self.last_report.json_files_parsed = 1
        self.last_report.json_files_matched = 1
        locs = self._dispatch(data, json_path.name)
        self.last_report.total_imported = len(locs)
        return locs

    def parse_directory(self, directory: Path) -> List[SavedLocation]:
        """Parse all JSON and Saved-list CSV files recursively under *directory*."""
        locations: List[SavedLocation] = []
        self.last_report = ImportReport(source=str(directory))
        json_paths = sorted(directory.rglob("*.json"))
        csv_paths = sorted(
            p
            for p in directory.rglob("*.csv")
            if self._is_takeout_csv(str(p.relative_to(directory)))
            and not p.stem.lower().endswith("_geocoded")
        )
        _agent_log(
            "takeout_parser.parse_directory",
            "start",
            {"dir": str(directory), "json_count": len(json_paths), "csv_count": len(csv_paths)},
            "B",
        )
        for json_path in json_paths:
            rel = str(json_path.relative_to(directory))
            if not self._is_maps_file(rel):
                continue
            self.last_report.json_files_matched += 1
            self._current_file = rel
            file_report = self.last_report.get_or_create_file(rel)
            try:
                data = json.loads(json_path.read_text(encoding="utf-8", errors="replace"))
            except (json.JSONDecodeError, OSError) as exc:
                file_report.parse_error = str(exc)
                self.last_report.json_files_failed += 1
                self.last_report.record_drop(rel, "parse_failure", str(exc))
                continue
            self.last_report.json_files_parsed += 1
            locs = self._dispatch(data, rel)
            file_report.records_imported = len(locs)
            locations.extend(locs)
        for csv_path in csv_paths:
            rel = str(csv_path.relative_to(directory))
            self.last_report.csv_files_matched += 1
            self._current_file = rel
            file_report = self.last_report.get_or_create_file(rel)
            try:
                raw = csv_path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                file_report.parse_error = str(exc)
                self.last_report.record_drop(rel, "parse_failure", str(exc))
                continue
            self.last_report.csv_files_parsed += 1
            locs = self._parse_csv_text(raw, rel)
            file_report.records_imported = len(locs)
            locations.extend(locs)
        self.last_report.total_imported = len(locations)
        return locations

    def _parse_csv_text(self, raw: str, source_file: str) -> List[SavedLocation]:
        """Parse a Takeout Saved-list CSV (Title, Note, URL, …)."""
        locations: List[SavedLocation] = []
        reader = csv.DictReader(io.StringIO(raw))
        if not reader.fieldnames:
            self.last_report.record_drop(source_file, "empty_csv", "no header row")
            return locations

        fields = {f.strip().lower(): f for f in reader.fieldnames if f}
        title_key = fields.get("title") or fields.get("place") or fields.get("name")
        url_key = fields.get("url")
        note_key = fields.get("note") or fields.get("notes")

        if not title_key and not url_key:
            self.last_report.record_drop(source_file, "unrecognized_csv", str(reader.fieldnames))
            return locations

        list_name = self._list_name_from_csv_path(source_file)
        source_type = "saved_list_csv"
        fr = self.last_report.get_or_create_file(source_file)
        rows = list(reader)
        fr.records_seen += len(rows)
        self.last_report.total_raw_records += len(rows)

        for row in rows:
            title = (row.get(title_key) or "").strip() if title_key else ""
            url = (row.get(url_key) or "").strip() if url_key else ""
            note = (row.get(note_key) or "").strip() if note_key else ""
            if not title and not url:
                self.last_report.record_drop(source_file, "empty_csv_row", "")
                continue

            lat, lng = self._coords_from_csv_row(row)
            if lat is None:
                lat, lng = _coords_from_google_url(url)
            name = title or _name_from_google_maps_url(url) or "Unnamed Place"

            if lat is None:
                if self.import_coordinateless and name:
                    loc = SavedLocation(
                        id=str(uuid.uuid4()),
                        name=name,
                        latitude=0.0,
                        longitude=0.0,
                        list_name=list_name,
                        notes=note or GEOCODE_PENDING_NOTE,
                        source_type=source_type,
                        source_file=source_file,
                        raw_json=json.dumps(dict(row), ensure_ascii=False),
                    )
                    fr.records_imported += 1
                    locations.append(loc)
                elif self.skip_missing_coords:
                    self.last_report.record_drop(source_file, "csv_no_coordinates", name[:80])
                continue

            city, country = None, None
            if note and "," in note:
                city, country = _parse_address(note)

            fr.records_imported += 1
            locations.append(
                SavedLocation(
                    id=str(uuid.uuid4()),
                    name=name,
                    latitude=lat,
                    longitude=lng,
                    city=city,
                    country=country,
                    list_name=list_name,
                    notes=note or None,
                    source_type=source_type,
                    source_file=source_file,
                    raw_json=json.dumps(dict(row), ensure_ascii=False),
                )
            )
        return locations

    @staticmethod
    def _list_name_from_csv_path(source_file: str) -> str:
        stem = Path(source_file).stem
        if stem.lower() in ("your local followed places", "your personalization feedback"):
            return stem.title()
        return stem.replace("_", " ").strip() or "Saved List"

    def _coords_from_csv_row(
        self, row: dict[str, str]
    ) -> tuple[float | None, float | None]:
        """Prefer explicit Latitude/Longitude columns when a geocoded CSV is imported."""
        lat, lng, _reason = self._coords_from_item(dict(row))
        return lat, lng

    @property
    def errors(self) -> List[str]:
        return list(self._errors)

    def _dispatch(self, data: Any, source_file: str) -> List[SavedLocation]:
        source_type, list_name = self._identify_source(source_file, data)

        if isinstance(data, dict) and data.get("type") == "FeatureCollection":
            return list(self._parse_feature_collection(data, source_type, list_name, source_file))

        if isinstance(data, list):
            return list(self._parse_array(data, source_type, list_name, source_file))

        if isinstance(data, dict) and isinstance(data.get("features"), list):
            if data.get("type") == "FeatureCollection" or any(
                isinstance(f, dict) and f.get("type") == "Feature" for f in data["features"]
            ):
                return list(
                    self._parse_feature_collection(
                        {"type": "FeatureCollection", "features": data["features"]},
                        source_type,
                        list_name,
                        source_file,
                    )
                )

        for key in ("features", "places", "locations", "items"):
            if isinstance(data, dict) and isinstance(data.get(key), list):
                return list(self._parse_array(data[key], source_type, list_name, source_file))

        logger.warning("Unrecognised format in %s — skipping", source_file)
        self.last_report.record_drop(source_file, "unrecognized_format", type(data).__name__)
        return []

    def _parse_feature_collection(
        self,
        data: Dict[str, Any],
        source_type: str,
        list_name: str,
        source_file: str,
    ) -> Iterator[SavedLocation]:
        features = data.get("features", [])
        fr = self.last_report.get_or_create_file(source_file)
        fr.records_seen += len(features)
        self.last_report.total_raw_records += len(features)

        for feature in features:
            loc = self._feature_to_location(feature, source_type, list_name, source_file)
            if loc is not None:
                yield loc

    def _parse_array(
        self,
        items: List[Any],
        source_type: str,
        list_name: str,
        source_file: str,
    ) -> Iterator[SavedLocation]:
        fr = self.last_report.get_or_create_file(source_file)
        dict_items = [i for i in items if isinstance(i, dict)]
        fr.records_seen += len(dict_items)
        self.last_report.total_raw_records += len(dict_items)

        for item in items:
            if not isinstance(item, dict):
                self.last_report.record_drop(source_file, "malformed_entry", "not a dict")
                continue
            if item.get("type") == "Feature":
                loc = self._feature_to_location(item, source_type, list_name, source_file)
            else:
                loc = self._item_to_location(item, source_type, list_name, source_file)
            if loc is not None:
                yield loc

    def _feature_to_location(
        self,
        feature: Dict[str, Any],
        source_type: str,
        list_name: str,
        source_file: str,
    ) -> Optional[SavedLocation]:
        props = _flatten_properties(feature.get("properties") or {})
        geometry = feature.get("geometry") or {}

        lat, lng, coord_reason = self._coords_from_geometry(geometry)
        url = str(props.get("google_maps_url") or "")
        if lat is None and url:
            lat, lng = _coords_from_google_url(url)
            if lat is not None:
                coord_reason = None

        name = (
            self._extract_name(props)
            or _name_from_google_maps_url(url)
        )

        if lat is None:
            if self.import_coordinateless and name:
                note = props.get("Comment") or "Imported without coordinates (Takeout export)"
                return self._make_location(
                    name=name,
                    lat=0.0,
                    lng=0.0,
                    props=props,
                    source_type=source_type,
                    list_name=list_name,
                    source_file=source_file,
                    feature=feature,
                    extra_notes=note,
                )
            if self.skip_missing_coords:
                reason = coord_reason or "missing_coordinates"
                detail = name or props.get("Comment", "")[:80]
                self.last_report.record_drop(source_file, reason, detail)
                return None

        if not name:
            name = "Unnamed Place"

        return self._make_location(
            name=name,
            lat=lat or 0.0,
            lng=lng or 0.0,
            props=props,
            source_type=source_type,
            list_name=list_name,
            source_file=source_file,
            feature=feature,
        )

    def _item_to_location(
        self,
        item: Dict[str, Any],
        source_type: str,
        list_name: str,
        source_file: str,
    ) -> Optional[SavedLocation]:
        flat = _flatten_properties(item) if "properties" not in item else item
        lat, lng, coord_reason = self._coords_from_item(flat)
        if lat is None and self.skip_missing_coords:
            self.last_report.record_drop(
                source_file,
                coord_reason or "missing_coordinates",
                self._extract_name(flat) or "",
            )
            return None

        name = self._extract_name(flat) or "Unnamed Place"
        city, country = self._extract_city_country(flat)
        notes = self._extract_notes(flat)
        category = self._extract_category(flat)
        actual_list = flat.get("list_name") or flat.get("listName") or list_name

        return SavedLocation(
            id=str(uuid.uuid4()),
            name=name,
            latitude=lat or 0.0,
            longitude=lng or 0.0,
            city=city,
            country=country,
            list_name=actual_list,
            notes=notes,
            category=category,
            source_type=source_type,
            source_file=source_file,
            raw_json=json.dumps(item, ensure_ascii=False),
        )

    def _make_location(
        self,
        name: str,
        lat: float,
        lng: float,
        props: dict,
        source_type: str,
        list_name: str,
        source_file: str,
        feature: dict,
        extra_notes: Optional[str] = None,
    ) -> SavedLocation:
        city, country = self._extract_city_country(props)
        notes = self._extract_notes(props) or extra_notes
        category = self._extract_category(props)
        actual_list = props.get("list_name") or props.get("List Name") or list_name
        fr = self.last_report.get_or_create_file(source_file)
        fr.records_imported += 1

        return SavedLocation(
            id=str(uuid.uuid4()),
            name=name,
            latitude=lat,
            longitude=lng,
            city=city,
            country=country,
            list_name=actual_list,
            notes=notes,
            category=category,
            source_type=source_type,
            source_file=source_file,
            raw_json=json.dumps(feature, ensure_ascii=False),
        )

    def _extract_name(self, obj: Dict[str, Any]) -> Optional[str]:
        for key in ("name", "Name", "title", "Title", "displayName", "placeName", "place_name"):
            val = obj.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
            if isinstance(val, dict):
                text = val.get("text") or val.get("value") or ""
                if text.strip():
                    return text.strip()
        return None

    def _extract_notes(self, obj: Dict[str, Any]) -> Optional[str]:
        for key in (
            "notes", "Notes", "comment", "Comment", "description", "snippet", "review",
            "review_text_published",
        ):
            val = obj.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return None

    def _extract_category(self, obj: Dict[str, Any]) -> Optional[str]:
        for key in ("category", "Category", "type", "placeType", "primaryType", "types"):
            val = obj.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip().lower()
            if isinstance(val, list) and val:
                return str(val[0]).strip().lower()
        return None

    def _extract_city_country(self, obj: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
        city: Optional[str] = None
        country: Optional[str] = None

        for key in ("city", "City", "locality", "administrative_area_level_2"):
            if obj.get(key):
                city = str(obj[key]).strip() or None
                break

        for key in ("country", "Country", "countryCode", "country_code"):
            if obj.get(key):
                raw = str(obj[key]).strip()
                country = raw or None
                break

        if not city or not country:
            address = (
                obj.get("address")
                or obj.get("formattedAddress")
                or obj.get("formatted_address")
                or obj.get("Address")
                or ""
            )
            if isinstance(address, str) and address.strip():
                parsed_city, parsed_country = _parse_address(address)
                city = city or parsed_city
                country = country or parsed_country

        return city, country

    def _coords_from_geometry(
        self, geometry: Dict[str, Any]
    ) -> Tuple[Optional[float], Optional[float], Optional[str]]:
        coords = geometry.get("coordinates")
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            try:
                lng = float(coords[0])
                lat = float(coords[1])
                if lat == 0.0 and lng == 0.0:
                    return None, None, "zero_sentinel"
                if _valid_coords(lat, lng):
                    return lat, lng, None
                return None, None, "invalid_coordinates"
            except (TypeError, ValueError):
                return None, None, "malformed_coordinates"
        return None, None, "missing_coordinates"

    def _coords_from_item(
        self, obj: Dict[str, Any]
    ) -> Tuple[Optional[float], Optional[float], Optional[str]]:
        for lat_key, lng_key in [
            ("latitude", "longitude"),
            ("lat", "lng"),
            ("lat", "lon"),
            ("Latitude", "Longitude"),
        ]:
            lat_raw = obj.get(lat_key)
            lng_raw = obj.get(lng_key)
            if lat_raw is not None and lng_raw is not None:
                try:
                    lat, lng = float(lat_raw), float(lng_raw)
                    if lat == 0.0 and lng == 0.0:
                        return None, None, "zero_sentinel"
                    if _valid_coords(lat, lng):
                        return lat, lng, None
                    return None, None, "invalid_coordinates"
                except (TypeError, ValueError):
                    pass

        for key in ("location", "Location", "coordinates", "geo"):
            nested = obj.get(key)
            if isinstance(nested, dict):
                lat, lng, reason = self._coords_from_item(nested)
                if lat is not None:
                    return lat, lng, reason

        geometry = obj.get("geometry")
        if isinstance(geometry, dict):
            return self._coords_from_geometry(geometry)

        return None, None, "missing_coordinates"

    @staticmethod
    def _identify_source(filename: str, data: Any) -> Tuple[str, str]:
        name_lower = Path(filename).name.lower()
        path_lower = filename.lower()
        for pattern, source_type, list_name in _FILE_MAP:
            if pattern.lower() in name_lower or pattern.lower() in path_lower:
                return source_type, list_name
        stem = Path(filename).stem.replace("_", " ").title()
        return "custom_list", stem

    @staticmethod
    def _is_takeout_csv(name: str) -> bool:
        """True for Takeout Saved-list CSVs (Want to go, custom lists, etc.)."""
        lower = name.lower().replace("\\", "/")
        if "/saved/" in lower or lower.startswith("saved/"):
            return True
        stem = Path(name).stem.lower()
        known = (
            "want to go", "starred places", "favorites", "saved places",
            "labeled places", "visited places",
        )
        if any(k in stem for k in known):
            return True
        if stem in ("your personalization feedback",):
            return False
        if "maps" in lower and stem not in (
            "your personalization feedback",
        ):
            return True
        return False

    @staticmethod
    def _is_maps_file(name: str) -> bool:
        lower = name.lower()
        if "/maps/" in lower or lower.startswith("maps/") or "takeout/maps" in lower:
            return True
        if "maps" in lower or "places" in lower or "reviews" in lower:
            return True
        for pattern, _, _ in _FILE_MAP:
            if pattern.lower() in lower:
                return True
        return False


def _valid_coords(lat: float, lng: float) -> bool:
    if lat == 0.0 and lng == 0.0:
        return False
    return -90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0


def _flatten_properties(props: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(props)
    location = props.get("location")
    if isinstance(location, dict):
        for key in ("name", "address", "country_code"):
            val = location.get(key)
            if val and key not in merged:
                merged[key] = val
        if location.get("country_code") and not merged.get("country"):
            merged["country"] = location["country_code"]
    return merged


def _name_from_google_maps_url(url: str) -> Optional[str]:
    if not url:
        return None
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    for key in ("q", "query"):
        values = query.get(key)
        if values and values[0].strip():
            return values[0].replace("+", " ").strip()
    return None


def _parse_address(address: str) -> Tuple[Optional[str], Optional[str]]:
    """Parse a formatted address. Ignore free-text notes that happen to contain commas."""
    from src_phase1.geo_grouping import is_known_country_label

    parts = [p.strip() for p in address.split(",") if p.strip()]
    if not parts:
        return None, None
    country = parts[-1] if len(parts) >= 1 else None
    if country and not is_known_country_label(country):
        return None, None
    city = parts[-2] if len(parts) >= 2 else None
    if city:
        city = re.sub(r"\b[A-Z]{1,2}\d[\d A-Z]*\b", "", city).strip() or city
    return city, country
