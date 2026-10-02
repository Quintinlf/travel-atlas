"""Optional imagery for Folium pin popups (Takeout does not include place photos)."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Optional

from src_phase1.google_place_identity import (
    extract_cid_decimal,
    url_from_raw_json,
)

if TYPE_CHECKING:
    from src_phase1.models import SavedLocation


def google_cid_from_pin(pin: "SavedLocation") -> Optional[str]:
    """Best-effort CID (decimal string) from preserved Takeout fields."""
    url = url_from_raw_json(pin.raw_json)
    cid = extract_cid_decimal(url)
    return str(cid) if cid is not None else None


def pin_popup_image_html(pin: "SavedLocation") -> str:
    """HTML snippet for Folium popups when GOOGLE_MAPS_API_KEY is set.

    Uses Street View Static API (location preview). This is not the same as the
    place-card thumbnail in the Google Maps app; that requires Places Photo API
    with a ``place_id`` resolved from the CID (see ``place_photo_static_url``).
    """
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if not api_key:
        return ""
    if pin.latitude == 0 and pin.longitude == 0:
        return ""
    src = (
        "https://maps.googleapis.com/maps/api/streetview"
        f"?size=320x180&location={pin.latitude},{pin.longitude}"
        f"&fov=80&key={api_key}"
    )
    return (
        f'<br><img src="{src}" width="240" '
        'style="border-radius:6px;margin-top:6px;" alt="Location preview">'
    )


def place_photo_static_url(
    place_id: str,
    *,
    max_width: int = 320,
    api_key: Optional[str] = None,
) -> Optional[str]:
    """URL for Places Photo (New) when you have already resolved ``place_id``."""
    key = (api_key or os.environ.get("GOOGLE_MAPS_API_KEY", "")).strip()
    if not key or not place_id:
        return None
    if place_id.startswith("places/"):
        return (
            f"https://places.googleapis.com/v1/{place_id}/media"
            f"?maxWidthPx={max_width}&key={key}"
        )
    return None
