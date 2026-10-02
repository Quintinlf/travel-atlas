# Travel Atlas Explorer

The Travel Atlas is an offline-first, evidence-backed destination knowledge
system. It reads the existing Phase 1 Google Maps pins without modifying their
`travel_pins.db`, then combines them with the separate local `atlas.db`.

## Run

From the `travel_code` directory:

```bash
streamlit run travel/travel_atlas/app_streamlit.py
```

The app creates `travel/atlas.db` locally, loads bundled Japan/Tokyo knowledge,
and opens a browser-based Explorer. Phase 1 pins appear on the map:

- Blue pins have bundled Atlas destination knowledge.
- Gray pins receive explicitly labelled generic offline travel preparation.
- Selecting a pin shows its location resolution, cited cultural context,
  related saved places, and a location/category-specific language lesson.

Use the **Developer context** expander in a pin's detail view to inspect the
resolution method, classification terms, coverage, and lesson source.

## Filling the Atlas

The schema was always built for an encyclopedia; the bundled seed only covers a
handful of areas. `travel_atlas/ingest/` closes that gap by turning the coverage
ruleset into a worklist and drafting sourced claims against it:

```
pins → geo_area rows → coverage gaps → Wikivoyage/Wikipedia text → drafts → your review
```

```bash
python -m travel_atlas.ingest areas       # geography implied by your saved pins
python -m travel_atlas.ingest gaps        # what's missing + a cost estimate; no network
python -m travel_atlas.ingest run --limit-areas 5
python -m travel_atlas.ingest status      # review queue depth
```

`gaps` touches nothing external — run it first. `run` fetches article text, stores it
verbatim in `source_record`, and asks Claude to report **only what that text supports**;
a topic the article does not cover is recorded as a gap rather than guessed at. Every
claim lands as `review_status='draft'`, which is invisible to coverage scoring until you
approve it in the **Knowledge Review** page. Each draft is shown beside the verbatim
quote it came from, so reviewing is a comparison rather than a fact-check from memory.

Runs are resumable: `ingest_attempt` records every (area, topic) pair tried, including
the barren ones, so a rerun only does new work. Extraction needs `anthropic` plus either
`ANTHROPIC_API_KEY` or an `ant auth login` profile; area provisioning and gap listing do
not. Health, safety and legal claims are excluded from bulk approval by design.

## Modes and lifecycle

Travel Atlas separates **application modes** from **trip lifecycle**.

**Application modes** (global UI context):

| Mode | Role |
|------|------|
| **Research** | Curiosity browsing — Destination Atlas / knowledge; no trip required |
| **Planning** | Working on one or more non-committed trips |
| **Active Trip** | The focused committed trip (hotel or flight reserved) |
| **Archive** | Completed / remembered trips |

**Trip lifecycle** (per trip, independent):

**Idea → Planning → Committed → Preparation → Traveling → Completed → Remembered**

Commitment is **purchase-gated**: the first `reservation` of kind `hotel` or `flight` with status `reserved` sets `committed_at`. Dates refine stages inside that gate (prep bands **90 / 60 / 30 / 7**, auto `traveling` when today is between departure and return).

| Surface | Role |
|---------|------|
| **Today** | Only for the **active committed trip** — missions, lesson, prep score, reservation alerts |
| **Command Center** | Lifecycle strip, reservations, checklist, learning queue, logistics, budget, photos |
| **Planning** | Personalized recommendations & ratings |
| **Trip Planner** | Multi-destination / region-parent itineraries |

**Regions:** a parent `trip_plan` with `kind='region'` (e.g. West Europe 2026) can own child trips (UK, France, …) for budget rollups and reporting.

**Reservations** are a first-class domain (`reservation` table) — not buried under logistics. Statuses: not_available → available_soon → book_now → reserved → completed / cancelled.

**Photos** are first-class (`trip_photo`) with a `PhotoProvider` stub for future cloud sync. Shopping and Astrology exist only as unused provider protocols.

Providers under `travel_atlas/providers/` are **offline stubs** (`StubResult`) — Booking deep-links, Weather, Transit, Language (locality-first scheduler), Safety, Calendar, Photo, ReservationAvailability, plus Shopping/Astrology extension points.

Budget board tracks category estimates with **confidence** (heuristic → user estimate → actual).
Logistics cards answer “How do I get there?” with walking/taxi heuristics.
`TravelPackService` builds an offline cache manifest (itinerary, reservations, lessons, photo metadata).

## Planning layer

The Planning engine (`travel_atlas/planning/`) is a **read-only** reasoning layer.
It combines:

- Atlas knowledge (`atlas.db` claims and geo areas)
- Saved pins (`travel_pins.db`, read-only) — **the planning backbone**
- Expandable `user_profile.preferences_json`
- Trip constraints (`trip_plan.definition_json`)
- Learned category weights from ratings (`planning_weight_state`)

Philosophy: **maximum personal joy per dollar**, not cheapest or most famous.

Exploration mix defaults to **90% personalized / 10% discovery** (“I didn’t know I’d
like this”). Weekly day themes give itineraries rhythm (Body & Nourishment on Monday,
Major Day on Saturday, etc.) and are overridable.

`FeedbackService` writes ratings and trip journal entries; the engine never mutates
knowledge tables. Rating a museum “loved” raises that category’s multiplier for
future scores.

Open the **Planning** page in the unified app (`streamlit run travel/app_home.py`).

## Data model

- `geo_area`: country, region, and city hierarchy
- `knowledge_category` and `knowledge_topic`: extensible coverage taxonomy
- `source`, `source_record`, and `knowledge_claim`: attributable, structured knowledge
- `coverage_rule` and `coverage_assessment`: computed readiness, gaps, and confidence-aware completeness
- `dynamic_snapshot`: future cache boundary for weather, events, prices, schedules, and advisories
- `ingest_attempt`: which (area, topic) pairs the ingestion pipeline has already tried
- `user_profile`, `pin_classification`, and `language_lesson`: local personalization data; Phase 1 imported pins are not mutated
- `user_profile.preferences_json` / `trip_plan.definition_json`: expandable bags for planning preferences and trip constraints without schema rewrites
- `trip_plan` hierarchy: `parent_trip_id`, `kind` (region|trip), `lifecycle_stage`, `committed_at`, `active_focus`
- `reservation`: first-class booking intents and purchase records
- `trip_photo`: traveler photos linked to trip / place / day / journal (distinct from `place_media_cache`)

Companions (overlap / shared / solo planning) are a planned future engine, not in schema yet.
Astrology and shopping recommendations are provider extension points only.

Bundled foundational knowledge remains available offline. Dynamic data belongs
to adapters and must retain its source and refresh timestamps.

## Django migration boundary

The service methods in `travel_atlas/services/` are independent of Streamlit:
`get_pin_details`, `get_destination_context`, `generate_language_lesson`,
`get_itinerary`, and `PlanningEngine.plan` / `answer`. Django can later expose these
methods through views and replace the SQLite repository with ORM adapters without
changing classification, lesson-generation, or planning scoring rules.

## Current limitations

- The bundled destination corpus covers Japan, Tokyo, Kazakhstan and Almaty. Everywhere
  else has to be drafted and reviewed via the ingestion pipeline above.
- Ingestion is grounded in Wikivoyage and Wikipedia only. Topics those two do not cover
  well for a given place will stay empty rather than be filled in from model memory.
- Other saved places remain visible and receive generic offline lessons, but no
  location-specific cultural facts are inferred for them.
- Weather, events, transit status, currency, and accommodation availability are
  adapter boundaries only; no network calls occur in the core experience.
- Geographic clusters are read from Phase 1 if already computed; this Explorer
  does not re-cluster or modify saved pins.

## Tests

```bash
python -m pytest travel/tests/test_travel_atlas.py travel/tests/test_personalized_explorer.py travel/tests/test_planning_engine.py travel/tests/test_planning_feedback.py travel/tests/test_command_center.py travel/tests/test_architecture_foundation.py -v
```

Health content is general educational information only. It must show its source
and retrieval date; users should verify current official and clinician guidance
that applies to their personal travel.
