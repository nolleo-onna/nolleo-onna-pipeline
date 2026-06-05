"""Good Price 도메인 DB 접근 계층."""
from __future__ import annotations

from typing import Any, cast

from psycopg import AsyncConnection
from psycopg.types.json import Json

from nolleo_pipeline.common.db import get_pool
from nolleo_pipeline.domains.good_price.models import (
    FoodPlaceMenuRecord,
    FoodPlaceRecord,
    FoodPlaceSourceRecord,
    ParsedFoodPlace,
)


class GoodPriceRepository:
    """food_* 공통 테이블 저장 진입점."""

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

    async def _find_place_id(
        self,
        conn: AsyncConnection,
        source: FoodPlaceSourceRecord,
    ) -> int | None:
        row = await conn.execute(
            """
            SELECT food_place_id
              FROM food_place_sources
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
            INSERT INTO food_places (
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
            raise RuntimeError("food_places INSERT did not return id")
        return int(cast(dict[str, Any], result)["id"])

    async def _update_place(
        self,
        conn: AsyncConnection,
        place_id: int,
        place: FoodPlaceRecord,
    ) -> None:
        await conn.execute(
            """
            UPDATE food_places
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
            INSERT INTO food_place_sources (
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
            INSERT INTO food_place_menus (
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
            INSERT INTO food_price_observations (
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
