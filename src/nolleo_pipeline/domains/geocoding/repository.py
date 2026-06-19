"""Geocoding 도메인 DB 접근 계층."""
from __future__ import annotations

from typing import Any, cast

from nolleo_pipeline.common.db import get_pool
from nolleo_pipeline.domains.geocoding.models import (
    FoodPlaceGeocodeTarget,
    FoodPlaceInferenceTarget,
    GeocodeResult,
)


class GeocodingRepository:
    """지오코딩 결과를 fd_food_places에 반영."""

    async def list_food_places_missing_coordinates(
        self,
        *,
        limit: int | None = None,
    ) -> list[FoodPlaceGeocodeTarget]:
        """좌표가 비어 있고 주소가 있는 활성 음식 장소 목록."""
        pool = await get_pool()
        sql = """
            SELECT id, name, address
              FROM fd_food_places
             WHERE is_active = TRUE
               AND address IS NOT NULL
               AND BTRIM(address) <> ''
               AND (map_x IS NULL OR map_y IS NULL)
             ORDER BY id
        """
        params: list[Any] = []
        if limit is not None:
            sql += " LIMIT %s"
            params.append(limit)

        async with pool.connection() as conn:
            row = await conn.execute(sql, params)
            records = await row.fetchall()

        return [
            FoodPlaceGeocodeTarget(
                food_place_id=int(record["id"]),
                name=str(record["name"]),
                address=str(record["address"]),
            )
            for record in cast(list[dict[str, Any]], records)
        ]

    async def list_food_places_missing_location(
        self,
        *,
        limit: int | None = None,
    ) -> list[FoodPlaceInferenceTarget]:
        """주소·좌표가 비어 있는 활성 음식 장소 목록."""
        pool = await get_pool()
        sql = """
            SELECT
                fp.id,
                fp.name,
                fp.tel,
                fp.source_region,
                fp.representative_menu
              FROM fd_food_places AS fp
             WHERE fp.is_active = TRUE
               AND (fp.address IS NULL OR BTRIM(fp.address) = '')
               AND (fp.map_x IS NULL OR fp.map_y IS NULL)
             ORDER BY fp.id
        """
        params: list[Any] = []
        if limit is not None:
            sql += " LIMIT %s"
            params.append(limit)

        async with pool.connection() as conn:
            row = await conn.execute(sql, params)
            records = await row.fetchall()

            targets: list[FoodPlaceInferenceTarget] = []
            for record in cast(list[dict[str, Any]], records):
                food_place_id = int(record["id"])
                menu_row = await conn.execute(
                    """
                    SELECT menu_name
                      FROM fd_food_place_menus
                     WHERE food_place_id = %s
                     ORDER BY
                         CASE WHEN is_representative THEN 0 ELSE 1 END,
                         display_order ASC NULLS LAST,
                         menu_name ASC
                     LIMIT 8
                    """,
                    (food_place_id,),
                )
                menu_records = await menu_row.fetchall()
                menu_names = tuple(
                    str(menu["menu_name"])
                    for menu in cast(list[dict[str, Any]], menu_records)
                )
                targets.append(
                    FoodPlaceInferenceTarget(
                        food_place_id=food_place_id,
                        name=str(record["name"]),
                        tel=record["tel"],
                        source_region=record["source_region"],
                        representative_menu=record["representative_menu"],
                        menu_names=menu_names,
                    )
                )
        return targets

    async def update_food_place_coordinates(
        self,
        food_place_id: int,
        result: GeocodeResult,
    ) -> None:
        """지오코딩 결과를 fd_food_places 좌표 컬럼에 반영."""
        pool = await get_pool()
        async with pool.connection() as conn, conn.transaction():
            await conn.execute(
                """
                UPDATE fd_food_places
                   SET map_x = %s,
                       map_y = %s,
                       updated_at = NOW()
                 WHERE id = %s
                """,
                (result.map_x, result.map_y, food_place_id),
            )

    async def update_food_place_location(
        self,
        food_place_id: int,
        *,
        address: str,
        result: GeocodeResult,
    ) -> None:
        """추론된 주소와 좌표를 fd_food_places에 반영."""
        pool = await get_pool()
        async with pool.connection() as conn, conn.transaction():
            await conn.execute(
                """
                UPDATE fd_food_places
                   SET address = %s,
                       map_x = %s,
                       map_y = %s,
                       updated_at = NOW()
                 WHERE id = %s
                """,
                (address, result.map_x, result.map_y, food_place_id),
            )
