"""Passport / Global Entry / cities / multi-destination entry helpers."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping

from travel_atlas.providers.state_dept import StateDeptSafetyProvider, country_tag
from travel_atlas.services.preferences_service import PreferencesService
from travel_atlas.services.region_map import region_map_image_url

DEFAULT_TRAVELER_DOCUMENTS: dict[str, Any] = {
    "passport_country": "United States of America",
    "passport_expires": "2033-01-01",
    "visa_pages_total": 26,
    "visa_pages_used": 6,
    "visa_pages_blank": 20,
    "global_entry_expires": "2030-01-01",
    # Global Entry includes TSA PreCheck for domestic US flights.
    "tsa_precheck": True,
    "tsa_precheck_via_global_entry": True,
    "tsa_precheck_recommended": True,
}

PASSPORT_VALIDITY_MONTHS = {
    "UK": 6,
    "EI": 6,
    "FR": 3,
    "SP": 3,
    "PO": 3,
    "JA": 6,
}

MAJOR_CITIES: dict[str, list[str]] = {
    "England": ["London", "Manchester", "Liverpool", "York", "Bath", "Oxford", "Cambridge"],
    "Scotland": ["Edinburgh", "Glasgow", "Inverness", "Aberdeen", "St Andrews"],
    "Wales": ["Cardiff", "Snowdonia", "Swansea"],
    "Northern Ireland": ["Belfast", "Giant's Causeway", "Derry"],
    "Ireland": ["Dublin", "Galway", "Cork", "Howth", "Killarney"],
    "France": ["Paris", "Lyon", "Marseille", "Nice", "Bordeaux", "Normandy"],
    "Spain": ["Madrid", "Barcelona", "Seville", "Valencia", "Basque Country"],
    "Portugal": ["Lisbon", "Porto", "Sintra", "Algarve", "Óbidos"],
    "United Kingdom": ["London", "Edinburgh", "Glasgow", "Manchester", "Cardiff", "Belfast"],
    "Alaska": ["Fairbanks", "Chena Hot Springs"],
}

#: Approximate city centers for free OSM/static maps.
CITY_COORDS: dict[str, tuple[float, float]] = {
    "London": (51.5074, -0.1278),
    "Manchester": (53.4808, -2.2426),
    "Liverpool": (53.4084, -2.9916),
    "York": (53.9600, -1.0873),
    "Bath": (51.3811, -2.3590),
    "Oxford": (51.7520, -1.2577),
    "Cambridge": (52.2053, 0.1218),
    "Edinburgh": (55.9533, -3.1883),
    "Glasgow": (55.8642, -4.2518),
    "Inverness": (57.4778, -4.2247),
    "Aberdeen": (57.1497, -2.0943),
    "St Andrews": (56.3398, -2.7967),
    "Cardiff": (51.4816, -3.1791),
    "Snowdonia": (53.0685, -4.0763),
    "Swansea": (51.6214, -3.9436),
    "Belfast": (54.5973, -5.9301),
    "Giant's Causeway": (55.2408, -6.5116),
    "Derry": (54.9966, -7.3086),
    "Dublin": (53.3498, -6.2603),
    "Galway": (53.2707, -9.0568),
    "Cork": (51.8985, -8.4756),
    "Howth": (53.3861, -6.0653),
    "Killarney": (52.0599, -9.5044),
    "Paris": (48.8566, 2.3522),
    "Lyon": (45.7640, 4.8357),
    "Marseille": (43.2965, 5.3698),
    "Nice": (43.7102, 7.2620),
    "Bordeaux": (44.8378, -0.5792),
    "Normandy": (49.1829, -0.3707),
    "Madrid": (40.4168, -3.7038),
    "Barcelona": (41.3874, 2.1686),
    "Seville": (37.3891, -5.9845),
    "Valencia": (39.4699, -0.3763),
    "Basque Country": (43.2630, -2.9350),
    "Lisbon": (38.7223, -9.1393),
    "Porto": (41.1579, -8.6291),
    "Sintra": (38.8029, -9.3817),
    "Algarve": (37.0179, -7.9304),
    "Óbidos": (39.3621, -9.1572),
    "Libreville": (0.4162, 9.4673),
    "Fairbanks": (64.8378, -147.7164),
    "Chena Hot Springs": (65.0519, -146.0478),
    "Los Angeles": (34.0522, -118.2437),
}

UK_NATION_EXPAND = {
    "United Kingdom": ["England", "Scotland", "Wales", "Northern Ireland"],
    "UK": ["England", "Scotland", "Wales", "Northern Ireland"],
}


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def expand_trip_regions(destination_labels: list[str]) -> list[str]:
    """Expand UK into nations for the cities slider; keep Ireland separate."""
    out: list[str] = []
    seen: set[str] = set()
    for label in destination_labels:
        clean = label.replace(" (UK)", "").strip()
        pieces = UK_NATION_EXPAND.get(clean, [clean])
        for piece in pieces:
            if piece not in seen and piece in MAJOR_CITIES:
                seen.add(piece)
                out.append(piece)
            elif piece not in seen and piece not in UK_NATION_EXPAND:
                # Non-seeded destinations still appear as a single slider entry.
                if piece in MAJOR_CITIES or True:
                    if piece not in seen:
                        seen.add(piece)
                        out.append(piece)
    return out


#: US-passport if/then hints for West Europe. Not legal advice — verify State Dept.
ENTRY_CONDITIONALS: dict[str, list[str]] = {
    "default": [
        "If your US passport is valid: short tourist stays in Western Europe are usually visa-free — confirm current rules.",
        "If fewer than 2 blank visa pages: some borders still want empty pages — renew or add pages before you fly.",
        "If Global Entry is valid: use it on return to the US; TSA PreCheck is included on domestic US legs.",
    ],
    "France": [
        "If entering the Schengen Area (France): visa-free stay typically up to 90 days in any 180-day window.",
        "If ETIAS is in force for US travelers: complete the online authorization before boarding.",
        "If your passport expires within ~3 months of the end of stay: renew first (France/Schengen validity buffer).",
    ],
    "Spain": [
        "If entering Schengen via Spain: same 90/180 visa-free clock as France/Portugal — it is one area, not a fresh 90 days per country.",
        "If ETIAS is in force: authorization is per traveler, not per entry.",
        "If visiting cannabis social clubs: private-club rules, not a tourist shop — bring passport/ID as members require.",
    ],
    "Portugal": [
        "If entering Schengen via Portugal: 90/180 visa-free with the rest of Schengen.",
        "If ETIAS is in force: get it before the first Schengen boarding.",
        "If combining Ireland + Schengen: Ireland is not Schengen — that is a separate stamp/clock.",
    ],
    "Ireland": [
        "If you hold a US passport: visa-free short stay (typically up to 90 days) — Ireland is not in Schengen.",
        "If you already used Schengen days: they do not count against Ireland, and Ireland days do not count against Schengen.",
        "If your passport expires within ~6 months: Ireland often wants extra validity — check before you fly.",
    ],
    "United Kingdom": [
        "If you hold a US passport: visa-free short stay is typical; complete a UK ETA if it is required for your travel date.",
        "If the UK is not your only stop: UK time is separate from Schengen and from Ireland.",
        "If your passport expires within ~6 months of travel: UK/Ireland buffers are stricter than some Schengen states.",
    ],
}
ENTRY_CONDITIONALS["England"] = list(ENTRY_CONDITIONALS["United Kingdom"])
ENTRY_CONDITIONALS["Scotland"] = list(ENTRY_CONDITIONALS["United Kingdom"])
ENTRY_CONDITIONALS["Wales"] = list(ENTRY_CONDITIONALS["United Kingdom"])
ENTRY_CONDITIONALS["Northern Ireland"] = list(ENTRY_CONDITIONALS["United Kingdom"])


class TravelerDocsService:
    def __init__(
        self,
        preferences: PreferencesService,
        safety: StateDeptSafetyProvider | None = None,
    ) -> None:
        self.preferences = preferences
        self.safety = safety or StateDeptSafetyProvider()

    def ensure_defaults(self, user_key: str = "local-default") -> dict[str, Any]:
        profile = self.preferences.get_preferences(user_key)
        bag = dict(profile.get("preferences") or {})
        docs = dict(bag.get("traveler_documents") or {})
        changed = False
        for key, value in DEFAULT_TRAVELER_DOCUMENTS.items():
            if key not in docs:
                docs[key] = value
                changed = True
        # Global Entry covers PreCheck — keep them linked when GE is valid.
        ge = _parse_date(str(docs.get("global_entry_expires") or ""))
        if ge and ge > date.today():
            if not docs.get("tsa_precheck"):
                docs["tsa_precheck"] = True
                docs["tsa_precheck_via_global_entry"] = True
                changed = True
        if changed:
            bag["traveler_documents"] = docs
            self.preferences.merge_preference_bag(bag, user_key)
        if hasattr(self.safety, "purge_stale_iso_cache"):
            self.safety.purge_stale_iso_cache()
        return docs

    def get_documents(self, user_key: str = "local-default") -> dict[str, Any]:
        return self.ensure_defaults(user_key)

    def passport_status(
        self,
        *,
        destination: str,
        departure: date | None,
        user_key: str = "local-default",
        documents: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        docs = dict(documents) if documents is not None else self.get_documents(user_key)
        expires = _parse_date(str(docs.get("passport_expires") or ""))
        blank_raw = docs.get("visa_pages_blank")
        blank_pages = int(blank_raw) if blank_raw is not None else 0
        tag = country_tag(destination) or "UK"
        months_needed = PASSPORT_VALIDITY_MONTHS.get(tag, 6)
        issues: list[str] = []
        ok = True
        if expires is None:
            ok = False
            issues.append("Passport expiry date missing.")
        else:
            today = date.today()
            if expires <= today:
                ok = False
                issues.append("Passport is expired — renew before travel.")
            elif departure:
                buffer_days = months_needed * 30
                if (expires - departure).days < buffer_days:
                    ok = False
                    issues.append(
                        f"Passport may not meet ~{months_needed}-month validity "
                        f"expectation for {destination} relative to departure."
                    )
            elif (expires - today).days < months_needed * 30:
                issues.append(
                    f"Passport expires within ~{months_needed} months — "
                    "confirm destination validity rules."
                )
        if blank_raw is not None and blank_pages < 2:
            ok = False
            issues.append(
                f"Only {blank_pages} blank visa pages — some borders want 1–2 empty pages."
            )
        ge = _parse_date(str(docs.get("global_entry_expires") or ""))
        if ge and ge <= date.today():
            issues.append("Global Entry card is expired.")
        tsa = bool(docs.get("tsa_precheck"))
        via_ge = bool(docs.get("tsa_precheck_via_global_entry")) and bool(
            ge and ge > date.today()
        )
        if docs.get("tsa_precheck_recommended") and not tsa and not via_ge:
            issues.append("TSA PreCheck recommended — not marked as held yet.")

        return {
            "ok": ok and not any("expired" in i.lower() for i in issues),
            "issues": issues,
            "expires": docs.get("passport_expires"),
            "blank_pages": blank_pages if blank_raw is not None else None,
            "passport_country": docs.get("passport_country"),
            "global_entry_expires": docs.get("global_entry_expires"),
            "tsa_precheck": tsa or via_ge,
            "tsa_precheck_via_global_entry": via_ge,
            "months_needed_hint": months_needed,
        }

    def entry_requirements(self, destination: str) -> Mapping[str, Any]:
        result = self.safety.advisories(destination=destination)
        payload = result.payload if isinstance(result.payload, dict) else {}
        entry = next(
            (
                item
                for item in payload.get("items") or []
                if item.get("kind") == "entry_exit_requirements"
            ),
            None,
        )
        health = next(
            (item for item in payload.get("items") or [] if item.get("kind") == "health"),
            None,
        )
        embassy = next(
            (
                item
                for item in payload.get("items") or []
                if item.get("kind") == "travel_embassyAndConsulate"
            ),
            None,
        )
        laws = next(
            (
                item
                for item in payload.get("items") or []
                if item.get("kind") == "local_laws_and_special_circumstances"
            ),
            None,
        )
        geo = None
        raw_info = (payload.get("raw") or {}).get("information") or {}
        if isinstance(raw_info, dict):
            geo = raw_info.get("geopoliticalarea")
        return {
            "status": result.status,
            "tag": payload.get("tag"),
            "geopoliticalarea": geo,
            "entry": entry,
            "health": health,
            "embassy": embassy,
            "local_laws": laws,
            "links": result.links,
            "items": payload.get("items") or [],
        }

    def entry_for_destinations(self, destinations: list[str]) -> list[dict[str, Any]]:
        rows = []
        for dest in destinations:
            clean = dest.replace(" (UK)", "").strip()
            # UK nations share the UK State Dept page.
            api_label = (
                "United Kingdom"
                if clean in {"England", "Scotland", "Wales", "Northern Ireland"}
                else clean
            )
            payload = dict(self.entry_requirements(api_label))
            payload["destination"] = clean
            payload["api_label"] = api_label
            rows.append(payload)
        return rows

    def entry_conditionals(self, destination: str) -> list[str]:
        clean = destination.replace(" (UK)", "").strip()
        items = list(ENTRY_CONDITIONALS.get("default") or [])
        items.extend(ENTRY_CONDITIONALS.get(clean) or ENTRY_CONDITIONALS.get(clean.title()) or [])
        return items

    def major_cities(self, destination: str) -> list[str]:
        clean = destination.replace(" (UK)", "").strip()
        return list(MAJOR_CITIES.get(clean, MAJOR_CITIES.get(clean.title(), [])))

    def cities_map_url(self, destination: str) -> str | None:
        cities = self.major_cities(destination)
        coords = [CITY_COORDS[c] for c in cities if c in CITY_COORDS]
        return region_map_image_url(coords)

    def locator_map_for_area(self, geopoliticalarea: str | None) -> str | None:
        if not geopoliticalarea:
            return None
        # Best-effort: if Gabon/Libreville somehow appears, show where it is.
        key = geopoliticalarea.strip()
        if "Gabon" in key or key.casefold() == "gabon":
            return region_map_image_url([CITY_COORDS["Libreville"]])
        return None
