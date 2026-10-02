"""Persistence queries for curated Travel Atlas knowledge."""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from typing import Any, Iterable, Mapping, Optional

from .database import AtlasDatabase, SCHEMA_VERSION

_CONFIDENCE_RANK = {"low": 1, "medium": 2, "high": 3}


class AtlasRepository:
    def __init__(self, database: AtlasDatabase) -> None:
        self.database = database

    def upsert_categories(self, categories: Iterable[Mapping[str, Any]]) -> None:
        with self.database.connect() as conn:
            conn.executemany(
                """
                INSERT INTO knowledge_category(key, display_name, description, sort_order)
                VALUES (:key, :display_name, :description, :sort_order)
                ON CONFLICT(key) DO UPDATE SET
                    display_name=excluded.display_name,
                    description=excluded.description,
                    sort_order=excluded.sort_order
                """,
                list(categories),
            )

    def upsert_topics(self, topics: Iterable[Mapping[str, Any]]) -> None:
        with self.database.connect() as conn:
            conn.executemany(
                """
                INSERT INTO knowledge_topic(key, category_key, display_name, description)
                VALUES (:key, :category_key, :display_name, :description)
                ON CONFLICT(key) DO UPDATE SET
                    category_key=excluded.category_key,
                    display_name=excluded.display_name,
                    description=excluded.description
                """,
                list(topics),
            )

    def upsert_area(self, area: Mapping[str, Any]) -> None:
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO geo_area(id, name, area_type, country_code, parent_id, latitude, longitude)
                VALUES (:id, :name, :area_type, :country_code, :parent_id, :latitude, :longitude)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    area_type=excluded.area_type,
                    country_code=excluded.country_code,
                    parent_id=excluded.parent_id,
                    latitude=excluded.latitude,
                    longitude=excluded.longitude
                """,
                area,
            )

    def upsert_source(self, source: Mapping[str, Any]) -> None:
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO source(id, title, publisher, source_url, enrichment_url, retrieved_at, license_note)
                VALUES (:id, :title, :publisher, :source_url, :enrichment_url, :retrieved_at, :license_note)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    publisher=excluded.publisher,
                    source_url=excluded.source_url,
                    enrichment_url=excluded.enrichment_url,
                    retrieved_at=excluded.retrieved_at,
                    license_note=excluded.license_note
                """,
                source,
            )

    def upsert_claim(self, claim: Mapping[str, Any]) -> None:
        payload = dict(claim)
        payload["value_json"] = json.dumps(payload.pop("value"), sort_keys=True)
        payload.setdefault("source_record_id", None)
        payload.setdefault("valid_from", None)
        payload.setdefault("valid_until", None)
        payload.setdefault("season_start_month_day", None)
        payload.setdefault("season_end_month_day", None)
        payload.setdefault("season_label", None)
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO knowledge_claim(
                    id, area_id, category_key, topic_key, value_json, source_id,
                    source_record_id, confidence, review_status, valid_from, valid_until,
                    season_start_month_day, season_end_month_day, season_label
                ) VALUES (
                    :id, :area_id, :category_key, :topic_key, :value_json, :source_id,
                    :source_record_id, :confidence, :review_status, :valid_from, :valid_until,
                    :season_start_month_day, :season_end_month_day, :season_label
                )
                ON CONFLICT(id) DO UPDATE SET
                    area_id=excluded.area_id,
                    category_key=excluded.category_key,
                    topic_key=excluded.topic_key,
                    value_json=excluded.value_json,
                    source_id=excluded.source_id,
                    source_record_id=excluded.source_record_id,
                    confidence=excluded.confidence,
                    review_status=excluded.review_status,
                    valid_from=excluded.valid_from,
                    valid_until=excluded.valid_until,
                    season_start_month_day=excluded.season_start_month_day,
                    season_end_month_day=excluded.season_end_month_day,
                    season_label=excluded.season_label
                """,
                payload,
            )

    def replace_coverage_rules(self, rules: Iterable[Mapping[str, Any]]) -> None:
        with self.database.connect() as conn:
            conn.execute("DELETE FROM coverage_rule")
            conn.executemany(
                """
                INSERT INTO coverage_rule(area_type, category_key, topic_key, weight, minimum_confidence)
                VALUES (:area_type, :category_key, :topic_key, :weight, :minimum_confidence)
                """,
                list(rules),
            )

    def list_areas(self, area_type: Optional[str] = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM geo_area"
        params: tuple[str, ...] = ()
        if area_type:
            query += " WHERE area_type = ?"
            params = (area_type,)
        query += " ORDER BY name"
        with self.database.connect() as conn:
            return [dict(row) for row in conn.execute(query, params)]

    def get_area(self, area_id: str) -> Optional[dict[str, Any]]:
        with self.database.connect() as conn:
            row = conn.execute("SELECT * FROM geo_area WHERE id = ?", (area_id,)).fetchone()
            return dict(row) if row else None

    def find_area_by_name(
        self, name: str, area_type: Optional[str] = None
    ) -> Optional[dict[str, Any]]:
        query = "SELECT * FROM geo_area WHERE LOWER(name) = LOWER(?)"
        params: list[str] = [name.strip()]
        if area_type:
            query += " AND area_type = ?"
            params.append(area_type)
        query += " ORDER BY CASE area_type WHEN 'city' THEN 1 WHEN 'country' THEN 2 ELSE 3 END"
        with self.database.connect() as conn:
            row = conn.execute(query, params).fetchone()
        return dict(row) if row else None

    def list_claims(self, area_id: str) -> list[dict[str, Any]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT claim.*, topic.display_name AS topic_name,
                       category.display_name AS category_name, category.sort_order,
                       source.title AS source_title, source.publisher, source.source_url,
                       source.enrichment_url, source.retrieved_at
                FROM knowledge_claim AS claim
                JOIN knowledge_topic AS topic ON topic.key = claim.topic_key
                JOIN knowledge_category AS category ON category.key = claim.category_key
                JOIN source ON source.id = claim.source_id
                WHERE claim.area_id = ?
                ORDER BY category.sort_order, topic.display_name
                """,
                (area_id,),
            ).fetchall()
        claims = []
        for row in rows:
            claim = dict(row)
            claim["value"] = json.loads(claim.pop("value_json"))
            claims.append(claim)
        return claims

    def list_seasonal_claims(self, area_id: str) -> list[dict[str, Any]]:
        """All claims (curated and personal) for an area with a recurring annual window."""
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT claim.*, topic.display_name AS topic_name,
                       category.display_name AS category_name, category.sort_order,
                       source.title AS source_title, source.publisher, source.source_url,
                       source.enrichment_url, source.retrieved_at
                FROM knowledge_claim AS claim
                JOIN knowledge_topic AS topic ON topic.key = claim.topic_key
                JOIN knowledge_category AS category ON category.key = claim.category_key
                JOIN source ON source.id = claim.source_id
                WHERE claim.area_id = ? AND claim.season_start_month_day IS NOT NULL
                ORDER BY category.sort_order, topic.display_name
                """,
                (area_id,),
            ).fetchall()
        claims = []
        for row in rows:
            claim = dict(row)
            claim["value"] = json.loads(claim.pop("value_json"))
            claims.append(claim)
        return claims

    def recompute_coverage(self, area_id: str) -> list[dict[str, Any]]:
        area = self.get_area(area_id)
        if not area:
            raise ValueError(f"Unknown area: {area_id}")
        with self.database.connect() as conn:
            rules = conn.execute(
                """
                SELECT rule.*, category.display_name AS category_name
                FROM coverage_rule AS rule
                JOIN knowledge_category AS category ON category.key = rule.category_key
                WHERE rule.area_type = ?
                ORDER BY category.sort_order, rule.topic_key
                """,
                (area["area_type"],),
            ).fetchall()
            claims = conn.execute(
                """
                SELECT topic_key, confidence FROM knowledge_claim
                WHERE area_id = ? AND review_status = 'reviewed'
                """,
                (area_id,),
            ).fetchall()
            claim_confidence: dict[str, int] = {}
            for row in claims:
                current = claim_confidence.get(row["topic_key"], 0)
                claim_confidence[row["topic_key"]] = max(
                    current, _CONFIDENCE_RANK[row["confidence"]]
                )

            grouped: dict[str, dict[str, Any]] = defaultdict(
                lambda: {"category_name": "", "covered": 0.0, "required": 0.0, "missing": []}
            )
            for rule in rules:
                item = grouped[rule["category_key"]]
                item["category_name"] = rule["category_name"]
                item["required"] += rule["weight"]
                if claim_confidence.get(rule["topic_key"], 0) >= _CONFIDENCE_RANK[rule["minimum_confidence"]]:
                    item["covered"] += rule["weight"]
                else:
                    item["missing"].append(rule["topic_key"])

            conn.execute(
                "DELETE FROM coverage_assessment WHERE area_id = ? AND ruleset_version = ?",
                (area_id, SCHEMA_VERSION),
            )
            results = []
            for category_key, item in grouped.items():
                score = item["covered"] / item["required"] if item["required"] else 0.0
                conn.execute(
                    """
                    INSERT INTO coverage_assessment(
                        area_id, category_key, covered_weight, required_weight, score,
                        missing_topics_json, ruleset_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        area_id, category_key, item["covered"], item["required"], score,
                        json.dumps(item["missing"]), SCHEMA_VERSION,
                    ),
                )
                results.append(
                    {
                        "category_key": category_key,
                        "category_name": item["category_name"],
                        "score": score,
                        "missing_topics": item["missing"],
                    }
                )
        return results

    def get_coverage(self, area_id: str) -> list[dict[str, Any]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT assessment.*, category.display_name AS category_name
                FROM coverage_assessment AS assessment
                JOIN knowledge_category AS category ON category.key = assessment.category_key
                WHERE assessment.area_id = ? AND assessment.ruleset_version = ?
                ORDER BY category.sort_order
                """,
                (area_id, SCHEMA_VERSION),
            ).fetchall()
        return [
            {**dict(row), "missing_topics": json.loads(row["missing_topics_json"])}
            for row in rows
        ]

    def get_profile(self, user_key: str) -> dict[str, Any]:
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT * FROM user_profile WHERE user_key = ?", (user_key,)
            ).fetchone()
            if not row:
                conn.execute("INSERT INTO user_profile(user_key) VALUES (?)", (user_key,))
                row = conn.execute(
                    "SELECT * FROM user_profile WHERE user_key = ?", (user_key,)
                ).fetchone()
        profile = dict(row)
        list_keys = {"interests_json", "learning_goals_json"}
        for key in (
            "interests_json",
            "accommodation_preferences_json",
            "learning_goals_json",
            "preferences_json",
        ):
            raw = profile.pop(key, None)
            field = key.removesuffix("_json")
            if raw is not None:
                profile[field] = json.loads(raw)
            else:
                profile[field] = [] if key in list_keys else {}
        return profile

    def save_profile(
        self,
        user_key: str,
        interests: list[str],
        travel_style: str,
        accommodation_preferences: Mapping[str, Any],
        learning_goals: list[str],
        preferences: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        existing = self.get_profile(user_key)
        bag = dict(existing.get("preferences") or {})
        if preferences is not None:
            bag.update(dict(preferences))
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO user_profile(
                    user_key, interests_json, travel_style, accommodation_preferences_json,
                    learning_goals_json, preferences_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_key) DO UPDATE SET
                    interests_json=excluded.interests_json,
                    travel_style=excluded.travel_style,
                    accommodation_preferences_json=excluded.accommodation_preferences_json,
                    learning_goals_json=excluded.learning_goals_json,
                    preferences_json=excluded.preferences_json,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    user_key, json.dumps(interests), travel_style,
                    json.dumps(dict(accommodation_preferences)), json.dumps(learning_goals),
                    json.dumps(bag),
                ),
            )
        return self.get_profile(user_key)

    def merge_preferences(
        self, user_key: str, preferences: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Merge keys into the expandable preferences bag without rewriting schema."""
        profile = self.get_profile(user_key)
        return self.save_profile(
            user_key,
            profile.get("interests", []),
            profile.get("travel_style", "balanced"),
            profile.get("accommodation_preferences", {}),
            profile.get("learning_goals", []),
            preferences,
        )

    def get_or_save_classification(
        self,
        pin_id: str,
        taxonomy_version: str,
        source_hash: str,
        tags: list[str],
        confidence: float,
        evidence: list[Mapping[str, Any]],
    ) -> dict[str, Any]:
        with self.database.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM pin_classification
                WHERE pin_id = ? AND taxonomy_version = ? AND source_hash = ?
                """,
                (pin_id, taxonomy_version, source_hash),
            ).fetchone()
            if not row:
                classification_id = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO pin_classification(
                        id, pin_id, taxonomy_version, source_hash, tags_json, confidence, evidence_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        classification_id, pin_id, taxonomy_version, source_hash,
                        json.dumps(tags), confidence, json.dumps(evidence),
                    ),
                )
                row = conn.execute(
                    "SELECT * FROM pin_classification WHERE id = ?", (classification_id,)
                ).fetchone()
        return {
            **dict(row),
            "tags": json.loads(row["tags_json"]),
            "evidence": json.loads(row["evidence_json"]),
        }

    def get_or_save_lesson(
        self,
        user_key: str,
        pin_id: str,
        source_hash: str,
        language_code: str,
        topic_tag: str,
        title: str,
        context_text: str,
        phrases: list[Mapping[str, str]],
        explanation: Mapping[str, Any],
        lesson_source: str,
    ) -> dict[str, Any]:
        self.get_profile(user_key)
        with self.database.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM language_lesson
                WHERE user_key = ? AND pin_id = ? AND source_hash = ?
                  AND language_code = ? AND topic_tag = ?
                """,
                (user_key, pin_id, source_hash, language_code, topic_tag),
            ).fetchone()
            if not row:
                lesson_id = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO language_lesson(
                        id, user_key, pin_id, source_hash, language_code, topic_tag,
                        title, context_text, phrases_json, explanation_json, lesson_source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        lesson_id, user_key, pin_id, source_hash, language_code, topic_tag,
                        title, context_text, json.dumps(phrases), json.dumps(dict(explanation)),
                        lesson_source,
                    ),
                )
                row = conn.execute(
                    "SELECT * FROM language_lesson WHERE id = ?", (lesson_id,)
                ).fetchone()
        return {
            **dict(row),
            "phrases": json.loads(row["phrases_json"]),
            "explanation": json.loads(row["explanation_json"]),
        }

    def get_pin_annotation(self, pin_id: str) -> str:
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT note_text FROM pin_annotation WHERE pin_id = ?", (pin_id,)
            ).fetchone()
        return row["note_text"] if row else ""

    def save_pin_annotation(self, pin_id: str, note_text: str) -> None:
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO pin_annotation(pin_id, note_text, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(pin_id) DO UPDATE SET
                    note_text=excluded.note_text,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (pin_id, note_text),
            )

    def list_custom_phrases(
        self, *, area_id: str | None = None, pin_id: str | None = None
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM custom_phrase WHERE 1=1"
        params: list[str] = []
        if area_id:
            query += " AND area_id = ?"
            params.append(area_id)
        if pin_id:
            query += " AND pin_id = ?"
            params.append(pin_id)
        query += " ORDER BY created_at DESC"
        with self.database.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def add_custom_phrase(
        self,
        *,
        id: str,
        area_id: str | None,
        pin_id: str | None,
        phrase: str,
        translation: str,
        note: str | None,
    ) -> dict[str, Any]:
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO custom_phrase(id, area_id, pin_id, phrase, translation, note)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (id, area_id, pin_id, phrase, translation, note),
            )
            row = conn.execute(
                "SELECT * FROM custom_phrase WHERE id = ?", (id,)
            ).fetchone()
        return dict(row)

    def list_user_claims(self, area_id: str) -> list[dict[str, Any]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT claim.*, topic.display_name AS topic_name,
                       category.display_name AS category_name, category.sort_order
                FROM knowledge_claim AS claim
                JOIN knowledge_topic AS topic ON topic.key = claim.topic_key
                JOIN knowledge_category AS category ON category.key = claim.category_key
                WHERE claim.area_id = ? AND claim.source_id = 'user-notes'
                ORDER BY category.sort_order, topic.display_name
                """,
                (area_id,),
            ).fetchall()
        claims = []
        for row in rows:
            claim = dict(row)
            claim["value"] = json.loads(claim.pop("value_json"))
            claims.append(claim)
        return claims

    def list_top_level_coverage(self) -> list[dict[str, Any]]:
        areas = self.list_areas()
        by_id = {area["id"]: area for area in areas}
        children_by_parent: dict[str | None, list[dict[str, Any]]] = defaultdict(list)
        for area in areas:
            children_by_parent[area.get("parent_id")].append(area)

        top_levels = [
            area for area in areas if area["area_type"] in {"country", "region"}
        ]
        results = []
        for area in top_levels:
            child_ids = [area["id"]] + [
                child["id"] for child in children_by_parent.get(area["id"], [])
            ]
            coverage_rows = []
            for child_id in child_ids:
                coverage_rows.extend(self.get_coverage(child_id))
            if not coverage_rows:
                overall = 0.0
            else:
                overall = sum(item["score"] for item in coverage_rows) / len(coverage_rows)
            child_areas = [
                {
                    "id": child["id"],
                    "name": child["name"],
                    "area_type": child["area_type"],
                    "coverage": self.get_coverage(child["id"]),
                }
                for child in children_by_parent.get(area["id"], [])
            ]
            results.append(
                {
                    "id": area["id"],
                    "name": area["name"],
                    "area_type": area["area_type"],
                    "parent_id": area.get("parent_id"),
                    "overall_score": overall,
                    "children": child_areas,
                }
            )
        return sorted(results, key=lambda item: item["name"].lower())

    # -- Ingestion pipeline -------------------------------------------------
    #
    # `recompute_coverage` scores an area from its *reviewed* claims only, so a draft
    # never inflates a coverage number. The methods below drive the loop that turns
    # coverage gaps into drafts and drafts into reviewed knowledge.

    def upsert_source_record(
        self,
        *,
        id: str,
        source_id: str,
        external_key: str,
        raw_payload: str,
        checksum: str,
    ) -> None:
        """Store the fetched source text verbatim so a claim can be traced back to it."""
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO source_record(
                    id, source_id, external_key, raw_payload, checksum
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(source_id, external_key) DO UPDATE SET
                    raw_payload=excluded.raw_payload,
                    checksum=excluded.checksum,
                    imported_at=CURRENT_TIMESTAMP
                """,
                (id, source_id, external_key, raw_payload, checksum),
            )

    def find_source_record(self, source_id: str, external_key: str) -> Optional[dict[str, Any]]:
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT * FROM source_record WHERE source_id = ? AND external_key = ?",
                (source_id, external_key),
            ).fetchone()
        return dict(row) if row else None

    def missing_topics(self, area_id: str) -> list[dict[str, str]]:
        """Topics the coverage ruleset requires for this area but no claim satisfies.

        A topic counts as satisfied by any claim at or above the rule's minimum
        confidence — including drafts, which are excluded from *scoring* but must be
        excluded from the worklist too, or a rerun would draft the same topic twice.
        """
        area = self.get_area(area_id)
        if not area:
            raise ValueError(f"Unknown area: {area_id}")
        with self.database.connect() as conn:
            rules = conn.execute(
                """
                SELECT rule.category_key, rule.topic_key, rule.minimum_confidence,
                       topic.display_name AS topic_name,
                       topic.description AS topic_description,
                       category.display_name AS category_name
                FROM coverage_rule AS rule
                JOIN knowledge_topic AS topic ON topic.key = rule.topic_key
                JOIN knowledge_category AS category ON category.key = rule.category_key
                WHERE rule.area_type = ?
                ORDER BY category.sort_order, rule.topic_key
                """,
                (area["area_type"],),
            ).fetchall()
            existing = conn.execute(
                "SELECT topic_key, confidence FROM knowledge_claim WHERE area_id = ?",
                (area_id,),
            ).fetchall()
            attempted = {
                row["topic_key"]
                for row in conn.execute(
                    "SELECT topic_key FROM ingest_attempt WHERE area_id = ?", (area_id,)
                )
            }

        best: dict[str, int] = {}
        for row in existing:
            best[row["topic_key"]] = max(
                best.get(row["topic_key"], 0), _CONFIDENCE_RANK[row["confidence"]]
            )

        missing = []
        for rule in rules:
            topic = rule["topic_key"]
            if topic in attempted:
                continue
            if best.get(topic, 0) >= _CONFIDENCE_RANK[rule["minimum_confidence"]]:
                continue
            missing.append(
                {
                    "area_id": area_id,
                    "area_name": area["name"],
                    "area_type": area["area_type"],
                    "country_code": area["country_code"],
                    "category_key": rule["category_key"],
                    "category_name": rule["category_name"],
                    "topic_key": topic,
                    "topic_name": rule["topic_name"],
                    "topic_description": rule["topic_description"],
                }
            )
        return missing

    def record_attempt(
        self,
        *,
        area_id: str,
        topic_key: str,
        status: str,
        detail: str | None = None,
        model: str | None = None,
        claim_count: int = 0,
    ) -> None:
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO ingest_attempt(
                    area_id, topic_key, status, detail, model, claim_count, attempted_at
                ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(area_id, topic_key) DO UPDATE SET
                    status=excluded.status,
                    detail=excluded.detail,
                    model=excluded.model,
                    claim_count=excluded.claim_count,
                    attempted_at=CURRENT_TIMESTAMP
                """,
                (area_id, topic_key, status, detail, model, claim_count),
            )

    def clear_attempts(self, area_id: str | None = None) -> int:
        """Forget past attempts so barren or errored pairs are retried."""
        with self.database.connect() as conn:
            if area_id:
                cursor = conn.execute(
                    "DELETE FROM ingest_attempt WHERE area_id = ?", (area_id,)
                )
            else:
                cursor = conn.execute("DELETE FROM ingest_attempt")
            return cursor.rowcount

    def list_claims_by_status(
        self, review_status: str, *, area_id: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        query = """
            SELECT claim.*, topic.display_name AS topic_name,
                   category.display_name AS category_name, category.sort_order,
                   area.name AS area_name, area.area_type,
                   source.title AS source_title, source.publisher, source.source_url
            FROM knowledge_claim AS claim
            JOIN knowledge_topic AS topic ON topic.key = claim.topic_key
            JOIN knowledge_category AS category ON category.key = claim.category_key
            JOIN geo_area AS area ON area.id = claim.area_id
            JOIN source ON source.id = claim.source_id
            WHERE claim.review_status = ?
        """
        params: list[Any] = [review_status]
        if area_id:
            query += " AND claim.area_id = ?"
            params.append(area_id)
        query += " ORDER BY area.name, category.sort_order, topic.display_name LIMIT ?"
        params.append(limit)
        with self.database.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        claims = []
        for row in rows:
            claim = dict(row)
            claim["value"] = json.loads(claim.pop("value_json"))
            claims.append(claim)
        return claims

    def count_claims_by_status(self) -> dict[str, int]:
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT review_status, COUNT(*) AS n FROM knowledge_claim "
                "GROUP BY review_status"
            ).fetchall()
        return {row["review_status"]: row["n"] for row in rows}

    def set_review_status(self, claim_ids: Iterable[str], review_status: str) -> list[str]:
        """Approve or reject drafts; returns the areas whose coverage is now stale."""
        ids = list(claim_ids)
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        with self.database.connect() as conn:
            areas = [
                row["area_id"]
                for row in conn.execute(
                    f"SELECT DISTINCT area_id FROM knowledge_claim WHERE id IN ({placeholders})",
                    ids,
                )
            ]
            conn.execute(
                f"UPDATE knowledge_claim SET review_status = ? WHERE id IN ({placeholders})",
                [review_status, *ids],
            )
        return areas

    def delete_claims(self, claim_ids: Iterable[str]) -> int:
        ids = list(claim_ids)
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        with self.database.connect() as conn:
            cursor = conn.execute(
                f"DELETE FROM knowledge_claim WHERE id IN ({placeholders})", ids
            )
            return cursor.rowcount

    def upsert_planned_area(
        self,
        *,
        area_id: str,
        name: str,
        area_type: str,
        parent_id: str | None = None,
    ) -> None:
        self.upsert_area(
            {
                "id": area_id,
                "name": name,
                "area_type": area_type,
                "country_code": None,
                "parent_id": parent_id,
                "latitude": None,
                "longitude": None,
            }
        )

    # --- Planning feedback (written by FeedbackService, read by PlanningEngine) ---

    def upsert_recommendation_rating(
        self,
        *,
        user_key: str,
        subject_kind: str,
        subject_id: str,
        rating: str,
        score: float,
        destination_label: str | None = None,
        category: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        self.get_profile(user_key)
        rating_id = str(uuid.uuid4())
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO recommendation_rating(
                    id, user_key, subject_kind, subject_id, destination_label,
                    category, rating, score, note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_key, subject_kind, subject_id) DO UPDATE SET
                    rating=excluded.rating,
                    score=excluded.score,
                    destination_label=excluded.destination_label,
                    category=excluded.category,
                    note=excluded.note,
                    created_at=CURRENT_TIMESTAMP
                """,
                (
                    rating_id,
                    user_key,
                    subject_kind,
                    subject_id,
                    destination_label,
                    category,
                    rating,
                    score,
                    note,
                ),
            )
            row = conn.execute(
                """
                SELECT * FROM recommendation_rating
                WHERE user_key = ? AND subject_kind = ? AND subject_id = ?
                """,
                (user_key, subject_kind, subject_id),
            ).fetchone()
        return dict(row)

    def list_recommendation_ratings(
        self, user_key: str, *, destination_label: str | None = None
    ) -> list[dict[str, Any]]:
        with self.database.connect() as conn:
            if destination_label:
                rows = conn.execute(
                    """
                    SELECT * FROM recommendation_rating
                    WHERE user_key = ? AND (
                        destination_label IS NULL OR destination_label = ?
                    )
                    ORDER BY created_at DESC
                    """,
                    (user_key, destination_label),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM recommendation_rating
                    WHERE user_key = ?
                    ORDER BY created_at DESC
                    """,
                    (user_key,),
                ).fetchall()
        return [dict(row) for row in rows]

    def get_rating_lookup(self, user_key: str) -> dict[tuple[str, str], dict[str, Any]]:
        return {
            (row["subject_kind"], row["subject_id"]): row
            for row in self.list_recommendation_ratings(user_key)
        }

    def save_journal_entry(
        self,
        *,
        user_key: str,
        body: str,
        trip_id: str | None = None,
        destination_label: str | None = None,
        entry_date: str | None = None,
        day_number: int | None = None,
        enjoyed: list[str] | None = None,
        skip: list[str] | None = None,
        entry_id: str | None = None,
    ) -> dict[str, Any]:
        self.get_profile(user_key)
        eid = entry_id or str(uuid.uuid4())
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO trip_journal_entry(
                    id, user_key, trip_id, destination_label, entry_date, day_number,
                    body, enjoyed_json, skip_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    body=excluded.body,
                    enjoyed_json=excluded.enjoyed_json,
                    skip_json=excluded.skip_json,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    eid,
                    user_key,
                    trip_id,
                    destination_label,
                    entry_date,
                    day_number,
                    body,
                    json.dumps(enjoyed or []),
                    json.dumps(skip or []),
                ),
            )
            row = conn.execute(
                "SELECT * FROM trip_journal_entry WHERE id = ?", (eid,)
            ).fetchone()
        result = dict(row)
        result["enjoyed"] = json.loads(result.pop("enjoyed_json"))
        result["skip"] = json.loads(result.pop("skip_json"))
        return result

    def list_journal_entries(
        self, user_key: str, *, destination_label: str | None = None
    ) -> list[dict[str, Any]]:
        with self.database.connect() as conn:
            if destination_label:
                rows = conn.execute(
                    """
                    SELECT * FROM trip_journal_entry
                    WHERE user_key = ? AND destination_label = ?
                    ORDER BY entry_date DESC, created_at DESC
                    """,
                    (user_key, destination_label),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM trip_journal_entry
                    WHERE user_key = ?
                    ORDER BY entry_date DESC, created_at DESC
                    """,
                    (user_key,),
                ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["enjoyed"] = json.loads(item.pop("enjoyed_json"))
            item["skip"] = json.loads(item.pop("skip_json"))
            out.append(item)
        return out

    def get_planning_weight_multipliers(self, user_key: str) -> dict[str, float]:
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT category, multiplier FROM planning_weight_state WHERE user_key = ?",
                (user_key,),
            ).fetchall()
        return {row["category"]: float(row["multiplier"]) for row in rows}

    def upsert_planning_weight(
        self, user_key: str, category: str, multiplier: float, sample_count: int
    ) -> None:
        self.get_profile(user_key)
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO planning_weight_state(
                    user_key, category, multiplier, sample_count, updated_at
                ) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_key, category) DO UPDATE SET
                    multiplier=excluded.multiplier,
                    sample_count=excluded.sample_count,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (user_key, category, multiplier, sample_count),
            )

    # --- Command Center: checklist, budget, missions ---

    def upsert_checklist_item(
        self,
        *,
        trip_id: str,
        key: str,
        band: str,
        title: str,
        category: str = "prep",
        due_offset_days: int | None = None,
        sort_index: int = 0,
        item_id: str | None = None,
    ) -> dict[str, Any]:
        eid = item_id or str(uuid.uuid4())
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO trip_checklist_item(
                    id, trip_id, key, band, title, category, due_offset_days, sort_index
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trip_id, key) DO UPDATE SET
                    band=excluded.band,
                    title=excluded.title,
                    category=excluded.category,
                    due_offset_days=excluded.due_offset_days,
                    sort_index=excluded.sort_index
                """,
                (eid, trip_id, key, band, title, category, due_offset_days, sort_index),
            )
            row = conn.execute(
                "SELECT * FROM trip_checklist_item WHERE trip_id = ? AND key = ?",
                (trip_id, key),
            ).fetchone()
        return dict(row)

    def list_checklist_items(self, trip_id: str) -> list[dict[str, Any]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM trip_checklist_item
                WHERE trip_id = ?
                ORDER BY sort_index, title
                """,
                (trip_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def set_checklist_completed(
        self, trip_id: str, key: str, completed: bool
    ) -> dict[str, Any] | None:
        with self.database.connect() as conn:
            if completed:
                conn.execute(
                    """
                    UPDATE trip_checklist_item
                    SET completed_at = CURRENT_TIMESTAMP
                    WHERE trip_id = ? AND key = ?
                    """,
                    (trip_id, key),
                )
            else:
                conn.execute(
                    """
                    UPDATE trip_checklist_item
                    SET completed_at = NULL
                    WHERE trip_id = ? AND key = ?
                    """,
                    (trip_id, key),
                )
            row = conn.execute(
                "SELECT * FROM trip_checklist_item WHERE trip_id = ? AND key = ?",
                (trip_id, key),
            ).fetchone()
        return dict(row) if row else None

    def upsert_budget_line(
        self,
        *,
        trip_id: str,
        category: str,
        label: str,
        estimated_amount: float,
        actual_amount: float | None = None,
        confidence: float = 40.0,
        source: str = "heuristic",
        line_id: str | None = None,
    ) -> dict[str, Any]:
        eid = line_id or str(uuid.uuid4())
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO trip_budget_line(
                    id, trip_id, category, label, estimated_amount, actual_amount,
                    confidence, source, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(trip_id, category, label) DO UPDATE SET
                    estimated_amount=excluded.estimated_amount,
                    actual_amount=excluded.actual_amount,
                    confidence=excluded.confidence,
                    source=excluded.source,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    eid,
                    trip_id,
                    category,
                    label,
                    estimated_amount,
                    actual_amount,
                    confidence,
                    source,
                ),
            )
            row = conn.execute(
                """
                SELECT * FROM trip_budget_line
                WHERE trip_id = ? AND category = ? AND label = ?
                """,
                (trip_id, category, label),
            ).fetchone()
        return dict(row)

    def list_budget_lines(self, trip_id: str) -> list[dict[str, Any]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM trip_budget_line
                WHERE trip_id = ?
                ORDER BY category, label
                """,
                (trip_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_mission_log(
        self,
        *,
        trip_id: str,
        mission_date: str,
        missions: list[Mapping[str, Any]],
        completed: list[str],
        prep_score: float,
        log_id: str | None = None,
    ) -> dict[str, Any]:
        eid = log_id or str(uuid.uuid4())
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO trip_mission_log(
                    id, trip_id, mission_date, missions_json, completed_json, prep_score
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(trip_id, mission_date) DO UPDATE SET
                    missions_json=excluded.missions_json,
                    completed_json=excluded.completed_json,
                    prep_score=excluded.prep_score
                """,
                (
                    eid,
                    trip_id,
                    mission_date,
                    json.dumps(list(missions)),
                    json.dumps(list(completed)),
                    prep_score,
                ),
            )
            row = conn.execute(
                """
                SELECT * FROM trip_mission_log
                WHERE trip_id = ? AND mission_date = ?
                """,
                (trip_id, mission_date),
            ).fetchone()
        result = dict(row)
        result["missions"] = json.loads(result.pop("missions_json"))
        result["completed"] = json.loads(result.pop("completed_json"))
        return result

    def get_mission_log(
        self, trip_id: str, mission_date: str
    ) -> dict[str, Any] | None:
        with self.database.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM trip_mission_log
                WHERE trip_id = ? AND mission_date = ?
                """,
                (trip_id, mission_date),
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["missions"] = json.loads(result.pop("missions_json"))
        result["completed"] = json.loads(result.pop("completed_json"))
        return result

