"""Good Price 도메인 DB 접근 계층."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, cast

from psycopg import AsyncConnection
from psycopg.types.json import Json

from nolleo_pipeline.common.db import get_pool
from nolleo_pipeline.domains.good_price.matcher import (
    FoodPlaceMatchCandidate,
    MATCH_METHOD_RULE,
    MAX_CANDIDATE_DISTANCE_M,
    ScoredSpotMatch,
    SpotMatchCandidate,
    pick_best_match,
)
from nolleo_pipeline.domains.good_price.models import (
    FoodPlaceMenuRecord,
    FoodPlaceRecord,
    FoodPlaceSourceRecord,
    ParsedFoodPlace,
)


SPOT_PRICE_SUMMARY_TABLE = "sp_spot_price_summary"
SPOTS_TABLE = "sp_spots"
SPOT_DETAILS_TABLE = "sp_spot_details"


@dataclass(frozen=True)
class SpotPriceMenuCandidate:
    """스팟 가격 요약 집계 입력 row."""

    spot_content_id: str | None
    food_place_id: int
    menu_name: str
    price: int | None
    source: str
    is_representative: bool
    display_order: int | None
    match_status: str


@dataclass(frozen=True)
class SpotPriceSummaryRecord:
    """sp_spot_price_summary upsert 대상 row."""

    spot_content_id: str
    min_price: int
    avg_price: int
    representative_menu_name: str
    representative_price: int
    menu_count: int
    source_count: int


@dataclass(frozen=True)
class SpotPriceSummaryRefreshResult:
    """스팟 가격 요약 갱신 결과."""

    aggregated_count: int
    upserted_count: int
    pruned_count: int
    dry_run: bool


@dataclass(frozen=True)
class FoodSpotMatchRunResult:
    """음식 장소-스팟 룰 매칭 실행 결과."""

    places_scanned: int
    matches_upserted: int
    matched_count: int
    pending_count: int
    separate_count: int
    no_candidate_count: int
    dry_run: bool


@dataclass(frozen=True)
class FoodPlaceStoreEnrichRunResult:
    """good_price_store → good_price_menu 메타데이터 병합 결과."""

    menu_places_scanned: int
    store_name_matches: int
    enriched_count: int
    address_filled: int
    coords_filled: int
    tel_filled: int
    no_store_match: int
    dry_run: bool


SPOT_PRICE_SUMMARY_AGGREGATE_SQL = """
WITH priced_menus AS (
    SELECT
        matches.spot_content_id,
        menus.food_place_id,
        menus.menu_name,
        menus.price,
        menus.source,
        menus.is_representative,
        menus.display_order
      FROM fd_food_place_spot_matches AS matches
      JOIN fd_food_place_menus AS menus
        ON menus.food_place_id = matches.food_place_id
     WHERE matches.match_status = 'matched'
       AND matches.spot_content_id IS NOT NULL
       AND menus.price IS NOT NULL
       AND menus.price > 0
),
ranked_menus AS (
    SELECT
        priced_menus.*,
        ROW_NUMBER() OVER (
            PARTITION BY priced_menus.spot_content_id
            ORDER BY
                CASE WHEN priced_menus.is_representative THEN 0 ELSE 1 END,
                priced_menus.price ASC,
                priced_menus.display_order ASC NULLS LAST,
                priced_menus.menu_name ASC
        ) AS representative_rank
      FROM priced_menus
)
SELECT
    spot_content_id,
    MIN(price)::int AS min_price,
    ROUND(AVG(price))::int AS avg_price,
    MAX(menu_name) FILTER (WHERE representative_rank = 1) AS representative_menu_name,
    (MAX(price) FILTER (WHERE representative_rank = 1))::int AS representative_price,
    COUNT(*)::int AS menu_count,
    COUNT(DISTINCT food_place_id)::int AS source_count
  FROM ranked_menus
 GROUP BY spot_content_id
"""


class GoodPriceRepository:
    """fd_food_* 공통 테이블 저장 진입점."""

    async def upsert_place(self, parsed: ParsedFoodPlace) -> int:
        """장소/원천/메뉴/관측 이력을 한 트랜잭션으로 저장."""
        pool = await get_pool()
        async with pool.connection() as conn, conn.transaction():
            place_id = await self._find_place_id(conn, parsed.source)
            if place_id is None:
                place_id = await self._insert_place(conn, parsed.place)
            else:
                await self._update_place(conn, place_id, parsed.place)

            await self._upsert_source(conn, place_id, parsed.source)
            for menu in parsed.menus:
                await self._upsert_menu(conn, place_id, menu)
                if menu.price is not None:
                    await self._insert_observation(conn, place_id, menu)
            return place_id

    async def aggregate_spot_price_summaries(self) -> list[SpotPriceSummaryRecord]:
        """matched food place의 현재 메뉴 가격을 spot 기준으로 집계."""
        pool = await get_pool()
        async with pool.connection() as conn:
            row = await conn.execute(SPOT_PRICE_SUMMARY_AGGREGATE_SQL)
            records = await row.fetchall()
        return [_summary_record_from_row(record) for record in cast(list[dict[str, Any]], records)]

    async def refresh_spot_price_summary(
        self,
        *,
        dry_run: bool = False,
        prune_missing: bool = False,
    ) -> SpotPriceSummaryRefreshResult:
        """sp_spot_price_summary 캐시를 SQL 집계 결과로 upsert한다."""
        if dry_run:
            summaries = await self.aggregate_spot_price_summaries()
            return SpotPriceSummaryRefreshResult(
                aggregated_count=len(summaries),
                upserted_count=0,
                pruned_count=0,
                dry_run=True,
            )

        pool = await get_pool()
        async with pool.connection() as conn, conn.transaction():
            upserted_count = await self._upsert_spot_price_summaries(conn)
            pruned_count = 0
            if prune_missing:
                pruned_count = await self._prune_missing_spot_price_summaries(conn)
        return SpotPriceSummaryRefreshResult(
            aggregated_count=upserted_count,
            upserted_count=upserted_count,
            pruned_count=pruned_count,
            dry_run=False,
        )

    async def _upsert_spot_price_summaries(self, conn: AsyncConnection) -> int:
        row = await conn.execute(
            f"""
            INSERT INTO {SPOT_PRICE_SUMMARY_TABLE} (
                spot_content_id,
                min_price,
                avg_price,
                representative_menu_name,
                representative_price,
                menu_count,
                source_count,
                updated_at
            )
            SELECT
                spot_content_id,
                min_price,
                avg_price,
                representative_menu_name,
                representative_price,
                menu_count,
                source_count,
                NOW()
              FROM ({SPOT_PRICE_SUMMARY_AGGREGATE_SQL}) AS summary
            ON CONFLICT (spot_content_id) DO UPDATE SET
                min_price = EXCLUDED.min_price,
                avg_price = EXCLUDED.avg_price,
                representative_menu_name = EXCLUDED.representative_menu_name,
                representative_price = EXCLUDED.representative_price,
                menu_count = EXCLUDED.menu_count,
                source_count = EXCLUDED.source_count,
                updated_at = NOW()
            RETURNING spot_content_id
            """
        )
        records = await row.fetchall()
        return len(records)

    async def _prune_missing_spot_price_summaries(self, conn: AsyncConnection) -> int:
        row = await conn.execute(
            f"""
            DELETE FROM {SPOT_PRICE_SUMMARY_TABLE} AS cached
             WHERE NOT EXISTS (
                SELECT 1
                  FROM ({SPOT_PRICE_SUMMARY_AGGREGATE_SQL}) AS summary
                 WHERE summary.spot_content_id = cached.spot_content_id
             )
            RETURNING cached.spot_content_id
            """
        )
        records = await row.fetchall()
        return len(records)

    FOOD_PLACE_STORE_ENRICH_CANDIDATES_SQL = """
    WITH store_by_name AS (
        SELECT DISTINCT ON (fp.name)
            fp.name,
            fp.address,
            fp.tel,
            fp.source_region,
            fp.map_x,
            fp.map_y
          FROM fd_food_places AS fp
          JOIN fd_food_place_sources AS src
            ON src.food_place_id = fp.id
           AND src.source = 'good_price_store'
         WHERE fp.is_active = TRUE
           AND fp.address IS NOT NULL
           AND BTRIM(fp.address) <> ''
         ORDER BY fp.name, fp.id DESC
    )
    SELECT
        menu_fp.id AS food_place_id,
        store.address AS store_address,
        store.tel AS store_tel,
        store.source_region AS store_source_region,
        store.map_x AS store_map_x,
        store.map_y AS store_map_y,
        (menu_fp.address IS NULL OR BTRIM(menu_fp.address) = '') AS needs_address,
        (menu_fp.tel IS NULL OR BTRIM(menu_fp.tel) = '') AS needs_tel,
        (menu_fp.source_region IS NULL OR BTRIM(menu_fp.source_region) = '') AS needs_source_region,
        (menu_fp.map_x IS NULL OR menu_fp.map_y IS NULL) AS needs_coords
      FROM fd_food_places AS menu_fp
      JOIN fd_food_place_sources AS menu_src
        ON menu_src.food_place_id = menu_fp.id
       AND menu_src.source = 'good_price_menu'
      JOIN store_by_name AS store
        ON store.name = menu_fp.name
     WHERE menu_fp.is_active = TRUE
       AND (
            menu_fp.address IS NULL OR BTRIM(menu_fp.address) = ''
            OR menu_fp.tel IS NULL OR BTRIM(menu_fp.tel) = ''
            OR menu_fp.source_region IS NULL OR BTRIM(menu_fp.source_region) = ''
            OR menu_fp.map_x IS NULL OR menu_fp.map_y IS NULL
       )
     ORDER BY menu_fp.id
    """

    async def enrich_menu_places_from_store(
        self,
        *,
        dry_run: bool = False,
        limit: int | None = None,
    ) -> FoodPlaceStoreEnrichRunResult:
        """good_price_menu row에 good_price_store 메타데이터를 이름 기준으로 보강."""
        pool = await get_pool()
        async with pool.connection() as conn:
            menu_count_row = await conn.execute(
                """
                SELECT COUNT(*) AS cnt
                  FROM fd_food_places AS fp
                  JOIN fd_food_place_sources AS src
                    ON src.food_place_id = fp.id
                   AND src.source = 'good_price_menu'
                 WHERE fp.is_active = TRUE
                """
            )
            menu_places_scanned = int(
                cast(dict[str, Any], await menu_count_row.fetchone())["cnt"]
            )
            no_store_row = await conn.execute(
                """
                SELECT COUNT(*) AS cnt
                  FROM fd_food_places AS menu_fp
                  JOIN fd_food_place_sources AS menu_src
                    ON menu_src.food_place_id = menu_fp.id
                   AND menu_src.source = 'good_price_menu'
                 WHERE menu_fp.is_active = TRUE
                   AND NOT EXISTS (
                        SELECT 1
                          FROM fd_food_places AS store_fp
                          JOIN fd_food_place_sources AS store_src
                            ON store_src.food_place_id = store_fp.id
                           AND store_src.source = 'good_price_store'
                         WHERE store_fp.is_active = TRUE
                           AND store_fp.name = menu_fp.name
                           AND store_fp.address IS NOT NULL
                           AND BTRIM(store_fp.address) <> ''
                   )
                """
            )
            no_store_match = int(cast(dict[str, Any], await no_store_row.fetchone())["cnt"])

            candidate_sql = self.FOOD_PLACE_STORE_ENRICH_CANDIDATES_SQL
            params: list[Any] = []
            if limit is not None:
                candidate_sql += " LIMIT %s"
                params.append(limit)

            row = await conn.execute(candidate_sql, params)
            candidates = cast(list[dict[str, Any]], await row.fetchall())

        store_name_matches = len(candidates)
        address_filled = 0
        coords_filled = 0
        tel_filled = 0
        enrichable_ids: list[int] = []

        for candidate in candidates:
            food_place_id = int(candidate["food_place_id"])
            would_update = False
            if candidate["needs_address"] and candidate["store_address"]:
                address_filled += 1
                would_update = True
            if (
                candidate["needs_coords"]
                and candidate["store_map_x"] is not None
                and candidate["store_map_y"] is not None
            ):
                coords_filled += 1
                would_update = True
            if candidate["needs_tel"] and candidate["store_tel"]:
                tel_filled += 1
                would_update = True
            if would_update:
                enrichable_ids.append(food_place_id)

        enriched_count = len(enrichable_ids)
        if dry_run or not enrichable_ids:
            return FoodPlaceStoreEnrichRunResult(
                menu_places_scanned=menu_places_scanned,
                store_name_matches=store_name_matches,
                enriched_count=enriched_count,
                address_filled=address_filled,
                coords_filled=coords_filled,
                tel_filled=tel_filled,
                no_store_match=no_store_match,
                dry_run=dry_run,
            )

        async with pool.connection() as conn, conn.transaction():
            await conn.execute(
                """
                WITH store_by_name AS (
                    SELECT DISTINCT ON (fp.name)
                        fp.name,
                        fp.address,
                        fp.tel,
                        fp.source_region,
                        fp.map_x,
                        fp.map_y
                      FROM fd_food_places AS fp
                      JOIN fd_food_place_sources AS src
                        ON src.food_place_id = fp.id
                       AND src.source = 'good_price_store'
                     WHERE fp.is_active = TRUE
                       AND fp.address IS NOT NULL
                       AND BTRIM(fp.address) <> ''
                     ORDER BY fp.name, fp.id DESC
                )
                UPDATE fd_food_places AS menu_fp
                   SET address = COALESCE(
                           NULLIF(BTRIM(menu_fp.address), ''),
                           store.address
                       ),
                       tel = COALESCE(NULLIF(BTRIM(menu_fp.tel), ''), store.tel),
                       source_region = COALESCE(
                           NULLIF(BTRIM(menu_fp.source_region), ''),
                           store.source_region
                       ),
                       map_x = COALESCE(menu_fp.map_x, store.map_x),
                       map_y = COALESCE(menu_fp.map_y, store.map_y),
                       updated_at = NOW()
                  FROM store_by_name AS store
                 WHERE menu_fp.id = ANY(%s)
                   AND store.name = menu_fp.name
                   AND menu_fp.is_active = TRUE
                """,
                (enrichable_ids,),
            )

        return FoodPlaceStoreEnrichRunResult(
            menu_places_scanned=menu_places_scanned,
            store_name_matches=store_name_matches,
            enriched_count=enriched_count,
            address_filled=address_filled,
            coords_filled=coords_filled,
            tel_filled=tel_filled,
            no_store_match=no_store_match,
            dry_run=False,
        )

    async def run_food_spot_rule_matching(
        self,
        *,
        dry_run: bool = False,
        limit: int | None = None,
        rematch_pending: bool = False,
        max_distance_m: float = MAX_CANDIDATE_DISTANCE_M,
    ) -> FoodSpotMatchRunResult:
        """활성 fd_food_places를 TourAPI spots(39)와 룰 매칭해 fd_food_place_spot_matches를 채운다."""
        places = await self.list_places_for_matching(
            limit=limit,
            rematch_pending=rematch_pending,
        )
        matched_count = 0
        pending_count = 0
        separate_count = 0
        no_candidate_count = 0
        matches_upserted = 0

        for place in places:
            spot_candidates = await self.list_spot_candidates_for_place(
                place.food_place_id,
                max_distance_m=max_distance_m,
            )
            best_match = pick_best_match(place, spot_candidates)
            if best_match is None:
                no_candidate_count += 1
                continue

            if best_match.match_status == "matched":
                matched_count += 1
            elif best_match.match_status == "pending":
                pending_count += 1
            else:
                separate_count += 1

            if dry_run:
                continue

            await self.upsert_food_spot_match(place.food_place_id, best_match)
            matches_upserted += 1

        return FoodSpotMatchRunResult(
            places_scanned=len(places),
            matches_upserted=matches_upserted,
            matched_count=matched_count,
            pending_count=pending_count,
            separate_count=separate_count,
            no_candidate_count=no_candidate_count,
            dry_run=dry_run,
        )

    async def list_places_for_matching(
        self,
        *,
        limit: int | None = None,
        rematch_pending: bool = False,
    ) -> list[FoodPlaceMatchCandidate]:
        """매칭 대상 음식 장소 목록."""
        pool = await get_pool()
        sql = """
            SELECT
                fp.id,
                fp.name,
                fp.tel,
                fp.address,
                fp.map_x,
                fp.map_y
              FROM fd_food_places AS fp
             WHERE fp.is_active = TRUE
               AND fp.geog IS NOT NULL
               AND fp.normalized_category NOT IN ('beauty', 'bath', 'lodging')
               AND NOT EXISTS (
                    SELECT 1
                      FROM fd_food_place_spot_matches AS existing
                     WHERE existing.food_place_id = fp.id
                       AND existing.match_status = 'matched'
                       AND COALESCE(existing.match_method, '') IN ('manual', 'llm')
               )
               AND (
                    NOT EXISTS (
                        SELECT 1
                          FROM fd_food_place_spot_matches AS existing
                         WHERE existing.food_place_id = fp.id
                    )
                    OR (
                        %s
                        AND EXISTS (
                            SELECT 1
                              FROM fd_food_place_spot_matches AS existing
                             WHERE existing.food_place_id = fp.id
                               AND existing.match_status = 'pending'
                               AND COALESCE(existing.match_method, 'rule') = 'rule'
                        )
                    )
               )
             ORDER BY fp.id
        """
        params: list[Any] = [rematch_pending]
        if limit is not None:
            sql += " LIMIT %s"
            params.append(limit)

        async with pool.connection() as conn:
            row = await conn.execute(sql, params)
            records = await row.fetchall()

        return [
            FoodPlaceMatchCandidate(
                food_place_id=int(record["id"]),
                name=str(record["name"]),
                tel=record["tel"],
                address=record["address"],
                map_x=float(record["map_x"]) if record["map_x"] is not None else None,
                map_y=float(record["map_y"]) if record["map_y"] is not None else None,
            )
            for record in cast(list[dict[str, Any]], records)
        ]

    async def list_spot_candidates_for_place(
        self,
        food_place_id: int,
        *,
        max_distance_m: float = MAX_CANDIDATE_DISTANCE_M,
    ) -> list[SpotMatchCandidate]:
        """좌표 기준으로 근처(기본 200m) 음식점 스팟 후보를 조회.

        정확도는 Python 점수·근거·모호성 판정에서 결정한다.
        """
        pool = await get_pool()
        async with pool.connection() as conn:
            row = await conn.execute(
                f"""
                SELECT
                    spots.content_id,
                    spots.title,
                    details.tel,
                    TRIM(
                        COALESCE(details.addr1, '')
                        || CASE
                            WHEN details.addr2 IS NULL OR details.addr2 = '' THEN ''
                            ELSE ' ' || details.addr2
                           END
                    ) AS address,
                    ST_Distance(fp.geog, spots.geog)::float AS distance_m
                  FROM fd_food_places AS fp
                  JOIN {SPOTS_TABLE} AS spots
                    ON spots.is_active = TRUE
                   AND spots.content_type_id = '39'
                   AND spots.geog IS NOT NULL
                   AND ST_DWithin(fp.geog, spots.geog, %s)
                  JOIN {SPOT_DETAILS_TABLE} AS details
                    ON details.content_id = spots.content_id
                 WHERE fp.id = %s
                   AND fp.geog IS NOT NULL
                 ORDER BY ST_Distance(fp.geog, spots.geog), spots.content_id
                 LIMIT 30
                """,
                (max_distance_m, food_place_id),
            )
            records = await row.fetchall()

        return [
            SpotMatchCandidate(
                spot_content_id=str(record["content_id"]),
                title=str(record["title"]),
                tel=record["tel"],
                address=record["address"] or None,
                distance_m=float(record["distance_m"]) if record["distance_m"] is not None else None,
            )
            for record in cast(list[dict[str, Any]], records)
        ]

    async def upsert_food_spot_match(
        self,
        food_place_id: int,
        match: ScoredSpotMatch,
    ) -> None:
        """룰 매칭 결과를 fd_food_place_spot_matches에 반영."""
        pool = await get_pool()
        async with pool.connection() as conn, conn.transaction():
            await conn.execute(
                """
                DELETE FROM fd_food_place_spot_matches
                 WHERE food_place_id = %s
                   AND COALESCE(match_method, 'rule') = %s
                """,
                (food_place_id, MATCH_METHOD_RULE),
            )

            if match.match_status == "separate":
                await conn.execute(
                    """
                    INSERT INTO fd_food_place_spot_matches (
                        food_place_id,
                        spot_content_id,
                        match_score,
                        match_status,
                        match_method
                    ) VALUES (%s, NULL, %s, 'separate', %s)
                    """,
                    (food_place_id, match.match_score, MATCH_METHOD_RULE),
                )
                return

            await conn.execute(
                """
                INSERT INTO fd_food_place_spot_matches (
                    food_place_id,
                    spot_content_id,
                    match_score,
                    match_status,
                    match_method
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (food_place_id, spot_content_id) DO UPDATE SET
                    match_score = EXCLUDED.match_score,
                    match_status = EXCLUDED.match_status,
                    match_method = EXCLUDED.match_method,
                    updated_at = NOW()
                """,
                (
                    food_place_id,
                    match.spot_content_id,
                    match.match_score,
                    match.match_status,
                    MATCH_METHOD_RULE,
                ),
            )

    async def _find_place_id(
        self,
        conn: AsyncConnection,
        source: FoodPlaceSourceRecord,
    ) -> int | None:
        row = await conn.execute(
            """
            SELECT food_place_id
              FROM fd_food_place_sources
             WHERE source = %s
               AND external_id = %s
            """,
            (source.source, source.external_id),
        )
        result = await row.fetchone()
        if result is None:
            return None
        return int(cast(dict[str, Any], result)["food_place_id"])

    async def _insert_place(self, conn: AsyncConnection, place: FoodPlaceRecord) -> int:
        row = await conn.execute(
            """
            INSERT INTO fd_food_places (
                name, business_category, normalized_category, is_course_food_candidate,
                address, tel, business_hours_raw, description, representative_menu,
                delivery_available, parking_available, source_region, map_x, map_y, is_active
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s
            )
            RETURNING id
            """,
            (
                place.name,
                place.business_category,
                place.normalized_category,
                place.is_course_food_candidate,
                place.address,
                place.tel,
                place.business_hours_raw,
                place.description,
                place.representative_menu,
                place.delivery_available,
                place.parking_available,
                place.source_region,
                place.map_x,
                place.map_y,
                place.is_active,
            ),
        )
        result = await row.fetchone()
        if result is None:
            raise RuntimeError("fd_food_places INSERT did not return id")
        return int(cast(dict[str, Any], result)["id"])

    async def _update_place(
        self,
        conn: AsyncConnection,
        place_id: int,
        place: FoodPlaceRecord,
    ) -> None:
        await conn.execute(
            """
            UPDATE fd_food_places
               SET name = %s,
                   business_category = %s,
                   normalized_category = %s,
                   is_course_food_candidate = %s,
                   address = %s,
                   tel = %s,
                   business_hours_raw = %s,
                   description = %s,
                   representative_menu = %s,
                   delivery_available = %s,
                   parking_available = %s,
                   source_region = %s,
                   map_x = %s,
                   map_y = %s,
                   is_active = %s,
                   inactive_since = CASE WHEN %s THEN NULL ELSE inactive_since END
             WHERE id = %s
            """,
            (
                place.name,
                place.business_category,
                place.normalized_category,
                place.is_course_food_candidate,
                place.address,
                place.tel,
                place.business_hours_raw,
                place.description,
                place.representative_menu,
                place.delivery_available,
                place.parking_available,
                place.source_region,
                place.map_x,
                place.map_y,
                place.is_active,
                place.is_active,
                place_id,
            ),
        )

    async def _upsert_source(
        self,
        conn: AsyncConnection,
        place_id: int,
        source: FoodPlaceSourceRecord,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO fd_food_place_sources (
                food_place_id, source, external_id, source_region, raw_json, fetched_at
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (source, external_id) DO UPDATE SET
                food_place_id = EXCLUDED.food_place_id,
                source_region = EXCLUDED.source_region,
                raw_json = EXCLUDED.raw_json,
                fetched_at = EXCLUDED.fetched_at
            """,
            (
                place_id,
                source.source,
                source.external_id,
                source.source_region,
                Json(source.raw_json),
                source.fetched_at,
            ),
        )

    async def _upsert_menu(
        self,
        conn: AsyncConnection,
        place_id: int,
        menu: FoodPlaceMenuRecord,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO fd_food_place_menus (
                food_place_id, menu_name, price, currency, display_order,
                source, is_representative, last_observed_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (food_place_id, menu_name, source) DO UPDATE SET
                price = EXCLUDED.price,
                currency = EXCLUDED.currency,
                display_order = EXCLUDED.display_order,
                is_representative = EXCLUDED.is_representative,
                last_observed_at = EXCLUDED.last_observed_at
            """,
            (
                place_id,
                menu.menu_name,
                menu.price,
                menu.currency,
                menu.display_order,
                menu.source,
                menu.is_representative,
                menu.observed_at,
            ),
        )

    async def _insert_observation(
        self,
        conn: AsyncConnection,
        place_id: int,
        menu: FoodPlaceMenuRecord,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO fd_food_price_observations (
                food_place_id, menu_name, observed_price, currency, display_order,
                source_type, source, raw_payload, observed_at, review_status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                place_id,
                menu.menu_name,
                menu.price,
                menu.currency,
                menu.display_order,
                menu.source_type,
                menu.source,
                Json(menu.raw_payload) if menu.raw_payload is not None else None,
                menu.observed_at,
                menu.review_status,
            ),
        )


def build_spot_price_summary_records(
    candidates: Iterable[SpotPriceMenuCandidate],
) -> list[SpotPriceSummaryRecord]:
    """SQL 집계와 같은 규칙으로 후보 row를 요약한다.

    운영 경로는 SQL 집계를 사용하고, 이 함수는 대표 메뉴/필터 규칙을 작게 검증하기 위한
    순수 함수다.
    """
    grouped: dict[str, list[SpotPriceMenuCandidate]] = {}
    for candidate in candidates:
        if candidate.match_status != "matched":
            continue
        if candidate.spot_content_id is None:
            continue
        if candidate.price is None or candidate.price <= 0:
            continue
        grouped.setdefault(candidate.spot_content_id, []).append(candidate)

    summaries: list[SpotPriceSummaryRecord] = []
    for spot_content_id, rows in sorted(grouped.items()):
        prices = [cast(int, row.price) for row in rows]
        representative = min(
            rows,
            key=lambda row: (
                0 if row.is_representative else 1,
                cast(int, row.price),
                row.display_order if row.display_order is not None else 32_767,
                row.menu_name,
            ),
        )
        summaries.append(
            SpotPriceSummaryRecord(
                spot_content_id=spot_content_id,
                min_price=min(prices),
                avg_price=_round_price_average(prices),
                representative_menu_name=representative.menu_name,
                representative_price=cast(int, representative.price),
                menu_count=len(rows),
                source_count=len({row.food_place_id for row in rows}),
            )
        )
    return summaries


def _round_price_average(prices: list[int]) -> int:
    average = Decimal(sum(prices)) / Decimal(len(prices))
    return int(average.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _summary_record_from_row(row: dict[str, Any]) -> SpotPriceSummaryRecord:
    return SpotPriceSummaryRecord(
        spot_content_id=str(row["spot_content_id"]),
        min_price=int(row["min_price"]),
        avg_price=int(row["avg_price"]),
        representative_menu_name=str(row["representative_menu_name"]),
        representative_price=int(row["representative_price"]),
        menu_count=int(row["menu_count"]),
        source_count=int(row["source_count"]),
    )
