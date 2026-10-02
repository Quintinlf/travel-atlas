"""Review queue for machine-drafted knowledge claims.

Drafts do not count toward coverage and are not shown in the Explorer — they sit here
until a human accepts them. Each one is displayed next to the verbatim source quote it
was extracted from and a link to the article, so reviewing is a comparison rather than
a fact-check from memory.

Approving rescores the area's coverage immediately, which is the visible payoff: the
gap list shrinks as you work through the queue.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_TRAVEL_ROOT = Path(__file__).parent.parent
if str(_TRAVEL_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRAVEL_ROOT))

from travel_atlas.database import AtlasDatabase
from travel_atlas.ingest import build_worklist, provision_areas
from travel_atlas.ingest.gaps import summarise
from travel_atlas.ingest.pipeline import approve, reject
from travel_atlas.knowledge_loader import load_bundled_knowledge
from travel_atlas.repository import AtlasRepository

ATLAS_DB_PATH = _TRAVEL_ROOT / "atlas.db"
PIN_DB_PATH = _TRAVEL_ROOT / "travel_pins.db"

CONFIDENCE_BADGE = {"high": "🟢 high", "medium": "🟡 medium", "low": "🟠 low"}

#: Health, safety and legal claims should not be waved through in a batch — a wrong
#: emergency number or drug-law summary is the kind of error that matters in person.
SENSITIVE_CATEGORIES = {"health", "microbiome", "wellness_substances"}


@st.cache_resource
def get_repository() -> AtlasRepository:
    database = AtlasDatabase(ATLAS_DB_PATH)
    database.migrate()
    repository = AtlasRepository(database)
    load_bundled_knowledge(repository)
    return repository


def _render_coverage(repository: AtlasRepository) -> None:
    gaps = build_worklist(repository, pin_db_path=PIN_DB_PATH)
    stats = summarise(gaps)
    counts = repository.count_claims_by_status()

    columns = st.columns(4)
    columns[0].metric("Awaiting review", counts.get("draft", 0))
    columns[1].metric("Reviewed claims", counts.get("reviewed", 0))
    columns[2].metric("Open gaps", stats["gaps"])
    columns[3].metric("Areas with gaps", stats["areas"])

    if stats["gaps"]:
        with st.expander(f"What's still missing ({stats['areas']} areas)"):
            current = None
            for gap in gaps[:200]:
                if gap.area_id != current:
                    current = gap.area_id
                    st.markdown(f"**{gap.area_name}** · {gap.pin_count} pins")
                st.caption(f"　{gap.category_name} / {gap.topic_name}")
            if len(gaps) > 200:
                st.caption(f"… and {len(gaps) - 200} more")


def _render_claim(claim: dict) -> tuple[bool, bool]:
    """One draft with its evidence. Returns (approve, reject)."""
    value = claim["value"]
    sensitive = claim["category_key"] in SENSITIVE_CATEGORIES

    header = f"**{value['title']}**"
    if sensitive:
        header += " ⚠️"
    st.markdown(header)
    st.caption(
        f"{claim['area_name']} · {claim['category_name']} / {claim['topic_name']} · "
        f"{CONFIDENCE_BADGE.get(claim['confidence'], claim['confidence'])}"
    )
    st.write(value["body"])

    if claim.get("season_label"):
        st.caption(
            f"Seasonal: {claim['season_label']} "
            f"({claim.get('season_start_month_day')} → {claim.get('season_end_month_day')})"
        )

    quote = value.get("quote")
    if quote:
        st.markdown("> " + quote.replace("\n", " ").strip())
    else:
        st.warning("No supporting quote was returned — verify before approving.")

    st.caption(f"Source: [{claim['publisher']}]({claim['source_url']})")
    if sensitive:
        st.caption("Health, safety and legal claims are excluded from bulk approval.")

    left, right, _ = st.columns([1, 1, 6])
    approved = left.button("Approve", key=f"approve-{claim['id']}", type="primary")
    rejected = right.button("Reject", key=f"reject-{claim['id']}")
    st.divider()
    return approved, rejected


def main() -> None:
    st.set_page_config(page_title="Knowledge Review", layout="wide")
    repository = get_repository()

    st.title("Knowledge Review")
    st.caption(
        "Machine-drafted claims, each shown with the source text it came from. "
        "Nothing here affects coverage or the Explorer until you approve it."
    )

    _render_coverage(repository)
    st.divider()

    with st.sidebar:
        st.header("Setup")
        st.caption(
            "Areas come from your saved pins. Drafting runs from the command line:\n\n"
            "`python -m travel_atlas.ingest run --limit-areas 5`"
        )
        if st.button("Provision areas from pins"):
            provisioned = provision_areas(repository, PIN_DB_PATH)
            st.success(
                f"{len(provisioned.countries)} countries, "
                f"{len(provisioned.cities)} cities."
            )
            st.cache_resource.clear()

    areas = sorted(
        {
            (claim["area_id"], claim["area_name"])
            for claim in repository.list_claims_by_status("draft", limit=1000)
        },
        key=lambda item: item[1],
    )
    if not areas:
        st.info(
            "No drafts waiting. Run `python -m travel_atlas.ingest gaps` to see what is "
            "missing, then `run` to draft it."
        )
        return

    area_id = st.selectbox(
        "Area",
        options=[None, *[area[0] for area in areas]],
        format_func=lambda value: "All areas" if value is None else dict(areas)[value],
    )

    drafts = repository.list_claims_by_status("draft", area_id=area_id, limit=100)
    st.subheader(f"{len(drafts)} draft{'' if len(drafts) == 1 else 's'}")

    bulk = [c for c in drafts if c["category_key"] not in SENSITIVE_CATEGORIES]
    if bulk:
        confident = [c for c in bulk if c["confidence"] == "high" and c["value"].get("quote")]
        if confident and st.button(
            f"Approve {len(confident)} high-confidence, non-sensitive claims"
        ):
            approve(repository, [c["id"] for c in confident])
            st.success(f"Approved {len(confident)} claims and rescored coverage.")
            st.rerun()

    for claim in drafts:
        approved, rejected = _render_claim(claim)
        if approved:
            approve(repository, [claim["id"]])
            st.rerun()
        if rejected:
            reject(repository, [claim["id"]])
            st.rerun()


if __name__ == "__main__":
    main()
