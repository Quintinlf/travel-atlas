"""
Phase 1 — Streamlit web dashboard.

Tabs:
  1. Dashboard   — key stats + top destinations + list breakdown
  2. Map         — interactive Folium map of all pins
  3. Clusters    — cluster map + ranked cluster list
  4. Raw Data    — searchable table with CSV export

Run with:
    streamlit run travel/src_phase1/app_streamlit.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the src_phase1 package importable when running via `streamlit run`
_HERE = Path(__file__).parent
_TRAVEL = _HERE.parent
if str(_TRAVEL) not in sys.path:
    sys.path.insert(0, str(_TRAVEL))
if str(_TRAVEL.parent) not in sys.path:
    sys.path.insert(0, str(_TRAVEL.parent))

import json
import tempfile
import zipfile
from typing import List

import folium
import pandas as pd
import plotly.express as px
import streamlit as st
from streamlit_folium import st_folium

from src_phase1.clustering import ClusterConfig, PinClusterer
from src_phase1.geo_grouping import WEST_EUROPE_FIT_BOUNDS, world_map_view
from src_phase1.insights import (
    BOOST_DEFAULT,
    BOOST_MAX,
    BOOST_MIN,
    DestinationInsights,
)
from src_phase1.map_media import pin_popup_image_html
from src_phase1.models import SavedLocation
from src_phase1.pin_repository import PinRepository
from src_phase1.takeout_parser import TakeoutParser, check_takeout_completeness

# ------------------------------------------------------------------ #
# Constants                                                            #
# ------------------------------------------------------------------ #

DB_PATH = _TRAVEL / "travel_pins.db"

_LIST_COLORS = {
    "Saved Places":   "#2196F3",
    "Want To Go":     "#FF9800",
    "Reviews":        "#4CAF50",
    "Starred Places": "#FFD700",
    "Labeled Places": "#9C27B0",
}
_DEFAULT_COLOR = "#607D8B"

# ------------------------------------------------------------------ #
# Page config                                                          #
# ------------------------------------------------------------------ #

st.set_page_config(
    page_title="Travel Pin Intelligence",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ------------------------------------------------------------------ #
# Cached helpers                                                       #
# ------------------------------------------------------------------ #

_CACHE_VERSION = "2026-07-24-region-v2"


@st.cache_resource
def get_repo() -> PinRepository:
    _ = _CACHE_VERSION
    return PinRepository(DB_PATH)


@st.cache_data(ttl=5)
def load_pins() -> List[SavedLocation]:
    _ = _CACHE_VERSION
    return get_repo().get_all_pins()


@st.cache_data(ttl=5)
def load_stats() -> dict:
    _ = _CACHE_VERSION
    return get_repo().get_stats()


def _invalidate_caches() -> None:
    load_pins.clear()
    load_stats.clear()


# ------------------------------------------------------------------ #
# Sidebar — import controls                                            #
# ------------------------------------------------------------------ #

def render_sidebar() -> None:
    st.sidebar.title("🗺️ Travel Pins")
    st.sidebar.markdown("---")

    st.sidebar.subheader("Import Takeout Data")

    with st.sidebar.expander("How to export ALL saved pins", expanded=False):
        st.markdown("""
Google splits your saved pins across **two Takeout categories**:

1. **Maps (your places)** — Reviews, Labeled places, Saved Places.json (often only ~8–40 pins)
2. **Saved** — Want to go, Favorites, Starred, **every custom list** (CSV, one file per list)

Your map with 70+ green flags / stars is mostly in **Saved**, not Maps.

**Steps:**
1. Go to [takeout.google.com](https://takeout.google.com)
2. Deselect all → select **Maps** AND **Saved**
3. Export as ZIP → upload here

Refs: [Takeout JSON vs CSV guide](https://www.takeout-tools.com/blog/google-takeout-saved-places-json-vs-csv), [ruk.ca on Starred vs Want to go](https://ruk.ca/content/google-maps-warning-want-go-and-starred-places-are-not-same)
        """)

        takeout_dir = _TRAVEL / "Takeout"
        if takeout_dir.exists():
            comp = check_takeout_completeness(takeout_dir)
            if comp["likely_incomplete"]:
                st.warning(comp["hint"])
            else:
                st.success(comp["hint"])

    uploaded = st.sidebar.file_uploader(
        "Upload Google Takeout ZIP or JSON",
        type=["zip", "json"],
        help="Export your Google Maps data from myaccount.google.com/data-and-privacy → Download your data",
    )

    col1, col2 = st.sidebar.columns(2)
    do_import = col1.button("📥 Import", use_container_width=True)
    do_sample = col2.button("🧪 Load Sample", use_container_width=True)

    if do_sample:
        _load_sample_data()

    if do_import and uploaded is not None:
        _import_uploaded_file(uploaded)

    st.sidebar.markdown("---")
    st.sidebar.subheader("Clustering")

    threshold = st.sidebar.slider(
        "Distance threshold (km)",
        min_value=1.0,
        max_value=100.0,
        value=15.0,
        step=1.0,
        help="Pins within this distance of each other are grouped into one cluster.",
    )

    if st.sidebar.button("🔄 Re-cluster", use_container_width=True):
        _recluster(threshold)

    st.sidebar.markdown("---")

    if st.sidebar.button("🗑️ Reset Database", use_container_width=True, type="secondary"):
        if st.session_state.get("confirm_reset"):
            get_repo().delete_all_pins()
            _invalidate_caches()
            st.session_state["confirm_reset"] = False
            st.sidebar.success("Database cleared.")
        else:
            st.session_state["confirm_reset"] = True
            st.sidebar.warning("Click Reset again to confirm.")


def _import_uploaded_file(uploaded) -> None:
    parser = TakeoutParser()
    repo = get_repo()

    with tempfile.NamedTemporaryFile(
        suffix=Path(uploaded.name).suffix, delete=False
    ) as tmp:
        tmp.write(uploaded.read())
        tmp_path = Path(tmp.name)

    with st.sidebar:
        with st.spinner("Importing…"):
            if tmp_path.suffix.lower() == ".zip":
                locations = parser.parse_zip(tmp_path)
            else:
                locations = parser.parse_file(tmp_path)

            inserted = repo.insert_pins_batch(locations)
            removed = repo.deduplicate()
            _recluster(15.0)
            _invalidate_caches()

    tmp_path.unlink(missing_ok=True)
    st.session_state["last_import_report"] = parser.last_report.to_dict()
    st.session_state["last_dedup_removed"] = removed

    report = parser.last_report
    if locations:
        st.sidebar.success(
            f"Imported {inserted} pins ({removed} duplicates removed). "
            f"Raw records: {report.total_raw_records}, "
            f"parsed: {report.total_imported}, "
            f"dropped: {sum(report.drops_by_reason.values())}."
        )
    else:
        st.sidebar.warning(
            "No pins found. Open the **Data Debug** tab for drop reasons."
        )
    if parser.errors:
        with st.sidebar.expander("Import warnings"):
            for e in parser.errors[:20]:
                st.text(e)


def _load_sample_data() -> None:
    fixture_dir = Path(__file__).parent.parent / "fixtures" / "sample_takeout"
    if not fixture_dir.exists():
        st.sidebar.error("Sample fixture directory not found.")
        return

    parser = TakeoutParser()
    repo = get_repo()

    with st.sidebar:
        with st.spinner("Loading sample data…"):
            locations = parser.parse_directory(fixture_dir)
            inserted = repo.insert_pins_batch(locations)
            removed = repo.deduplicate()
            _recluster(15.0)
            _invalidate_caches()

    st.sidebar.success(
        f"Loaded {inserted} sample pins ({removed} duplicates removed)."
    )
    st.session_state["last_import_report"] = parser.last_report.to_dict()
    st.session_state["last_dedup_removed"] = removed


def _recluster(threshold_km: float) -> None:
    repo = get_repo()
    pins = repo.get_pins_with_coords()
    clusterer = PinClusterer(ClusterConfig(distance_threshold_km=threshold_km))
    clusters = clusterer.cluster_pins(pins)
    repo.save_clusters(clusters)
    _invalidate_caches()


# ------------------------------------------------------------------ #
# Tab 1 — Dashboard                                                    #
# ------------------------------------------------------------------ #

def _render_place_browser(counts: dict, *, noun: str, singular: str, icon: str) -> None:
    """Popover listing every saved place behind a metric, A–Z.

    ``counts`` arrives keyed by the raw column value, so names are folded on their
    stripped form first — otherwise "Japan" and "Japan " list as two entries.
    """
    merged: dict = {}
    for name, count in counts.items():
        cleaned = (name or "").strip()
        if cleaned:
            merged[cleaned] = merged.get(cleaned, 0) + count

    label = f"Browse {len(merged)} {noun}"
    with st.popover(label, icon=icon, width="stretch", disabled=not merged):
        query = st.text_input(
            f"Filter {noun}",
            key=f"filter_{noun}",
            placeholder=f"Search {noun}…",
            label_visibility="collapsed",
        )
        names = sorted(merged, key=str.casefold)
        if query:
            names = [name for name in names if query.casefold() in name.casefold()]
        if not names:
            st.caption(f"No {noun} match “{query}”.")
            return
        st.dataframe(
            pd.DataFrame({singular: names, "Pins": [merged[n] for n in names]}),
            hide_index=True,
            height=min(400, 36 + 35 * len(names)),
            width="stretch",
        )


def _render_boost_controls(signals: List[dict], boosts: dict) -> None:
    """Per-destination multipliers for when the computed score disagrees with you."""
    with st.expander("⚖️ Adjust destination weighting", expanded=False):
        st.caption(
            f"Multiplies the computed score ({BOOST_MIN}–{BOOST_MAX}). "
            "Leave at 1.0 to rank purely on your notes."
        )
        with st.form("destination_boosts", border=False):
            pending = {}
            for signal in signals:
                destination = signal["destination"]
                pending[destination] = st.slider(
                    destination,
                    min_value=BOOST_MIN,
                    max_value=BOOST_MAX,
                    value=float(boosts.get(destination, BOOST_DEFAULT)),
                    step=0.25,
                    key=f"boost_{destination}",
                )
            submitted = st.form_submit_button(
                "Save weighting", icon=":material/save:"
            )

        if submitted:
            repo = get_repo()
            for destination, boost in pending.items():
                repo.set_destination_boost(destination, boost)
            _invalidate_caches()
            st.rerun()


def render_dashboard(pins: List[SavedLocation], stats: dict) -> None:
    st.header("📊 Dashboard")

    if not pins:
        st.info("No pins loaded yet. Use the sidebar to import Takeout data or load the sample.")
        return

    # Key metrics row
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Pins", stats["total"])
    c2.metric("Cities", len(stats["by_city"]))
    with c2:
        _render_place_browser(
            stats["by_city"],
            noun="cities",
            singular="City",
            icon=":material/location_city:",
        )
    c3.metric("Countries", len(stats["by_country"]))
    with c3:
        _render_place_browser(
            stats["by_country"],
            noun="countries",
            singular="Country",
            icon=":material/public:",
        )
    c4.metric("Lists", len(stats["by_list"]))
    boosts = get_repo().get_destination_boosts()
    ratings = get_repo().get_country_ratings()
    # One-time seed so UK / FR / ES / PT float to the top until you customize.
    if not ratings:
        for seed_name, seed_rating in (
            ("England (UK)", 5),
            ("Scotland (UK)", 5),
            ("Ireland", 5),
            ("France", 5),
            ("Spain", 4),
            ("Portugal", 4),
        ):
            get_repo().set_country_rating(seed_name, seed_rating)
        ratings = get_repo().get_country_ratings()
    insights = DestinationInsights(pins, boosts=boosts, country_ratings=ratings)
    istat = insights.get_statistics()
    c5.metric("Avg Pins / City", f"{istat['avg_pins_per_city']:.1f}")

    with st.expander("Rate countries / UK nations", expanded=False):
        st.caption(
            "Personal 1–5 ratings reorder Top Countries (rating first, then pin count). "
            "Republic of Ireland stays separate from the UK."
        )
        from src_phase1.geo_grouping import destination_label, top_level_destination

        destinations = sorted(
            {
                destination_label(*top_level_destination(pin))
                for pin in pins
            }
        )
        with st.form("country_ratings"):
            pending_ratings = {}
            for dest in destinations[:40]:
                pending_ratings[dest] = st.select_slider(
                    dest,
                    options=[0, 1, 2, 3, 4, 5],
                    value=int(ratings.get(dest) or ratings.get(dest.split(" (")[0]) or 0),
                    format_func=lambda v: "—" if v == 0 else "★" * v,
                    key=f"rate_{dest}",
                )
            if st.form_submit_button("Save ratings"):
                for dest, value in pending_ratings.items():
                    get_repo().set_country_rating(dest, None if value == 0 else value)
                _invalidate_caches()
                st.rerun()

    st.markdown("---")

    col_left, col_right = st.columns([3, 2])

    with col_left:
        st.subheader("🏆 Top Destinations")
        signals = insights.get_destination_signals(n=15)
        if signals:
            df_top = pd.DataFrame(signals).rename(
                columns={
                    "destination": "Destination",
                    "score": "Score",
                    "pin_count": "Pins",
                    "note_lines": "Note lines",
                    "annotated_pins": "Annotated pins",
                    "cities": "Cities",
                    "boost": "Boost",
                }
            )
            fig = px.bar(
                df_top,
                x="Score",
                y="Destination",
                orientation="h",
                color="Note lines",
                color_continuous_scale="Blues",
                text="Note lines",
                labels={"Score": "Interest Score", "Destination": ""},
                hover_data=["Pins", "Annotated pins", "Cities", "Boost"],
            )
            fig.update_layout(
                height=max(300, len(signals) * 28),
                yaxis={"categoryorder": "total ascending"},
                margin=dict(l=0, r=10, t=20, b=0),
                coloraxis_showscale=False,
            )
            fig.update_traces(textposition="outside")
            st.plotly_chart(fig, use_container_width=True)
            st.caption(
                "Scored on how much you wrote about a place — the number on each bar is "
                "lines of your own notes. Raw pin count is not a factor; hover for it."
            )
            _render_boost_controls(signals, boosts)

    with col_right:
        st.subheader("⭐ Rated tiers")
        rated_rows = []
        for dest, count in insights.get_top_countries(n=20):
            rating = int(ratings.get(dest) or ratings.get(dest.split(" (")[0]) or 0)
            tier = {5: "Must go", 4: "High want", 3: "Interested", 2: "Maybe", 1: "Low"}.get(
                rating, "Unrated"
            )
            rated_rows.append({"Destination": dest, "Rating": rating, "Tier": tier, "Pins": count})
        if rated_rows:
            st.dataframe(pd.DataFrame(rated_rows), hide_index=True, width="stretch")

        st.subheader("🌍 Top Countries (rating → pins)")
        top_countries = insights.get_top_countries(n=8)
        if top_countries:
            df_countries = pd.DataFrame(top_countries, columns=["Country", "Pins"])
            fig3 = px.bar(
                df_countries,
                x="Pins",
                y="Country",
                orientation="h",
                color="Pins",
                color_continuous_scale="Greens",
                text="Pins",
            )
            fig3.update_layout(
                height=max(200, len(top_countries) * 30),
                yaxis={"categoryorder": "total ascending"},
                margin=dict(l=0, r=10, t=20, b=0),
                coloraxis_showscale=False,
            )
            fig3.update_traces(textposition="outside")
            st.plotly_chart(fig3, use_container_width=True)


# ------------------------------------------------------------------ #
# Tab 2 — Map                                                          #
# ------------------------------------------------------------------ #

def render_map(pins: List[SavedLocation]) -> None:
    st.header("🗺️ Pin Map")

    geo_pins = [p for p in pins if p.latitude != 0 or p.longitude != 0]
    if not geo_pins:
        st.info("No pins with coordinates to display.")
        return

    st.caption(f"{len(geo_pins):,} pins with coordinates.")
    show_all = st.checkbox(
        "Show all pins worldwide",
        value=False,
        key="pin-intel-show-all-pins",
        help="Default camera is West Europe so Kazakhstan/Japan pins don't steal the view.",
    )
    coords = [(p.latitude, p.longitude) for p in geo_pins]
    avg_lat, avg_lng, zoom, plot_coords = world_map_view(coords, show_all=show_all)
    plot_set = set(plot_coords)
    plot_pins = (
        geo_pins if show_all else [p for p in geo_pins if (p.latitude, p.longitude) in plot_set]
    )
    st.caption(f"Showing {len(plot_pins):,} pins on this view.")

    m = folium.Map(location=[avg_lat, avg_lng], zoom_start=zoom, tiles="CartoDB positron")
    if not show_all:
        m.fit_bounds(list(WEST_EUROPE_FIT_BOUNDS))

    for pin in plot_pins[:10_000]:
        color = _LIST_COLORS.get(pin.list_name, _DEFAULT_COLOR)
        popup_html = (
            f"<b>{pin.name}</b><br>"
            f"<i>{pin.list_name}</i><br>"
            + (f"{pin.city}, {pin.country}<br>" if pin.city else "")
            + (f"<small>{pin.notes[:120]}</small>" if pin.notes else "")
            + pin_popup_image_html(pin)
        )
        folium.CircleMarker(
            location=[pin.latitude, pin.longitude],
            radius=5,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.7,
            popup=folium.Popup(popup_html, max_width=250),
            tooltip=pin.name,
        ).add_to(m)

    # Legend
    legend_html = """
    <div style="position:fixed;bottom:30px;left:30px;z-index:1000;
                background:white;padding:10px;border-radius:8px;
                box-shadow:2px 2px 6px rgba(0,0,0,.3);font-size:13px;">
    """
    for list_name, color in _LIST_COLORS.items():
        legend_html += (
            f'<div style="margin:2px 0">'
            f'<span style="display:inline-block;width:12px;height:12px;'
            f'background:{color};border-radius:50%;margin-right:6px;"></span>'
            f"{list_name}</div>"
        )
    legend_html += "</div>"
    m.get_root().html.add_child(folium.Element(legend_html))

    st_folium(m, height=600, use_container_width=True)


# ------------------------------------------------------------------ #
# Tab 3 — Clusters                                                     #
# ------------------------------------------------------------------ #

def render_clusters(pins: List[SavedLocation]) -> None:
    st.header("📍 Destination Clusters")

    repo = get_repo()
    cluster_rows = repo.load_clusters()

    if not cluster_rows:
        st.info("No clusters computed yet. Click **Re-cluster** in the sidebar.")
        return

    st.caption(f"{len(cluster_rows)} clusters found.")

    col_map, col_list = st.columns([3, 2])

    with col_map:
        show_all = st.checkbox(
            "Show all clusters worldwide",
            value=False,
            key="pin-intel-clusters-show-all",
        )
        cluster_coords = [
            (c["centroid_lat"], c["centroid_lng"])
            for c in cluster_rows
            if c.get("centroid_lat") is not None and c.get("centroid_lng") is not None
        ]
        avg_lat, avg_lng, zoom, plot_coords = world_map_view(
            cluster_coords, show_all=show_all
        )
        plot_set = set(plot_coords)
        plot_clusters = (
            cluster_rows
            if show_all
            else [
                c
                for c in cluster_rows
                if (c.get("centroid_lat"), c.get("centroid_lng")) in plot_set
            ]
        )
        m = folium.Map(location=[avg_lat, avg_lng], zoom_start=zoom, tiles="CartoDB positron")
        if not show_all:
            m.fit_bounds(list(WEST_EUROPE_FIT_BOUNDS))

        max_pins = max((c["pin_count"] for c in plot_clusters), default=1)
        for cl in plot_clusters:
            radius = 6 + (cl["pin_count"] / max_pins) * 20
            label = cl["city"] or cl["name"]
            popup_html = (
                f"<b>{label}</b><br>"
                f"{cl['pin_count']} pins<br>"
                + (f"{cl['country']}" if cl.get("country") else "")
            )
            folium.CircleMarker(
                location=[cl["centroid_lat"], cl["centroid_lng"]],
                radius=radius,
                color="#E91E63",
                fill=True,
                fill_color="#E91E63",
                fill_opacity=0.6,
                popup=folium.Popup(popup_html, max_width=200),
                tooltip=f"{label} ({cl['pin_count']} pins)",
            ).add_to(m)

        st_folium(m, height=500, use_container_width=True)

    with col_list:
        st.subheader("Cluster Rankings")
        df_cl = pd.DataFrame(cluster_rows)[
            ["name", "city", "country", "pin_count", "centroid_lat", "centroid_lng"]
        ].rename(
            columns={
                "name": "Name",
                "city": "City",
                "country": "Country",
                "pin_count": "Pins",
                "centroid_lat": "Lat",
                "centroid_lng": "Lng",
            }
        )
        df_cl["Lat"] = df_cl["Lat"].round(3)
        df_cl["Lng"] = df_cl["Lng"].round(3)
        st.dataframe(df_cl, use_container_width=True, hide_index=True)


# ------------------------------------------------------------------ #
# Tab 4 — Raw Data                                                     #
# ------------------------------------------------------------------ #

def render_raw_data(pins: List[SavedLocation]) -> None:
    st.header("🔍 Raw Data")

    if not pins:
        st.info("No pins loaded.")
        return

    df = pd.DataFrame([p.to_dict() for p in pins])
    display_cols = ["name", "city", "country", "list_name", "category", "notes",
                    "latitude", "longitude", "source_file", "imported_at"]
    df_display = df[[c for c in display_cols if c in df.columns]]

    # Filters
    c1, c2, c3 = st.columns(3)
    filter_city = c1.text_input("Filter by city")
    filter_list = c2.selectbox("Filter by list", ["All"] + sorted(df["list_name"].unique().tolist()))
    filter_name = c3.text_input("Search name")

    mask = pd.Series([True] * len(df_display))
    if filter_city:
        mask &= df_display["city"].fillna("").str.contains(filter_city, case=False)
    if filter_list != "All":
        mask &= df_display["list_name"] == filter_list
    if filter_name:
        mask &= df_display["name"].str.contains(filter_name, case=False)

    filtered = df_display[mask]
    st.caption(f"Showing {len(filtered):,} of {len(df):,} pins.")
    st.dataframe(filtered, use_container_width=True, hide_index=True)

    csv = filtered.to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️ Export filtered data to CSV",
        data=csv,
        file_name="travel_pins.csv",
        mime="text/csv",
    )


# ------------------------------------------------------------------ #
# Tab 5 — Data Debug Panel                                             #
# ------------------------------------------------------------------ #

def render_debug_panel() -> None:
    st.header("🔬 Data Debug Panel")
    st.caption("Shows what was parsed, imported, and dropped during the last Takeout import.")

    takeout_dir = _TRAVEL / "Takeout"
    if takeout_dir.exists():
        st.subheader("Takeout completeness check (local folder)")
        comp = check_takeout_completeness(takeout_dir)
        c1, c2, c3 = st.columns(3)
        c1.metric("Saved Places.json", "✓" if comp["has_saved_places_json"] else "✗")
        c2.metric("Want to go.csv", "✓" if comp["has_want_to_go_csv"] else "✗")
        c3.metric("Starred CSV", "✓" if comp["has_starred_csv"] else "✗")
        if comp["likely_incomplete"]:
            st.error(comp["hint"])
        else:
            st.success(comp["hint"])
        if comp["saved_csv_lists"]:
            st.write("Saved CSV lists found:", ", ".join(comp["saved_csv_lists"]))

    report = st.session_state.get("last_import_report")
    if not report:
        st.info("No import has been run yet. Upload a Takeout ZIP via the sidebar, then return here.")
        if (_TRAVEL / "Takeout").exists():
            if st.button("Run diagnostic import on local Takeout/ folder"):
                parser = TakeoutParser()
                with st.spinner("Parsing local Takeout…"):
                    locs = parser.parse_directory(_TRAVEL / "Takeout")
                st.session_state["last_import_report"] = parser.last_report.to_dict()
                st.session_state["last_dedup_removed"] = 0
                st.rerun()
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Raw records seen", report.get("total_raw_records", 0))
    c2.metric("Records imported", report.get("total_imported", 0))
    dropped = sum(report.get("drops_by_reason", {}).values())
    c3.metric("Records dropped", dropped)
    c4.metric("Dedup removed", st.session_state.get("last_dedup_removed", 0))

    st.subheader("ZIP / source summary")
    st.json({
        "source": report.get("source"),
        "zip_total_entries": report.get("zip_total_entries"),
        "json_files_matched": report.get("json_files_matched"),
        "json_files_parsed": report.get("json_files_parsed"),
        "json_files_failed": report.get("json_files_failed"),
        "csv_files_matched": report.get("csv_files_matched", 0),
        "csv_files_parsed": report.get("csv_files_parsed", 0),
        "non_json_skipped": report.get("non_json_skipped"),
    })

    st.subheader("Dropped records breakdown")
    drops = report.get("drops_by_reason", {})
    if drops:
        df_drops = pd.DataFrame(
            [{"Reason": k, "Count": v} for k, v in sorted(drops.items(), key=lambda x: -x[1])]
        )
        st.dataframe(df_drops, use_container_width=True, hide_index=True)
        st.bar_chart(df_drops.set_index("Reason"))
    else:
        st.success("No records were dropped during the last import.")

    st.subheader("Per-file contribution")
    files = report.get("files", [])
    if files:
        df_files = pd.DataFrame([
            {
                "File": f["path"],
                "Records seen": f["records_seen"],
                "Imported": f["records_imported"],
                "Drops": len(f.get("drops", [])),
                "Parse error": f.get("parse_error") or "",
            }
            for f in sorted(files, key=lambda x: -x.get("records_imported", 0))
        ])
        st.dataframe(df_files, use_container_width=True, hide_index=True)

        with st.expander("Drop details (first 100 per file)"):
            for f in files:
                if f.get("drops"):
                    st.markdown(f"**{f['path']}**")
                    for d in f["drops"][:100]:
                        st.text(f"  [{d['reason']}] {d.get('detail', '')[:120]}")
    else:
        st.warning("No file-level detail available.")

    st.subheader("Full report (copyable JSON)")
    st.code(json.dumps(report, indent=2, ensure_ascii=False), language="json")


# ------------------------------------------------------------------ #
# Main                                                                 #
# ------------------------------------------------------------------ #

def main() -> None:
    render_sidebar()

    pins = load_pins()
    stats = load_stats()

    with st.sidebar.expander("Filter by saved trip", expanded=False):
        st.caption("Show pin counts for a trip (UK nations split; Ireland separate).")
        try:
            from travel_atlas.database import AtlasDatabase
            from travel_atlas.repository import AtlasRepository
            from travel_atlas.services.destination_itinerary import DestinationItineraryService
            from travel_atlas.services.itinerary_service import ItineraryService
            from travel_atlas.services.pin_service import PinService
            from travel_atlas.services.trip_service import TripPlanService
            from src_phase1.geo_grouping import destination_matches, trip_pin_stats

            atlas_db = AtlasDatabase(_TRAVEL / "atlas.db")
            atlas_db.migrate()
            repo = AtlasRepository(atlas_db)
            pin_svc = PinService(_TRAVEL / "travel_pins.db", atlas_database_path=_TRAVEL / "atlas.db")
            itinerary = DestinationItineraryService(pin_svc, ItineraryService(pin_svc))
            trips = TripPlanService(repo, itinerary).list_trips()
            if trips:
                trip_id = st.selectbox(
                    "Trip",
                    [t["id"] for t in trips],
                    format_func=lambda tid: next(
                        t["name"] for t in trips if t["id"] == tid
                    ),
                    key="pin_intel_trip_filter",
                )
                trip = TripPlanService(repo, itinerary).get_trip(trip_id)
                trip_pins = []
                for destination in trip.get("destinations") or []:
                    kind = destination.get("destination_kind") or destination.get("kind")
                    label = destination.get("destination_label") or destination.get("label")
                    if not kind or not label:
                        continue
                    trip_pins.extend(
                        p for p in pins if destination_matches(p, kind, label)
                    )
                stats_trip = trip_pin_stats(trip_pins)
                st.markdown(f"**{stats_trip['total']} pins** in this trip")
                for name, count in stats_trip["by_destination"].items():
                    st.caption(f"{name}: {count}")
            else:
                st.caption("No saved trips yet — create one in Trip Planner.")
        except Exception as exc:  # noqa: BLE001 — sidebar should not crash the page
            st.caption(f"Trip filter unavailable: {exc}")

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 Dashboard", "🗺️ Map", "📍 Clusters", "🔍 Raw Data", "🔬 Data Debug",
    ])

    with tab1:
        render_dashboard(pins, stats)
    with tab2:
        render_map(pins)
    with tab3:
        render_clusters(pins)
    with tab4:
        render_raw_data(pins)
    with tab5:
        render_debug_panel()


if __name__ == "__main__":
    main()
