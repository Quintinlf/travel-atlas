"""Fetch the source text a claim will be extracted from.

Two free, keyless, CC BY-SA corpora carry almost all of what the Atlas taxonomy asks
for. Wikivoyage is written *for travellers* and its article template maps onto the
practical topics almost one-to-one — "Eat", "Get around", "Stay safe", "Respect".
Wikipedia carries the depth Wikivoyage does not: history, religion, architecture,
ecology.

Only the sections a topic actually needs are fetched into the extraction prompt.
Sending a whole country article to answer "what are the emergency numbers" wastes
tokens and buries the answer.

Nothing here calls a model. This module's whole job is to return attributable text
plus the URL it came from, so a later claim can point at a real document.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Optional, Sequence

#: Wikimedia asks automated clients to identify themselves. Override
#: ``TRAVEL_ATLAS_CONTACT`` with an email so they can reach you about a misbehaving run.
USER_AGENT = (
    f"TravelAtlas/1.0 (personal travel knowledge base; "
    f"{os.environ.get('TRAVEL_ATLAS_CONTACT', 'no-contact-configured')}) python-urllib"
)

WIKIVOYAGE_API = "https://en.wikivoyage.org/w/api.php"
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"

WIKIVOYAGE_SOURCE_ID = "wikivoyage"
WIKIPEDIA_SOURCE_ID = "wikipedia"

#: Registered once per run so every drafted claim has a real ``source`` row to cite.
SOURCE_DEFINITIONS = [
    {
        "id": WIKIVOYAGE_SOURCE_ID,
        "title": "Wikivoyage",
        "publisher": "Wikimedia Foundation",
        "source_url": "https://en.wikivoyage.org/",
        "enrichment_url": "https://en.wikivoyage.org/wiki/Special:Search",
        "retrieved_at": None,
        "license_note": "Text available under CC BY-SA 4.0; attribute Wikivoyage contributors.",
    },
    {
        "id": WIKIPEDIA_SOURCE_ID,
        "title": "Wikipedia",
        "publisher": "Wikimedia Foundation",
        "source_url": "https://en.wikipedia.org/",
        "enrichment_url": "https://en.wikipedia.org/wiki/Special:Search",
        "retrieved_at": None,
        "license_note": "Text available under CC BY-SA 4.0; attribute Wikipedia contributors.",
    },
]


@dataclass(frozen=True)
class SourcePlan:
    """Where a topic's evidence lives: which corpus, and which sections of it."""

    source_id: str
    sections: tuple[str, ...]


#: Topic → where to look. Section names are matched case-insensitively against article
#: headings; a topic whose sections are all absent yields no document and the pair is
#: recorded as ``no_source`` rather than guessed at.
TOPIC_SOURCES: dict[str, tuple[SourcePlan, ...]] = {
    "primary_languages": (
        SourcePlan(WIKIVOYAGE_SOURCE_ID, ("Talk",)),
        SourcePlan(WIKIPEDIA_SOURCE_ID, ("Languages", "Language", "Demographics")),
    ),
    "visitor_phrases": (SourcePlan(WIKIVOYAGE_SOURCE_ID, ("Talk",)),),
    "etiquette": (
        SourcePlan(WIKIVOYAGE_SOURCE_ID, ("Respect", "Cope")),
        SourcePlan(WIKIPEDIA_SOURCE_ID, ("Culture", "Society")),
    ),
    "historical_context": (
        SourcePlan(WIKIPEDIA_SOURCE_ID, ("History",)),
        SourcePlan(WIKIVOYAGE_SOURCE_ID, ("Understand", "History")),
    ),
    "spiritual_traditions": (
        SourcePlan(WIKIPEDIA_SOURCE_ID, ("Religion", "Culture")),
    ),
    "religious_practices": (
        SourcePlan(WIKIPEDIA_SOURCE_ID, ("Religion",)),
        SourcePlan(WIKIVOYAGE_SOURCE_ID, ("Respect",)),
    ),
    "folk_beliefs": (
        SourcePlan(WIKIPEDIA_SOURCE_ID, ("Folklore", "Mythology", "Culture")),
    ),
    "seasonal_traditions": (
        SourcePlan(WIKIVOYAGE_SOURCE_ID, ("Holidays", "Festivals and holidays", "Do")),
        SourcePlan(WIKIPEDIA_SOURCE_ID, ("Culture", "Holidays")),
    ),
    "cuisine": (SourcePlan(WIKIVOYAGE_SOURCE_ID, ("Eat", "Drink")),),
    "fermented_foods": (
        SourcePlan(WIKIPEDIA_SOURCE_ID, ("Cuisine", "Food and drink")),
        SourcePlan(WIKIVOYAGE_SOURCE_ID, ("Eat",)),
    ),
    "health_advisory": (
        SourcePlan(WIKIVOYAGE_SOURCE_ID, ("Stay healthy", "Stay safe")),
    ),
    "food_water_safety": (SourcePlan(WIKIVOYAGE_SOURCE_ID, ("Stay healthy", "Eat")),),
    "pharmacy_medicine": (
        SourcePlan(WIKIVOYAGE_SOURCE_ID, ("Stay healthy", "Cope", "Buy")),
    ),
    "emergency_context": (
        SourcePlan(WIKIVOYAGE_SOURCE_ID, ("Stay safe", "Connect", "Cope")),
    ),
    "local_drug_laws": (SourcePlan(WIKIVOYAGE_SOURCE_ID, ("Stay safe", "Respect")),),
    "public_transport": (SourcePlan(WIKIVOYAGE_SOURCE_ID, ("Get around", "Get in")),),
    "payment_context": (SourcePlan(WIKIVOYAGE_SOURCE_ID, ("Buy", "Connect")),),
    "seasonality": (
        SourcePlan(WIKIVOYAGE_SOURCE_ID, ("Climate", "Understand", "When to go")),
        SourcePlan(WIKIPEDIA_SOURCE_ID, ("Climate", "Geography")),
    ),
    "ecological_heritage": (
        SourcePlan(WIKIPEDIA_SOURCE_ID, ("Geography", "Biodiversity", "Wildlife")),
    ),
    "urban_architecture": (
        SourcePlan(WIKIPEDIA_SOURCE_ID, ("Architecture", "Cityscape", "Culture")),
        SourcePlan(WIKIVOYAGE_SOURCE_ID, ("See",)),
    ),
}


@dataclass(frozen=True)
class SourceDocument:
    source_id: str
    title: str
    url: str
    text: str

    @property
    def external_key(self) -> str:
        return self.title

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


class SourceUnavailable(Exception):
    """The article does not exist, or the API could not be reached."""


def _api_get(api: str, params: dict[str, str], *, timeout: int = 20) -> dict:
    url = f"{api}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise SourceUnavailable(f"{api}: {exc}") from exc


def fetch_plain_text(source_id: str, title: str) -> Optional[str]:
    """Full article as plain text with ``== Heading ==`` markers intact.

    The ``extracts`` API is used rather than the raw wikitext because it strips
    templates, tables and reference markup while preserving section structure — which
    is exactly what section-scoped extraction needs.
    """
    api = WIKIVOYAGE_API if source_id == WIKIVOYAGE_SOURCE_ID else WIKIPEDIA_API
    payload = _api_get(
        api,
        {
            "action": "query",
            "prop": "extracts",
            "explaintext": "1",
            "redirects": "1",
            "format": "json",
            "formatversion": "2",
            "titles": title,
        },
    )
    pages = payload.get("query", {}).get("pages") or []
    if not pages:
        return None
    page = pages[0]
    if page.get("missing"):
        return None
    return page.get("extract") or None


_HEADING = re.compile(r"^(={2,6})\s*(.+?)\s*\1\s*$", re.MULTILINE)


def split_sections(text: str) -> dict[str, str]:
    """Split an extract into ``{heading: body}``, keyed case-insensitively.

    Only top-level (``==``) headings become keys; deeper subsections stay inside their
    parent's body, which is what a topic prompt wants — "Eat" should carry its
    "Street food" subsection along with it.
    """
    sections: dict[str, str] = {}
    matches = list(_HEADING.finditer(text))
    if not matches:
        return sections

    lead_end = matches[0].start()
    if text[:lead_end].strip():
        sections["__lead__"] = text[:lead_end].strip()

    current: str | None = None
    current_start = 0
    for match in matches:
        level = len(match.group(1))
        if level > 2:
            continue
        if current is not None:
            sections[current] = text[current_start : match.start()].strip()
        current = match.group(2).strip().lower()
        current_start = match.end()
    if current is not None:
        sections[current] = text[current_start:].strip()
    return sections


def fetch_sections(source_id: str, article_title: str) -> Optional[dict[str, str]]:
    """One article, split into sections. Fetch this once per (source, area) and reuse.

    An area's topics draw on overlapping sections of the same two articles, so fetching
    per topic would re-download the same page a dozen times.
    """
    text = fetch_plain_text(source_id, article_title)
    if not text:
        return None
    sections = split_sections(text)
    if not sections:
        sections = {"__lead__": text.strip()}
    return sections


def article_url(source_id: str, article_title: str) -> str:
    host = "en.wikivoyage.org" if source_id == WIKIVOYAGE_SOURCE_ID else "en.wikipedia.org"
    return f"https://{host}/wiki/{urllib.parse.quote(article_title.replace(' ', '_'))}"


def assemble_document(
    source_id: str,
    article_title: str,
    sections: dict[str, str],
    sections_wanted: Sequence[str],
    *,
    max_chars: int = 12000,
) -> Optional[SourceDocument]:
    """Keep only the sections the requested topics asked for."""
    seen: set[str] = set()
    parts: list[str] = []
    for name in (n.lower() for n in sections_wanted):
        if name in seen:
            continue
        seen.add(name)
        body = sections.get(name)
        if body:
            parts.append(f"== {name.title()} ==\n{body}")

    # Short articles (most cities) often have no matching heading at all; the lead
    # paragraph is still real, attributable text worth extracting from.
    if not parts:
        lead = sections.get("__lead__", "")
        if len(lead.strip()) < 200:
            return None
        parts.append(lead)

    return SourceDocument(
        source_id=source_id,
        title=article_title,
        url=article_url(source_id, article_title),
        text="\n\n".join(parts)[:max_chars],
    )


def build_document(
    source_id: str,
    article_title: str,
    sections_wanted: tuple[str, ...],
    *,
    max_chars: int = 12000,
) -> Optional[SourceDocument]:
    """Fetch one article and keep only the sections a topic asked for."""
    sections = fetch_sections(source_id, article_title)
    if sections is None:
        return None
    return assemble_document(
        source_id, article_title, sections, sections_wanted, max_chars=max_chars
    )


def documents_for_topic(
    topic_key: str, area_name: str, *, max_chars: int = 12000
) -> list[SourceDocument]:
    """Every source document available for one (area, topic) pair, best first."""
    plans = TOPIC_SOURCES.get(topic_key)
    if not plans:
        return []
    documents = []
    for plan in plans:
        try:
            document = build_document(
                plan.source_id, area_name, plan.sections, max_chars=max_chars
            )
        except SourceUnavailable:
            continue
        if document:
            documents.append(document)
    return documents
