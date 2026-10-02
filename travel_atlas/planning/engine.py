"""Read-only PlanningEngine — central reasoning layer for travel recommendations.

Philosophy: maximize personal joy per dollar. Saved pins are the backbone;
hidden gems and wildcards augment, never replace them.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from typing import Any, Mapping, Sequence

from src_phase1.geo_grouping import destination_matches
from src_phase1.models import SavedLocation

from travel_atlas.services.destination_itinerary import DestinationItineraryService
from travel_atlas.services.knowledge_service import KnowledgeService
from travel_atlas.services.pin_service import PinService
from travel_atlas.services.planning_service import PlanningService
from travel_atlas.services.preferences_service import PreferencesService
from travel_atlas.services.types import (
    PlannerReport,
    Recommendation,
    TripDefinition,
    UserProfileView,
)

from .config import default_planning_config, load_planning_config
from .coverage import compute_coverage
from .estimates import (
    classify_tags_readonly,
    daily_budget_cap,
    estimate_cost,
    estimate_duration,
    packing_suggestions,
    primary_category,
)
from .explanations import build_match_breakdown, explain_recommendation
from .learning import merge_learned_weights
from .modules import Candidate, PlanningModule, default_modules
from .queries import QUESTION_KEYS
from .scoring import confidence_from_signals, score_batch, score_signals
from .signals import build_signal_vector, pin_priority_tier
from .themes import energy_fit, themes_for_trip


def profile_from_dict(user_key: str, raw: Mapping[str, Any]) -> UserProfileView:
    return UserProfileView(
        user_key=user_key,
        interests=tuple(raw.get("interests") or []),
        travel_style=str(raw.get("travel_style") or "balanced"),
        accommodation_preferences=dict(raw.get("accommodation_preferences") or {}),
        learning_goals=tuple(raw.get("learning_goals") or []),
        preferences=dict(raw.get("preferences") or {}),
    )


_TIER_ORDER = {"must_visit": 0, "interested": 1, "maybe": 2, "discovery": 3, "not_planned": 4}


class PlanningEngine:
    """Scores personalized recommendations. Does not open write transactions."""

    def __init__(
        self,
        *,
        pin_service: PinService,
        knowledge_service: KnowledgeService,
        preferences_service: PreferencesService,
        itinerary_service: DestinationItineraryService | None = None,
        planning_service: PlanningService | None = None,
        climate_service: Any | None = None,
        modules: Sequence[PlanningModule] | None = None,
        config: Mapping[str, Any] | None = None,
    ) -> None:
        self.pin_service = pin_service
        self.knowledge_service = knowledge_service
        self.preferences_service = preferences_service
        self.itinerary_service = itinerary_service
        self.planning_service = planning_service
        self.climate_service = climate_service
        self.modules = list(modules) if modules is not None else default_modules()
        self.config = dict(config) if config is not None else load_planning_config()

    @property
    def repository(self):
        return self.preferences_service.repository

    def plan(
        self,
        *,
        destination_kind: str,
        destination_label: str,
        trip: TripDefinition | None = None,
        user_key: str = "local-default",
    ) -> PlannerReport:
        trip_def = trip or TripDefinition(
            destination_kind=destination_kind,
            destination_label=destination_label,
        )
        energy = trip_def.energy or self.config.get("default_energy") or "medium"
        trip_def = TripDefinition(
            destination_kind=destination_kind,
            destination_label=destination_label,
            cities=trip_def.cities,
            start_date=trip_def.start_date,
            end_date=trip_def.end_date,
            day_count=trip_def.day_count,
            budget=trip_def.budget,
            transportation_preferences=trip_def.transportation_preferences,
            lodging_preferences=trip_def.lodging_preferences,
            travel_style=trip_def.travel_style,
            pace=trip_def.pace,
            energy=energy,
            theme_overrides=dict(trip_def.theme_overrides or {}),
        )
        profile = profile_from_dict(
            user_key, self.preferences_service.get_preferences(user_key)
        )
        pins = self._destination_pins(destination_kind, destination_label, trip_def.cities)
        area_id = self.knowledge_service.resolve_area_for_destination(
            destination_kind, destination_label
        )
        claims = self._reviewed_claims(area_id)
        rating_lookup = self.repository.get_rating_lookup(user_key)
        category_multipliers = self.repository.get_planning_weight_multipliers(user_key)

        start = date.fromisoformat(trip_def.start_date) if trip_def.start_date else None
        themes = themes_for_trip(start, trip_def.day_count)
        # Apply optional per-day overrides by day number.
        for theme_row in themes:
            override = (trip_def.theme_overrides or {}).get(theme_row["day"])
            if override:
                theme_row["theme_title"] = str(override)
                theme_row["theme_key"] = "override"

        candidates = self._build_candidates(pins, claims, destination_label)
        context: dict[str, Any] = {
            "all_candidates": candidates,
            "pins": pins,
            "claims": claims,
            "area_id": area_id,
            "themes": themes,
            "limit": int(self.config.get("max_recommendations_per_section") or 8),
        }
        for module in self.modules:
            for extra in module.contribute_candidates(
                trip=trip_def, profile=profile, context=context
            ):
                candidates.append(extra)

        recommendations = self._score_candidates(
            candidates,
            profile,
            trip_def,
            rating_lookup=rating_lookup,
            category_multipliers=category_multipliers,
            themes=themes,
        )
        # Drop hard skips from primary lists.
        active = [r for r in recommendations if r.user_rating != "skip"]
        skipped = [r for r in recommendations if r.user_rating == "skip"]

        mix = dict(self.config.get("exploration_mix") or {"personalized": 0.9, "discovery": 0.1})
        personalized, wildcards = self._split_exploration(active, mix)

        context["scored"] = personalized
        context["wildcards"] = wildcards
        context["itinerary_days"] = self._build_themed_itinerary(
            pins, personalized, trip_def, themes
        )
        context["budget"] = self._budget_summary(personalized, trip_def, profile)
        context["packing"] = self._packing(pins, trip_def, profile)
        context["planning_links"] = self._planning_links(pins, destination_label)
        context["food_subsystem"] = self._food_subsystem(personalized, claims, profile)

        sections: dict[str, Any] = {}
        for module in self.modules:
            sections[module.key] = module.build_section(
                recommendations=personalized,
                trip=trip_def,
                profile=profile,
                context=context,
            )

        experiences = sections["experiences"].recommendations
        food = sections["food"].recommendations
        museums = sections["museums"].recommendations
        transportation = sections["transportation"].recommendations
        skip = tuple(list(skipped) + self._skip_list(personalized))

        pin_backbone = self._pin_backbone(personalized)
        coverage = compute_coverage(personalized, profile)
        summary = self._summary(
            destination_label, profile, experiences, food, museums, trip_def, coverage
        )

        return PlannerReport(
            destination_kind=destination_kind,
            destination_label=destination_label,
            summary=summary,
            experiences=experiences,
            food=food,
            museums=museums,
            transportation=transportation,
            itinerary=tuple(context["itinerary_days"]),
            budget=dict(sections["budget"].payload or {}),
            packing=tuple(sections["packing"].payload.get("items") or []),
            skip=skip,
            area_id=area_id,
            coverage=coverage,
            themes=tuple(themes),
            wildcards=tuple(wildcards),
            food_subsystem=dict(context["food_subsystem"]),
            pin_backbone=tuple(pin_backbone),
            energy=energy,
            exploration_mix=mix,
        )

    def answer(
        self,
        question_key: str,
        *,
        destination_kind: str,
        destination_label: str,
        trip: TripDefinition | None = None,
        user_key: str = "local-default",
    ) -> Any:
        if question_key not in QUESTION_KEYS:
            raise ValueError(f"Unknown question key: {question_key}")
        report = self.plan(
            destination_kind=destination_kind,
            destination_label=destination_label,
            trip=trip,
            user_key=user_key,
        )
        mapping = {
            "what_to_do": report.experiences,
            "fit_interests": tuple(
                sorted(
                    report.experiences,
                    key=lambda r: r.signals.get("interest_tag_overlap", 0.0),
                    reverse=True,
                )
            ),
            "hidden_gems": tuple(
                sorted(
                    report.experiences,
                    key=lambda r: r.signals.get("hidden_gem", 0.0),
                    reverse=True,
                )[:5]
            ),
            "food": report.food,
            "museums": report.museums,
            "n_day_itinerary": report.itinerary,
            "what_to_skip": report.skip,
            "transportation": report.transportation,
            "budget": report.budget,
            "packing": report.packing,
            "coverage": report.coverage,
            "wildcards": report.wildcards,
        }
        return mapping.get(question_key, report)

    def _destination_pins(
        self,
        destination_kind: str,
        destination_label: str,
        cities: Sequence[str],
    ) -> list[SavedLocation]:
        pins = [
            pin
            for pin in self.pin_service.list_pins()
            if destination_matches(pin, destination_kind, destination_label)
        ]
        if cities:
            city_set = {c.lower() for c in cities}
            narrowed = [p for p in pins if (p.city or "").lower() in city_set]
            if narrowed:
                return narrowed
        return pins

    def _reviewed_claims(self, area_id: str | None) -> list[dict[str, Any]]:
        if not area_id:
            return []
        claims = self.knowledge_service.repository.list_claims(area_id)
        return [c for c in claims if c.get("review_status") == "reviewed"]

    def _build_candidates(
        self,
        pins: Sequence[SavedLocation],
        claims: Sequence[Mapping[str, Any]],
        destination_label: str,
    ) -> list[Candidate]:
        tag_counts: Counter[str] = Counter()
        pin_tags: dict[str, list[str]] = {}
        for pin in pins:
            tags = classify_tags_readonly(pin)
            pin_tags[pin.id] = tags
            for tag in tags:
                tag_counts[tag] += 1

        candidates: list[Candidate] = []
        for pin in pins:
            tags = pin_tags[pin.id]
            category = primary_category(tags)
            location = ", ".join(
                part for part in (pin.city, pin.country) if part
            ) or destination_label
            candidates.append(
                Candidate(
                    title=pin.name,
                    category=category,
                    location=location,
                    tags=tags,
                    pin_id=pin.id,
                    is_saved_pin=True,
                    peer_count=tag_counts[category],
                    pin=pin,
                )
            )

        for claim in claims:
            value = claim.get("value") or {}
            if isinstance(value, str):
                import json

                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    value = {"title": value, "body": ""}
            title = value.get("title") or claim.get("topic_key") or "Atlas note"
            topic = str(claim.get("topic_key") or "")
            category_key = str(claim.get("category_key") or "general_travel")
            tags = self._tags_for_claim(category_key, topic)
            category = primary_category(tags)
            if any(c.title.lower() == str(title).lower() for c in candidates):
                continue
            candidates.append(
                Candidate(
                    title=str(title),
                    category=category,
                    location=destination_label,
                    tags=tags,
                    claim_topics=[topic, category_key],
                    claim_id=str(claim.get("id") or ""),
                    is_saved_pin=False,
                    peer_count=tag_counts.get(category, 1),
                )
            )
        return candidates

    @staticmethod
    def _tags_for_claim(category_key: str, topic_key: str) -> list[str]:
        blob = f"{category_key} {topic_key}".lower()
        tags: list[str] = []
        mapping = [
            (("food", "cuisine", "dining", "market"), "market_food"),
            (("museum", "history", "heritage", "art", "culture"), "museum_history"),
            (("nature", "park", "outdoor", "hike"), "nature_gardens"),
            (("temple", "spiritual", "religion"), "temple_spirituality"),
            (("transport", "transit", "train", "getting_around"), "transport"),
            (("night", "bar"), "nightlife"),
            (("shop",), "shopping"),
        ]
        for terms, tag in mapping:
            if any(term in blob for term in terms):
                tags.append(tag)
        return tags or ["general_travel"]

    def _score_candidates(
        self,
        candidates: Sequence[Candidate],
        profile: UserProfileView,
        trip: TripDefinition,
        *,
        rating_lookup: Mapping[tuple[str, str], Mapping[str, Any]],
        category_multipliers: Mapping[str, float],
        themes: Sequence[Mapping[str, Any]],
    ) -> list[Recommendation]:
        if not candidates:
            return []
        base_weights = dict(
            self.config.get("weights") or default_planning_config()["weights"]
        )
        # Average theme for trip-level scoring (day-level applied in itinerary).
        avg_theme_cats: set[str] = set()
        theme_energy = trip.energy
        for row in themes:
            avg_theme_cats.update(row.get("categories") or [])
            theme_energy = row.get("energy") or theme_energy

        signal_rows: list[dict[str, float]] = []
        meta: list[Candidate] = []
        rating_meta: list[tuple[str | None, float | None, bool]] = []
        weight_rows: list[dict[str, float]] = []

        for candidate in candidates:
            rating_row = None
            if candidate.pin_id:
                rating_row = rating_lookup.get(("pin", candidate.pin_id))
            elif candidate.claim_id:
                rating_row = rating_lookup.get(("claim", candidate.claim_id))
            if rating_row is None:
                rating_row = rating_lookup.get(("title", candidate.title.lower()))

            rating_name = rating_row["rating"] if rating_row else None
            rating_score = float(rating_row["score"]) if rating_row else None
            is_skip = rating_name == "skip"

            # Theme fit vs union of trip themes (day-specific re-rank later).
            tf = 1.0 if candidate.category in avg_theme_cats else 0.4
            if not avg_theme_cats:
                tf = 0.5
            duration = estimate_duration(candidate.category, self.config)
            ef = energy_fit(duration, theme_energy, trip.pace)

            signals = build_signal_vector(
                tags=candidate.tags,
                category=candidate.category,
                pin=candidate.pin,
                profile=profile,
                trip=trip,
                config=self.config,
                claim_topics=candidate.claim_topics,
                peer_count=candidate.peer_count,
                is_saved_pin=candidate.is_saved_pin,
                theme_fit_value=tf,
                energy_fit_value=ef,
                rating_score=rating_score,
                is_skip=is_skip,
                wildcard=False,
            )
            weights = merge_learned_weights(
                base_weights, dict(category_multipliers), candidate.category
            )
            # Backbone: amplify saved pins so they outrank generic claims.
            if candidate.is_saved_pin:
                weights = dict(weights)
                weights["saved_pin_boost"] = weights.get("saved_pin_boost", 0.16) * 1.35
                weights["pin_affinity"] = weights.get("pin_affinity", 0.1) * 1.2

            signal_rows.append(signals)
            meta.append(candidate)
            rating_meta.append((rating_name, rating_score, is_skip))
            weight_rows.append(weights)

        # Score each row with its own (possibly learned) weights; batch variance
        # drop uses the first weight map for component selection.
        common_weights = weight_rows[0] if weight_rows else base_weights
        batch_scores = score_batch(signal_rows, common_weights)
        # Re-score with per-candidate learned weights for final ordering.
        scores = [
            score_signals(signals, w)
            for signals, w in zip(signal_rows, weight_rows)
        ]
        # Blend batch-normalized ranking with per-row learned score.
        scores = [
            round(0.5 * a + 0.5 * b, 1) for a, b in zip(batch_scores, scores)
        ]

        ranked: list[Recommendation] = []
        for candidate, signals, score, (rating_name, _rs, _skip) in sorted(
            zip(meta, signal_rows, scores, rating_meta),
            key=lambda item: (
                _TIER_ORDER.get(
                    pin_priority_tier(item[0].pin, item[3][0]), 3
                ),
                -item[2],
            ),
        ):
            duration = estimate_duration(candidate.category, self.config)
            cost = estimate_cost(candidate.category, self.config)
            nearby = 0
            if candidate.pin and candidate.is_saved_pin:
                nearby = max(0, candidate.peer_count - 1)
            breakdown = build_match_breakdown(
                signals,
                score=score,
                interests=profile.interests,
                nearby_pin_count=nearby,
            )
            explanation = explain_recommendation(
                title=candidate.title,
                signals=signals,
                interests=profile.interests,
                pace=trip.pace,
                match_breakdown=breakdown,
            )
            refs: dict[str, str] = {}
            if candidate.pin_id:
                refs["pin_id"] = candidate.pin_id
            if candidate.claim_id:
                refs["claim_id"] = candidate.claim_id
            tier = pin_priority_tier(candidate.pin, rating_name)
            ranked.append(
                Recommendation(
                    title=candidate.title,
                    category=candidate.category,
                    location=candidate.location,
                    estimated_duration_hours=duration,
                    estimated_cost=cost,
                    confidence=confidence_from_signals(signals, score),
                    explanation=explanation,
                    score=score,
                    signals=signals,
                    source_refs=refs,
                    match_breakdown=breakdown,
                    priority_tier=tier,
                    user_rating=rating_name,
                    joy_per_dollar=round(signals.get("joy_per_dollar", 0) * 100, 1),
                )
            )
        return ranked

    def _split_exploration(
        self, recommendations: Sequence[Recommendation], mix: Mapping[str, float]
    ) -> tuple[list[Recommendation], list[Recommendation]]:
        """90% personalized / 10% discovery — wildcards are unexpected adjacent interests."""
        discovery_ratio = float(mix.get("discovery") or 0.1)
        if not recommendations:
            return [], []
        n_wild = max(1, int(round(len(recommendations) * discovery_ratio))) if len(recommendations) >= 5 else 0
        # Personalized: saved pins first, then high scores.
        pins = [r for r in recommendations if "pin_id" in r.source_refs]
        others = [r for r in recommendations if "pin_id" not in r.source_refs]
        personalized = pins + others

        # Wildcards: high hidden_gem / atlas relevance, not already top pins.
        top_titles = {r.title for r in personalized[: max(3, len(personalized) // 2)]}
        wild_pool = [
            r
            for r in others
            if r.title not in top_titles
            and (
                r.signals.get("hidden_gem", 0) >= 0.35
                or r.signals.get("atlas_claim_relevance", 0) >= 0.4
            )
        ]
        if not wild_pool:
            wild_pool = [r for r in others if r.title not in top_titles]
        wildcards = wild_pool[:n_wild]
        # Mark wildcard signal in a copy-friendly way via explanation prefix.
        marked = []
        for r in wildcards:
            marked.append(
                Recommendation(
                    title=r.title,
                    category=r.category,
                    location=r.location,
                    estimated_duration_hours=r.estimated_duration_hours,
                    estimated_cost=r.estimated_cost,
                    confidence=r.confidence,
                    explanation=(
                        "I didn't know I'd like this: " + r.explanation
                        if not r.explanation.startswith("I didn't know")
                        else r.explanation
                    ),
                    score=r.score,
                    signals={**dict(r.signals), "wildcard": max(0.85, r.signals.get("wildcard", 0))},
                    source_refs=r.source_refs,
                    match_breakdown=r.match_breakdown,
                    priority_tier="discovery",
                    user_rating=r.user_rating,
                    joy_per_dollar=r.joy_per_dollar,
                )
            )
        return personalized, marked

    def _pin_backbone(
        self, recommendations: Sequence[Recommendation]
    ) -> list[dict[str, Any]]:
        pins = [r for r in recommendations if "pin_id" in r.source_refs]
        return [
            {
                "title": r.title,
                "pin_id": r.source_refs.get("pin_id"),
                "tier": r.priority_tier,
                "score": r.score,
                "rating": r.user_rating,
                "category": r.category,
            }
            for r in pins
        ]

    def _food_subsystem(
        self,
        recommendations: Sequence[Recommendation],
        claims: Sequence[Mapping[str, Any]],
        profile: UserProfileView,
    ) -> dict[str, Any]:
        facets = list(self.config.get("food_facets") or [])
        food_recs = [r for r in recommendations if r.category == "market_food"]
        favorites = list(profile.preferences.get("favorite_foods") or [])
        facet_hits: dict[str, list[str]] = {f: [] for f in facets}
        for claim in claims:
            topic = str(claim.get("topic_key") or "").lower()
            value = claim.get("value") or {}
            title = value.get("title") if isinstance(value, dict) else str(value)
            blob = f"{topic} {title}".lower()
            for facet in facets:
                token = facet.replace("_", " ").split()[0]
                if token in blob or facet.replace("_", " ") in blob:
                    if title:
                        facet_hits[facet].append(str(title))
        for rec in food_recs:
            facet_hits.setdefault("markets", []).append(rec.title)
            facet_hits.setdefault("street_food", []).append(rec.title)
        return {
            "facets": facets,
            "recommendations": [
                {"title": r.title, "score": r.score, "explanation": r.explanation}
                for r in food_recs[:8]
            ],
            "favorite_foods": favorites,
            "by_facet": {k: v[:5] for k, v in facet_hits.items() if v},
            "cook_later_prompt": (
                "Want to cook this when you get home?"
                if favorites or food_recs
                else None
            ),
        }

    def _build_themed_itinerary(
        self,
        pins: Sequence[SavedLocation],
        recommendations: Sequence[Recommendation],
        trip: TripDefinition,
        themes: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        pace_caps = self.config.get("max_pins_per_day") or {}
        energy = trip.energy
        energy_cap_adj = {"low": 0.75, "medium": 1.0, "high": 1.25}
        base_cap = int(pace_caps.get(trip.pace, pace_caps.get("medium", 4)))
        score_by_pin = {
            r.source_refs["pin_id"]: r
            for r in recommendations
            if "pin_id" in r.source_refs
        }
        start = date.fromisoformat(trip.start_date) if trip.start_date else None

        days_out: list[dict[str, Any]] = []
        used: set[str] = set()

        for theme_row in themes:
            day_energy = theme_row.get("energy") or energy
            cap = max(1, int(round(base_cap * energy_cap_adj.get(day_energy, 1.0))))
            if theme_row.get("open_time"):
                cap = max(1, cap - 1)  # leave room for spontaneity

            theme_cats = set(theme_row.get("categories") or [])
            # Prefer unused pins matching theme, then high score.
            pool = [
                r
                for r in recommendations
                if "pin_id" in r.source_refs
                and r.source_refs["pin_id"] not in used
            ]
            themed = [r for r in pool if r.category in theme_cats] or pool
            themed = sorted(themed, key=lambda r: r.score, reverse=True)[:cap]
            for r in themed:
                used.add(r.source_refs["pin_id"])

            stops = []
            slots = ["breakfast", "morning", "lunch", "afternoon", "dinner", "evening"]
            if theme_row.get("open_time"):
                slots = ["morning", "open_block", "afternoon", "evening"]
            for index, rec in enumerate(themed):
                slot = slots[index % len(slots)]
                stops.append(
                    {
                        "slot": slot,
                        "name": rec.title,
                        "pin_id": rec.source_refs.get("pin_id"),
                        "score": rec.score,
                        "explanation": rec.explanation,
                        "category": rec.category,
                        "match_breakdown": [
                            {"label": f.label, "points": f.points}
                            for f in rec.match_breakdown[:5]
                        ],
                    }
                )
            if theme_row.get("open_time"):
                stops.append(
                    {
                        "slot": "open_block",
                        "name": "Open discovery window",
                        "pin_id": None,
                        "score": 0,
                        "explanation": "Leave time free — nearby opportunities can fill this.",
                        "category": "general_travel",
                        "match_breakdown": [],
                    }
                )

            days_out.append(
                {
                    "day": theme_row["day"],
                    "date": theme_row.get("date"),
                    "weekday": theme_row.get("weekday"),
                    "theme_title": theme_row.get("theme_title"),
                    "theme_key": theme_row.get("theme_key"),
                    "focus": theme_row.get("focus"),
                    "energy": day_energy,
                    "stops": stops,
                }
            )

        # If no pin-based days, fall back to destination itinerary service.
        if not any(d["stops"] for d in days_out) and self.itinerary_service and pins:
            raw = self.itinerary_service.build_destination_itinerary(
                destination_kind=trip.destination_kind,
                destination_label=trip.destination_label,
                days=trip.day_count,
                start_date=start,
            )
            for index, day in enumerate(raw.get("days") or []):
                theme_row = themes[index] if index < len(themes) else {}
                stops = []
                for slot in ("morning", "afternoon", "evening"):
                    for stop in day.get(slot) or []:
                        pin_id = stop.get("pin_id") or stop.get("id")
                        rec = score_by_pin.get(pin_id) if pin_id else None
                        stops.append(
                            {
                                "slot": slot,
                                "name": stop.get("name"),
                                "pin_id": pin_id,
                                "score": rec.score if rec else 0.0,
                                "explanation": rec.explanation if rec else "",
                            }
                        )
                days_out[index] if index < len(days_out) else None
                entry = {
                    "day": day.get("day"),
                    "date": day.get("date"),
                    "weekday": theme_row.get("weekday"),
                    "theme_title": theme_row.get("theme_title"),
                    "theme_key": theme_row.get("theme_key"),
                    "focus": theme_row.get("focus"),
                    "energy": theme_row.get("energy") or energy,
                    "stops": stops[:base_cap],
                }
                if index < len(days_out):
                    days_out[index] = entry
                else:
                    days_out.append(entry)
        return days_out

    def _budget_summary(
        self,
        recommendations: Sequence[Recommendation],
        trip: TripDefinition,
        profile: UserProfileView,
    ) -> dict[str, Any]:
        top = recommendations[: int(self.config.get("max_recommendations_per_section") or 8)]
        itinerary_cost = sum(r.estimated_cost for r in top)
        daily_cap = daily_budget_cap(
            trip.budget, trip.day_count, profile.preferences, self.config
        )
        joy_scores = [r.joy_per_dollar or 0 for r in top if r.joy_per_dollar]
        over = []
        if daily_cap is not None:
            over = [
                {"title": r.title, "estimated_cost": r.estimated_cost}
                for r in top
                if r.estimated_cost > daily_cap
            ]
        return {
            "currency": "USD",
            "trip_budget": trip.budget,
            "daily_cap": daily_cap,
            "sample_experiences_cost": round(itinerary_cost, 2),
            "day_count": trip.day_count,
            "over_budget_items": over,
            "avg_joy_per_dollar": round(sum(joy_scores) / len(joy_scores), 1) if joy_scores else None,
            "philosophy": "Maximum personal joy per dollar spent.",
            "note": "Estimates are heuristic category averages, not live prices.",
        }

    def _packing(
        self,
        pins: Sequence[SavedLocation],
        trip: TripDefinition,
        profile: UserProfileView,
    ) -> list[str]:
        month = None
        if trip.start_date:
            month = date.fromisoformat(trip.start_date).month
        climate_hint = None
        if self.climate_service and pins:
            anchor = next((p for p in pins if p.latitude or p.longitude), None)
            if anchor:
                try:
                    months = self.climate_service.get_normals(
                        anchor.latitude, anchor.longitude, allow_network=False
                    )
                    if months and month:
                        m = next((x for x in months if x.month == month), None)
                        if m and m.rain_mm >= 150:
                            climate_hint = f"Expect a wet {m.name} — pack rain protection"
                        elif m and m.avg_high_c >= 30:
                            climate_hint = f"Expect hot {m.name} days — pack sun protection"
                except Exception:
                    climate_hint = None
        return packing_suggestions(
            preferences=profile.preferences,
            pace=trip.pace,
            month=month,
            climate_hint=climate_hint,
        )

    def _planning_links(
        self, pins: Sequence[SavedLocation], destination_label: str
    ) -> dict[str, str]:
        if not self.planning_service or not pins:
            return {"destination": destination_label}
        return self.planning_service.planning_links(pins[0])

    def _skip_list(
        self, recommendations: Sequence[Recommendation]
    ) -> list[Recommendation]:
        if len(recommendations) < 3:
            return []
        return [
            r
            for r in recommendations
            if r.score < 35
            or (
                r.signals.get("pace_fit", 1) < 0.35
                and r.signals.get("budget_fit", 1) < 0.35
            )
            or r.priority_tier == "not_planned"
        ][-5:]

    @staticmethod
    def _summary(
        destination_label: str,
        profile: UserProfileView,
        experiences: Sequence[Recommendation],
        food: Sequence[Recommendation],
        museums: Sequence[Recommendation],
        trip: TripDefinition,
        coverage: Mapping[str, Any],
    ) -> str:
        interest_bit = (
            ", ".join(profile.interests[:3])
            if profile.interests
            else "your general travel style"
        )
        top = experiences[0].title if experiences else "your saved places"
        cov = coverage.get("overall", 0)
        parts = [
            f"For {destination_label} at a {trip.pace} pace (energy: {trip.energy}), "
            f"optimize for joy per dollar around {interest_bit}.",
            f"Interest coverage: {cov}%.",
            f"Top pick: {top}.",
        ]
        if food:
            parts.append(f"Food to prioritize: {food[0].title}.")
        if museums:
            parts.append(f"Most relevant museum: {museums[0].title}.")
        return " ".join(parts)


__all__ = ["PlanningEngine", "default_planning_config", "profile_from_dict"]
