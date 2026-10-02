"""Resolve culture/substance thumbs: local file, optional CSE, then Commons."""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from src_phase1 import commons_media

MEDIA_DIR = Path(__file__).resolve().parent.parent / "data" / "media"


def resolve_substance_image(item: dict[str, Any]) -> tuple[str | None, str]:
    """Return (path_or_url, caption). Prefer curated local files."""
    filename = (item.get("image_file") or "").strip()
    if filename:
        path = MEDIA_DIR / Path(filename).name
        if path.is_file():
            return str(path), "Curated photo"

    query = (item.get("image_query") or item.get("name") or "").strip()
    cse = _custom_search_image(query)
    if cse:
        return cse, "Google Custom Search"

    if query:
        photo = commons_media.find_photo(
            query,
            0.0,
            0.0,
            allow_nearby=False,
            require_name_match=True,
        )
        if photo:
            return photo.thumb_url, photo.attribution_line()
    return None, "No photo"


def _custom_search_image(query: str) -> str | None:
    """Optional Programmable Search (needs GOOGLE_CSE_ID + GOOGLE_CSE_API_KEY)."""
    if not query:
        return None
    cx = (os.environ.get("GOOGLE_CSE_ID") or "").strip()
    key = (
        os.environ.get("GOOGLE_CSE_API_KEY")
        or os.environ.get("GOOGLE_MAPS_API_KEY")
        or ""
    ).strip()
    if not cx or not key:
        return None
    params = urllib.parse.urlencode(
        {
            "key": key,
            "cx": cx,
            "q": query,
            "searchType": "image",
            "num": "1",
            "safe": "active",
            "imgType": "photo",
        }
    )
    url = f"https://www.googleapis.com/customsearch/v1?{params}"
    try:
        with urllib.request.urlopen(url, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None
    items = payload.get("items") or []
    if not items:
        return None
    link = items[0].get("link")
    return str(link) if link else None
