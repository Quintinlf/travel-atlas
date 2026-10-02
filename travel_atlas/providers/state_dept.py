"""US State Department Consular Affairs Data API (no key required)."""

from __future__ import annotations

import html
import json
import re
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .base import StubResult

BASE = "https://cadataapi.state.gov/api"
USER_AGENT = "TravelAtlas/0.1 (personal travel planner)"
_TAG_RE = re.compile(r"<[^>]+>")

#: State Dept Consular API tags — NOT ISO-3166.
#: GB = Gabon, ES = El Salvador, PT = Pitcairn-ish mismatches historically.
#: UK = United Kingdom, SP = Spain, PO = Portugal, EI = Ireland.
COUNTRY_TAGS: dict[str, str] = {
    "united kingdom": "UK",
    "uk": "UK",
    "u.k.": "UK",
    "england": "UK",
    "scotland": "UK",
    "wales": "UK",
    "northern ireland": "UK",
    "ireland": "EI",
    "republic of ireland": "EI",
    "france": "FR",
    "spain": "SP",
    "portugal": "PO",
    "japan": "JA",
    "kazakhstan": "KZ",
}

#: Expected geopoliticalarea substrings used to reject wrong-country cache hits.
_EXPECTED_AREA: dict[str, tuple[str, ...]] = {
    "UK": ("unitedkingdom", "united kingdom", "uk"),
    "EI": ("ireland",),
    "FR": ("france",),
    "SP": ("spain",),
    "PO": ("portugal",),
    "JA": ("japan",),
    "KZ": ("kazakhstan",),
    # Gabon is intentional when user asks for Gabon
    "GB": ("gabon",),
}


def country_tag(destination: str) -> str | None:
    return COUNTRY_TAGS.get(destination.strip().lower())


def _area_matches_tag(tag: str, geopoliticalarea: str | None) -> bool:
    expected = _EXPECTED_AREA.get(tag.upper())
    if not expected or not geopoliticalarea:
        return True
    normalized = geopoliticalarea.replace(" ", "").casefold()
    return any(token.replace(" ", "") in normalized for token in expected)

def _strip_html(value: str | None) -> str:
    if not value:
        return ""
    text = _TAG_RE.sub(" ", value)
    text = html.unescape(text)
    return " ".join(text.split())


class StateDeptSafetyProvider:
    key = "state-dept-cadata-v1"

    def __init__(self, cache_db_path: Path | None = None) -> None:
        self.cache_db_path = Path(cache_db_path) if cache_db_path else None

    def advisories(self, *, destination: str) -> StubResult:
        tag = country_tag(destination)
        if not tag:
            return StubResult(
                provider=self.key,
                status="unsupported",
                payload={
                    "message": f"No State Dept tag mapped for {destination}.",
                    "destination": destination,
                    "items": [],
                },
                links={},
            )
        info = self.get_country_information(tag)
        advisory = self.get_travel_advisory(tag)
        if info is None and advisory is None:
            return StubResult(
                provider=self.key,
                status="offline",
                payload={
                    "message": "Could not reach State Dept API. Check network.",
                    "destination": destination,
                    "items": [],
                },
                links={
                    "travel_state_gov": f"https://travel.state.gov/content/travel/en/international-travel/International-Travel-Country-Information-Pages.html"
                },
            )

        items = []
        if advisory:
            items.append(
                {
                    "kind": "advisory",
                    "title": advisory.get("title") or "Travel advisory",
                    "body": _strip_html(advisory.get("description") or advisory.get("body")),
                    "level": advisory.get("level") or advisory.get("alert_level"),
                }
            )
        if info:
            for field, title in (
                ("entry_exit_requirements", "Entry / exit requirements"),
                ("health", "Health & vaccinations"),
                ("travel_embassyAndConsulate", "Embassy & consulate"),
                ("local_laws_and_special_circumstances", "Local laws"),
                ("travel_transportation", "Transportation"),
            ):
                body = _strip_html(info.get(field))
                if body:
                    items.append({"kind": field, "title": title, "body": body})

        return StubResult(
            provider=self.key,
            status="live",
            payload={
                "destination": destination,
                "tag": tag,
                "last_update": (info or {}).get("last_update_date"),
                "items": items,
                "raw": {"information": info, "advisory": advisory},
            },
            links={
                "country_page": f"https://travel.state.gov/content/travel/en/international-travel/International-Travel-Country-Information-Pages/{tag}.html",
                "cdc": f"https://wwwnc.cdc.gov/travel/destinations/traveler/none/{destination.strip().lower().replace(' ', '-')}",
            },
        )

    def get_country_information(self, tag: str) -> dict[str, Any] | None:
        cached = self._cache_get(f"info:{tag}")
        if isinstance(cached, dict):
            area = str(cached.get("geopoliticalarea") or "")
            if _area_matches_tag(tag, area):
                return cached
            self._cache_delete(f"info:{tag}")
        data = self._get_json(f"{BASE}/CountryTravelInformation/{tag}")
        if isinstance(data, list):
            data = next(
                (
                    item
                    for item in data
                    if isinstance(item, dict)
                    and str(item.get("tag") or "").upper() == tag.upper()
                ),
                data[0] if data and isinstance(data[0], dict) else None,
            )
        if isinstance(data, dict):
            area = str(data.get("geopoliticalarea") or "")
            if not _area_matches_tag(tag, area):
                self._cache_delete(f"info:{tag}")
                return None
            self._cache_set(f"info:{tag}", data)
            return data
        return None

    def get_travel_advisory(self, tag: str) -> dict[str, Any] | None:
        cached = self._cache_get(f"advisory:{tag}")
        if isinstance(cached, dict):
            return cached
        data = self._get_json(f"{BASE}/TravelAdvisories/{tag}")
        if isinstance(data, list) and data:
            data = data[0]
        if isinstance(data, dict):
            self._cache_set(f"advisory:{tag}", data)
            return data
        return None

    def purge_stale_iso_cache(self) -> int:
        """Drop cache rows written under the old ISO-style tag mistakes."""
        if not self.cache_db_path or not self.cache_db_path.exists():
            return 0
        stale = (
            "info:GB",
            "advisory:GB",
            "info:ES",
            "advisory:ES",
            "info:PT",
            "advisory:PT",
            "info:IE",
            "advisory:IE",
            "info:JP",
            "advisory:JP",
        )
        deleted = 0
        try:
            with sqlite3.connect(self.cache_db_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS state_dept_cache (
                        cache_key TEXT PRIMARY KEY,
                        payload_json TEXT NOT NULL,
                        fetched_at TEXT NOT NULL
                    )
                    """
                )
                for key in stale:
                    cur = conn.execute(
                        "DELETE FROM state_dept_cache WHERE cache_key = ?", (key,)
                    )
                    deleted += cur.rowcount
                conn.commit()
        except sqlite3.Error:
            return deleted
        return deleted

    @staticmethod
    def _get_json(url: str) -> Any | None:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
            return None

    def _cache_get(self, key: str) -> Any | None:
        if not self.cache_db_path or not self.cache_db_path.exists():
            return None
        try:
            with sqlite3.connect(self.cache_db_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS state_dept_cache (
                        cache_key TEXT PRIMARY KEY,
                        payload_json TEXT NOT NULL,
                        fetched_at TEXT NOT NULL
                    )
                    """
                )
                row = conn.execute(
                    "SELECT payload_json FROM state_dept_cache WHERE cache_key = ?",
                    (key,),
                ).fetchone()
            if not row:
                return None
            return json.loads(row[0])
        except (sqlite3.Error, json.JSONDecodeError):
            return None

    def _cache_delete(self, key: str) -> None:
        if not self.cache_db_path or not self.cache_db_path.exists():
            return
        try:
            with sqlite3.connect(self.cache_db_path) as conn:
                conn.execute(
                    "DELETE FROM state_dept_cache WHERE cache_key = ?", (key,)
                )
                conn.commit()
        except sqlite3.Error:
            return

    def _cache_set(self, key: str, payload: Any) -> None:
        if not self.cache_db_path:
            return
        try:
            self.cache_db_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.cache_db_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS state_dept_cache (
                        cache_key TEXT PRIMARY KEY,
                        payload_json TEXT NOT NULL,
                        fetched_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO state_dept_cache(cache_key, payload_json, fetched_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(cache_key) DO UPDATE SET
                        payload_json=excluded.payload_json,
                        fetched_at=excluded.fetched_at
                    """,
                    (
                        key,
                        json.dumps(payload),
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
                conn.commit()
        except sqlite3.Error:
            return
