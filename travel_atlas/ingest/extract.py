"""Extract structured, sourced claims from fetched source text.

This is the only stage that calls a model, and it is deliberately the least creative
one. The model is given a document and a list of topics and asked to report *what this
document says* — not what it knows about the place. A topic the document does not cover
comes back as no claim at all, which is the behaviour that keeps the Atlas honest: the
alternative is a confidently-worded paragraph with a citation that does not support it.

Every claim comes back with a verbatim ``quote`` from the source. That quote is what
makes review fast — you are checking a sentence against its source, not fact-checking a
paragraph from scratch.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Sequence

from .gaps import Gap
from .sources import SourceDocument

DEFAULT_MODEL = "claude-opus-5"

#: Extraction is a bounded reading task, not open-ended reasoning. Lower effort holds
#: quality here while keeping a few-hundred-call run affordable; raise it if review
#: starts rejecting a lot.
DEFAULT_EFFORT = "medium"

SYSTEM_PROMPT = """\
You extract structured travel-knowledge claims from encyclopedia source text for a \
personal travel atlas.

Your single hard rule: every claim must be supported by the supplied document. You are \
reporting what this document says, not what you know about the place. Do not add facts \
from your own knowledge, do not generalise from a neighbouring country, and do not \
soften a gap by writing something vague and safe.

If the document does not meaningfully cover a requested topic, return no claim for that \
topic. An empty result is a correct and useful answer — a downstream process records \
the gap and looks elsewhere. Padding the list with thin claims is the worst outcome.

For each claim:
- `title`: a short specific noun phrase (e.g. "Regional fermented staples", not "Food").
- `body`: 2-4 sentences a traveller could act on. Concrete over generic: name the dish, \
the transit card, the emergency number, the custom. Write it as standalone prose - the \
reader does not see the source document.
- `quote`: a verbatim span copied from the document that supports the claim. Copy it \
exactly; do not paraphrase or stitch together distant sentences.
- `confidence`: `high` when the document states it plainly and it is unlikely to go \
stale; `medium` when it is stated but partial, or changes every few years (prices, \
schedules, visa rules); `low` when you are reading between the lines.
- Seasonal claims: set `season_label` plus `season_start_month_day` and \
`season_end_month_day` as `MM-DD` when the claim only holds during part of the year \
(a festival, a monsoon, a closure). Otherwise leave all three empty.

Safety, health and legal topics are held to a higher bar: state only what the document \
states, keep the wording factual rather than reassuring, and prefer `medium` confidence \
so a human reviews before a traveller relies on it.
"""


def _schema(topic_keys: Sequence[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "topic_key": {"type": "string", "enum": list(topic_keys)},
                        "title": {"type": "string"},
                        "body": {"type": "string"},
                        "quote": {"type": "string"},
                        "confidence": {
                            "type": "string",
                            "enum": ["high", "medium", "low"],
                        },
                        "season_label": {"type": "string"},
                        "season_start_month_day": {"type": "string"},
                        "season_end_month_day": {"type": "string"},
                    },
                    "required": [
                        "topic_key",
                        "title",
                        "body",
                        "quote",
                        "confidence",
                        "season_label",
                        "season_start_month_day",
                        "season_end_month_day",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["claims"],
        "additionalProperties": False,
    }


@dataclass(frozen=True)
class ExtractedClaim:
    topic_key: str
    title: str
    body: str
    quote: str
    confidence: str
    season_label: str | None
    season_start_month_day: str | None
    season_end_month_day: str | None

    def value(self) -> dict:
        """The ``knowledge_claim.value_json`` payload.

        ``title`` and ``body`` are the shape the existing Explorer UI renders; ``quote``
        rides along for the review queue and is ignored by readers that do not know
        about it.
        """
        return {"title": self.title, "body": self.body, "quote": self.quote}


class ExtractionUnavailable(Exception):
    """The Anthropic SDK is missing, or no credentials are configured."""


def build_client(api_key: str | None = None):
    """Construct an Anthropic client, failing with an actionable message.

    A bare ``Anthropic()`` also picks up an ``ant auth login`` profile, so an unset
    ``ANTHROPIC_API_KEY`` is not on its own a reason to refuse.
    """
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise ExtractionUnavailable(
            "The `anthropic` package is required for extraction. "
            "Install it with: pip install anthropic"
        ) from exc

    try:
        return anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    except Exception as exc:  # pragma: no cover - depends on the environment
        raise ExtractionUnavailable(
            "No Anthropic credentials found. Set ANTHROPIC_API_KEY, or run "
            f"`ant auth login`. ({exc})"
        ) from exc


def _prompt(area_name: str, area_type: str, gaps: Sequence[Gap], document: SourceDocument) -> str:
    topics = "\n".join(
        f"- `{gap.topic_key}` ({gap.category_name} / {gap.topic_name}): {gap.topic_description}"
        for gap in gaps
    )
    return (
        f"Place: {area_name} ({area_type})\n\n"
        f"Topics to look for:\n{topics}\n\n"
        f"Source: {document.title} - {document.url}\n"
        f"<document>\n{document.text}\n</document>\n\n"
        "Return claims for only the topics this document actually supports."
    )


def extract_claims(
    client,
    *,
    area_name: str,
    area_type: str,
    gaps: Sequence[Gap],
    document: SourceDocument,
    model: str = DEFAULT_MODEL,
    effort: str = DEFAULT_EFFORT,
) -> list[ExtractedClaim]:
    """Ask the model what this document supports, for these topics. Never invents."""
    if not gaps:
        return []

    response = client.messages.create(
        model=model,
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        output_config={
            "effort": effort,
            "format": {"type": "json_schema", "schema": _schema([g.topic_key for g in gaps])},
        },
        messages=[
            {
                "role": "user",
                "content": _prompt(area_name, area_type, gaps, document),
            }
        ],
    )

    if response.stop_reason == "refusal":
        raise ExtractionUnavailable(
            f"Model declined to process {area_name}: {response.stop_reason}"
        )

    text = next((block.text for block in response.content if block.type == "text"), "")
    if not text.strip():
        return []
    payload = json.loads(text)

    allowed = {gap.topic_key for gap in gaps}
    claims = []
    for raw in payload.get("claims", []):
        if raw.get("topic_key") not in allowed:
            continue
        if not (raw.get("title") or "").strip() or not (raw.get("body") or "").strip():
            continue
        claims.append(
            ExtractedClaim(
                topic_key=raw["topic_key"],
                title=raw["title"].strip(),
                body=raw["body"].strip(),
                quote=(raw.get("quote") or "").strip(),
                confidence=raw.get("confidence", "medium"),
                season_label=(raw.get("season_label") or "").strip() or None,
                season_start_month_day=(raw.get("season_start_month_day") or "").strip()
                or None,
                season_end_month_day=(raw.get("season_end_month_day") or "").strip() or None,
            )
        )
    return claims


def estimate_cost(call_count: int, *, avg_input_tokens: int = 4500, avg_output_tokens: int = 900) -> float:
    """Rough USD estimate for a run, at Claude Opus 5 rates ($5/$25 per MTok).

    Deliberately approximate — it exists so a dry run can say "this is about $8, not
    about $800" before you commit to a few hundred calls.
    """
    input_cost = call_count * avg_input_tokens / 1_000_000 * 5.0
    output_cost = call_count * avg_output_tokens / 1_000_000 * 25.0
    return round(input_cost + output_cost, 2)


def default_model() -> str:
    return os.environ.get("TRAVEL_ATLAS_MODEL", DEFAULT_MODEL)
