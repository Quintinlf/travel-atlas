# Phase 1 — Google Maps Pin Intelligence System

> Personal geospatial preference intelligence layer.  
> Import your Google Maps saved places → see where you care about most.

---

## What This Does

1. **Imports** your Google Maps saved places from a Takeout export (ZIP or JSON)
2. **Normalises** all pins into a unified SQLite database (`travel_pins.db`)
3. **Clusters** pins geographically into destinations (configurable radius)
4. **Scores** destinations by how many pins + list diversity + priority
5. **Visualises** everything in an interactive Streamlit web dashboard

**No external APIs.  No flights or hotels yet.  Just your data, clean and inspectable.**

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r travel/requirements.txt
```

### 2. Run the dashboard

```bash
cd travel_code
streamlit run travel/src_phase1/app_streamlit.py
```

Open `http://localhost:8501` in your browser.

### 3. Load sample data

Click **Load Sample** in the sidebar to see the system working immediately with
31 sample pins across London, Paris, Edinburgh, Dublin, Amsterdam, Rome,
New York, and Versailles.

### 4. Import your own Google Takeout

1. Go to [Google Takeout](https://takeout.google.com/)
2. Select only **Google Maps** → **Saved Places**
3. Download the ZIP
4. Upload it via the **Import Takeout Data** section in the sidebar

---

## Dashboard Overview

| Tab | What You See |
|-----|-------------|
| **Dashboard** | Total pins · top destinations (scored) · list breakdown · top countries |
| **Map** | Interactive pin map, colour-coded by list |
| **Clusters** | Geographic cluster map + ranked cluster list |
| **Raw Data** | Searchable table with CSV export |

---

## Running Tests

```bash
cd travel_code
python -m pytest travel/tests/test_phase1.py -v
```

Expected output: 30+ passing tests in < 5 seconds.

---

## Project Structure

```
travel/
├── src_phase1/
│   ├── models.py           # SavedLocation dataclass + SQLite schema
│   ├── takeout_parser.py   # Parse Takeout JSON (FeatureCollection, arrays, ZIP)
│   ├── pin_repository.py   # SQLite CRUD + geographic deduplication
│   ├── clustering.py       # Configurable distance-based clustering
│   ├── insights.py         # Destination scoring + statistics
│   └── app_streamlit.py    # Web dashboard (4 tabs)
├── tests/
│   └── test_phase1.py      # 30+ unit tests
├── fixtures/
│   └── sample_takeout/     # Sample JSON files for testing
│       ├── Saved Places.json
│       ├── Want to go.json
│       ├── Reviews.json
│       └── Labeled places.json
├── config/
│   └── clustering_config.yaml
├── requirements.txt
├── travel_pins.db          # Created at runtime
└── README_PHASE1.md        # This file
```

---

## Destination Scoring Formula

```
score(city) =
    0.50 × normalised_pin_count
  + 0.30 × normalised_avg_priority
  + 0.20 × normalised_list_diversity
```

All three components are min-max normalised to \[0, 1\] before weighting.
The final score is multiplied by 100 so it reads as "London: 87.3".

- **pin_count** — the primary signal: you explicitly saved these places
- **avg_priority** — default 5 (neutral), can be adjusted in the DB
- **list_diversity** — more lists mentioning a city = stronger interest

---

## Clustering

The default algorithm groups pins within **15 km** of each other into one destination cluster.

You can change the threshold using the sidebar slider — drag it and click **Re-cluster**.

| Threshold | Effect |
|-----------|--------|
| 1–5 km | Neighbourhood-level clusters |
| 10–20 km | City-level clusters (default) |
| 50–100 km | Regional clusters |

---

## Supported Takeout Formats

| File | Source Type |
|------|-------------|
| `Saved Places.json` | GeoJSON FeatureCollection |
| `Want to go.json` | JSON array |
| `Reviews.json` | JSON array with lat/lng |
| `Labeled places.json` | JSON array |
| `Starred places.json` | JSON array |
| Custom list JSONs | JSON array (uses filename as list name) |

The parser preserves **all original fields** in the `raw_json` column so no
data is ever lost during import.

---

## Deduplication

Two pins are considered duplicates when:
- They are within **100 metres** of each other, **and**
- They have the **same name** (case-insensitive)

The pin with richer data (longer notes, city/country filled in) is kept.
The threshold can be changed in `config/clustering_config.yaml`.

---

## What Comes Next (Phase 2)

Phase 2 will add:
- Trip builder: select N cities from your top destinations, allocate budget + days
- Route optimisation: compute best order to visit selected cities
- Cost estimation: rough flight + hotel cost ranges (no live APIs yet)

The database schema is already designed to support Phase 2 without migration.

---

## Troubleshooting

**Dashboard is blank after import**
→ Click **Re-cluster** in the sidebar to recompute clusters.

**"No pins with coordinates to display"**
→ The imported file may not contain lat/lng. Check that you downloaded
the correct Takeout category (Google Maps → Saved Places).

**Import warnings about malformed records**
→ These are logged and skipped. Your valid pins are still imported.
Use the **Raw Data** tab to inspect what was imported.

**streamlit-folium not found**
→ Run `pip install streamlit-folium folium` and restart.
