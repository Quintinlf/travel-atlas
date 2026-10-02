# Travel Atlas

An offline-first travel planning system built around a simple idea: **a recommendation
you can't trace to a source isn't worth showing.**

It ingests your own Google Maps saved places, clusters them into destinations, builds a
sourced knowledge base about those places, and plans trips against what you actually
like — with every factual claim carrying the text it came from and a human approval
behind it.

Python · SQLite · Streamlit · **265 passing tests**

---

## Why it exists

Booking sites optimize for the booking. I wanted a planner that optimized for *maximum
personal joy per dollar* — one that knew I'd already saved 577 places across three
continents and could reason about them.

That turned into a harder and more interesting problem than the UI suggests: where does
travel knowledge come from, how do you keep a language model from inventing it, and what
should the system do when a price feed returns nothing?

---

## The parts worth reviewing

### 1. Provider integrations that degrade honestly

`travel_atlas/providers/` wraps real travel APIs — **Amadeus** (GDS hotel search),
**Aviasales** (flights), **Nuitée / LiteAPI** (hotel rates), Open-Meteo, NOAA space
weather, US State Department advisories — behind one `Provider` protocol returning a
uniform `StubResult`.

Every provider answers the same way whether it's configured or not. A missing credential
or an empty upstream is a **first-class result**, not an exception and never a guess:

```json
{
  "ok": true,
  "fare_source": null,
  "message": "No cached Aviasales fares for this route — open Kayak or Google Flights for live quotes.",
  "fares": [],
  "cheapest": null,
  "links": { "kayak": "https://…", "google_flights": "https://…" }
}
```

`fairbanks_price_snapshot.json` in the repo root is a real captured run of exactly this:
the flight feed had nothing, so the system said so and handed back search links. It never
fabricates a fare. For anything that touches money or safety, "I don't know, here's where
to look" is the correct answer, and the type system makes it the easy one to write.

### 2. A knowledge pipeline with enforced provenance

```
pins → geo_area rows → coverage gaps → Wikivoyage/Wikipedia text → drafts → human review
```

`travel_atlas/ingest/` turns a coverage ruleset into a worklist, fetches article text,
stores it **verbatim** in `source_record`, and asks a model to report only what that text
supports. A topic the article doesn't cover is recorded as a gap rather than guessed at.

Every extracted claim lands as `review_status='draft'` — invisible to coverage scoring
until a human approves it in the Knowledge Review page, where each draft is shown beside
the quote it came from, so review is a comparison rather than a memory test. **Health,
safety and legal claims are excluded from bulk approval by design.** Runs are resumable:
`ingest_attempt` logs every (area, topic) pair tried, including the barren ones.

`python -m travel_atlas.ingest gaps` touches no network at all — it prints what's missing
and what filling it would cost, before anything is fetched.

### 3. A lifecycle gated on a real-world event

Trips move `Idea → Planning → Committed → Preparation → Traveling → Completed → Remembered`.

Commitment is **purchase-gated**: the first `reservation` of kind `hotel` or `flight`
reaching status `reserved` is what sets `committed_at`. Nothing else can. Dates then
refine the stage inside that gate — preparation bands at 90/60/30/7 days out, and
`traveling` triggers automatically when today falls between departure and return.

Reservations are a first-class table with their own state machine
(`not_available → available_soon → book_now → reserved → completed / cancelled`) rather
than a field buried in a logistics blob, because what a traveler needs to *do* next is
almost always a function of reservation state.

### 4. A planning engine that is strictly read-only

`travel_atlas/planning/` scores candidate places against saved pins, an expandable
preference profile, trip constraints, and category weights learned from your own
ratings. It never mutates knowledge tables — feedback writes to `recommendation_rating`,
and the engine reads.

The exploration mix defaults to **90% personalized / 10% discovery**, because a planner
that only shows you what you already like is a mirror, not a guide. Weekly day themes
give itineraries rhythm (Body & Nourishment on Monday, the Major Day on Saturday) and are
overridable per trip.

---

## Architecture

| Layer | Path | Role |
|---|---|---|
| Pin intelligence | `src_phase1/` | Google Takeout import → normalize → cluster → score |
| Knowledge | `travel_atlas/ingest/`, `knowledge_service` | Sourced claims, coverage rules, review queue |
| Providers | `travel_atlas/providers/` | Flights, hotels, weather, safety, transit, calendar |
| Services | `travel_atlas/services/` | Trips, reservations, budget, logistics, prep, itineraries |
| Planning | `travel_atlas/planning/` | Read-only scoring, learning, explanations |
| UI | `app_home.py` + `*_streamlit.py` | Research / Planning / Active Trip / Archive modes |

Two SQLite databases, deliberately separate: `travel_pins.db` (your imported pins, which
the Atlas only ever reads) and `atlas.db` (everything the system derives or stores).
Re-importing your pins can never be blocked by, or corrupt, derived state.

---

## Running it

```bash
pip install -r requirements.txt
streamlit run app_home.py
```

No API keys required. Unconfigured providers return labelled stub results, so the whole
app is explorable offline — click **Load Sample** to populate it with the synthetic pin
set in `fixtures/sample_takeout/` (London, Paris, Edinburgh, Rome, New York…).

To use your own data: export **Google Maps → Saved Places** from
[Google Takeout](https://takeout.google.com/) and upload the ZIP in the sidebar.

To enable live providers, set the keys named in `config/travel_config.yaml`
(`AMADEUS_CLIENT_ID`, `AMADEUS_CLIENT_SECRET`, …) in your environment or a `.env` file.

```bash
python -m pytest tests -q          # 265 tests, ~2 minutes
python -m travel_atlas.ingest gaps # coverage report, no network
```

---

## Scope and honesty

- **Providers are real integrations, not live production traffic.** Amadeus runs against
  its sandbox by default; several providers ship as labelled stubs with the interface
  settled and the call not wired. The repo distinguishes the two rather than blurring it.
- **Knowledge coverage is thin on purpose.** The schema was built for an encyclopedia; the
  seeded corpus covers a handful of areas. Growing it is a review-queue problem, and the
  queue is the feature.
- **Shopping and Astrology exist only as provider protocols** — extension points, not
  implementations.
- Personal data is not in this repository. Traveler profiles, passport fields and birth
  details are **demo values**; the author's own pin database and Google Takeout export are
  not published.

## License

MIT
